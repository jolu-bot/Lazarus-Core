#include "../../include/ext4_parser.h"
#include <cstring>
#include <fstream>
#include <filesystem>
#include <algorithm>
#include <sstream>
#include <iomanip>

namespace lazarus {

static constexpr uint16_t EXT4_MAGIC   = 0xEF53;
static constexpr uint64_t SUPERBLOCK_OFFSET = 1024;
static constexpr uint32_t ROOT_INODE   = 2;

Ext4Parser::Ext4Parser(DiskReader* reader, uint64_t partition_offset)
    : m_reader(reader), m_partition_offset(partition_offset) {}

bool Ext4Parser::parse_superblock() {
    uint8_t buf[1024];
    if (!m_reader->read_bytes(m_partition_offset + SUPERBLOCK_OFFSET, 1024, buf))
        return false;
    std::memcpy(&m_sb, buf, sizeof(m_sb));

    if (m_sb.s_magic != EXT4_MAGIC) return false;

    m_block_size      = 1024u << m_sb.s_log_block_size;
    m_inodes_per_group = m_sb.s_inodes_per_group;
    m_inode_size       = (m_sb.s_rev_level >= 1) ? m_sb.s_inode_size : 128;

    uint32_t total_blocks = m_sb.s_blocks_count_lo;
    m_group_count = (total_blocks + m_sb.s_blocks_per_group - 1) /
                     m_sb.s_blocks_per_group;

    m_valid = true;
    return true;
}

bool Ext4Parser::is_valid() const { return m_valid; }

uint64_t Ext4Parser::block_to_offset(uint32_t block) const {
    return m_partition_offset + static_cast<uint64_t>(block) * m_block_size;
}

bool Ext4Parser::read_inode(uint32_t inode_no, Ext4Inode& out) {
    if (!m_valid || inode_no == 0) return false;
    uint32_t group   = (inode_no - 1) / m_inodes_per_group;
    uint32_t index   = (inode_no - 1) % m_inodes_per_group;

    if (group >= m_group_count) return false;

    // Group descriptor is after superblock
    // Group descriptor table starts at block 1 (or 2 if block_size==1024)
    uint64_t gdt_block = (m_block_size == 1024) ? 2 : 1;
    uint64_t gdt_offset = block_to_offset(static_cast<uint32_t>(gdt_block));

    // Each group descriptor is 32 bytes (64 in ext4 with 64bit feature)
    uint32_t desc_size = 32;
    uint8_t  gdt_buf[64];
    if (!m_reader->read_bytes(gdt_offset + group * desc_size, desc_size, gdt_buf))
        return false;

    uint32_t inode_table_block;
    std::memcpy(&inode_table_block, gdt_buf + 8, 4); // bg_inode_table_lo

    uint64_t inode_offset = block_to_offset(inode_table_block) +
                            static_cast<uint64_t>(index) * m_inode_size;

    uint8_t ibuf[256];
    uint32_t read_size = std::min<uint32_t>(m_inode_size, sizeof(ibuf));
    if (!m_reader->read_bytes(inode_offset, read_size, ibuf)) return false;

    std::memcpy(&out, ibuf, std::min<size_t>(read_size, sizeof(Ext4Inode)));
    return true;
}

std::vector<uint32_t> Ext4Parser::get_inode_blocks(const Ext4Inode& inode) {
    std::vector<uint32_t> blocks;
    // Direct blocks
    for (int i = 0; i < 12; ++i)
        if (inode.i_block[i]) blocks.push_back(inode.i_block[i]);
    // Indirect blocks (simplified - direct only for now)
    return blocks;
}

void Ext4Parser::scan_inodes(const FileFoundCallback& on_file,
                              const ProgressCallback&  on_progress) {
    if (!m_valid) return;

    uint32_t total_inodes = m_sb.s_inodes_count;
    uint64_t files_found = 0;

    for (uint32_t ino = 1; ino <= total_inodes; ++ino) {
        Ext4Inode inode{};
        if (!read_inode(ino, inode)) continue;

        // Skip directories and special files
        bool is_regular = (inode.i_mode & 0xF000) == 0x8000;
        bool is_deleted  = (inode.i_dtime > 0);

        if (!is_regular && !is_deleted) continue;
        if (inode.i_size_lo == 0 && inode.i_size_high == 0) continue;

        RecoveredFile rf;
        rf.id       = ino;
        rf.inode    = ino;
        rf.fs       = FileSystem::EXT4;
        rf.size     = (static_cast<uint64_t>(inode.i_size_high) << 32) |
                       inode.i_size_lo;
        rf.status   = is_deleted ? FileStatus::DELETED : FileStatus::ACTIVE;
        rf.recoverable = true;
        rf.confidence  = is_deleted ? 0.65f : 0.92f;

        // Try to detect extension from data
        auto blks = get_inode_blocks(inode);
        std::string ext;
        if (!blks.empty()) {
            uint8_t magic[8] = {};
            m_reader->read_bytes(block_to_offset(blks[0]), 8, magic);
            if (magic[0]==0xFF && magic[1]==0xD8) ext = "jpg";
            else if (magic[0]==0x89 && magic[1]==0x50) ext = "png";
            else if (magic[0]==0x25 && magic[1]==0x50) ext = "pdf";
            else ext = "bin";
        } else ext = "bin";

        rf.name      = "inode_" + std::to_string(ino) + "." + ext;
        rf.extension = ext;

        on_file(rf);
        ++files_found;

        if (ino % 1000 == 0) {
            ScanProgress prog;
            prog.sectors_total   = total_inodes;
            prog.sectors_scanned = ino;
            prog.files_found     = files_found;
            prog.files_recoverable = files_found;
            prog.percent = static_cast<float>(ino) / total_inodes * 100.f;
            prog.finished = false;
            on_progress(prog);
        }
    }

    ScanProgress done;
    done.sectors_total    = total_inodes;
    done.sectors_scanned  = total_inodes;
    done.files_found      = files_found;
    done.files_recoverable = files_found;
    done.percent  = 100.f;
    done.finished = true;
    on_progress(done);
}

bool Ext4Parser::extract_file(const RecoveredFile& file,
                               const std::string& output_path) {
    Ext4Inode inode{};
    if (!read_inode(static_cast<uint32_t>(file.inode), inode)) return false;

    std::ofstream out(output_path, std::ios::binary | std::ios::trunc);
    if (!out) return false;

    auto blocks  = get_inode_blocks(inode);
    uint64_t rem = file.size;
    std::vector<uint8_t> buf(m_block_size);

    for (uint32_t blk : blocks) {
        if (rem == 0) break;
        uint32_t to_read = static_cast<uint32_t>(
            std::min<uint64_t>(rem, m_block_size));
        if (!m_reader->read_bytes(block_to_offset(blk), to_read, buf.data()))
            break;
        out.write(reinterpret_cast<const char*>(buf.data()), to_read);
        rem -= to_read;
    }
    return !out.fail();
}

} // namespace lazarus
