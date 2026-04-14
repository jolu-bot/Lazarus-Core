#pragma once
#include "types.h"
#include "disk_reader.h"
#include <vector>
#include <cstdint>

namespace lazarus {

#pragma pack(push, 1)
struct Ext4Superblock {
    uint32_t s_inodes_count;
    uint32_t s_blocks_count_lo;
    uint32_t s_r_blocks_count_lo;
    uint32_t s_free_blocks_count_lo;
    uint32_t s_free_inodes_count;
    uint32_t s_first_data_block;
    uint32_t s_log_block_size;      // block_size = 1024 << s_log_block_size
    uint32_t s_log_cluster_size;
    uint32_t s_blocks_per_group;
    uint32_t s_clusters_per_group;
    uint32_t s_inodes_per_group;
    uint32_t s_mtime;
    uint32_t s_wtime;
    uint16_t s_mnt_count;
    uint16_t s_max_mnt_count;
    uint16_t s_magic;               // 0xEF53
    uint16_t s_state;
    uint16_t s_errors;
    uint16_t s_minor_rev_level;
    uint32_t s_lastcheck;
    uint32_t s_checkinterval;
    uint32_t s_creator_os;
    uint32_t s_rev_level;
    uint16_t s_def_resuid;
    uint16_t s_def_resgid;
    uint32_t s_first_ino;
    uint16_t s_inode_size;
    uint16_t s_block_group_nr;
    uint32_t s_feature_compat;
    uint32_t s_feature_incompat;
    uint32_t s_feature_ro_compat;
    uint8_t  s_uuid[16];
    char     s_volume_name[16];
    // ... rest of superblock (1024 bytes total)
    uint8_t  padding[764];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct Ext4Inode {
    uint16_t i_mode;
    uint16_t i_uid;
    uint32_t i_size_lo;
    uint32_t i_atime;
    uint32_t i_ctime;
    uint32_t i_mtime;
    uint32_t i_dtime;     // deletion time > 0 means deleted
    uint16_t i_gid;
    uint16_t i_links_count;
    uint32_t i_blocks_lo;
    uint32_t i_flags;
    uint32_t i_osd1;
    uint32_t i_block[15]; // 12 direct + ind + dind + tind
    uint32_t i_generation;
    uint32_t i_file_acl_lo;
    uint32_t i_size_high;
    uint32_t i_obso_faddr;
    uint8_t  i_osd2[12];
    uint16_t i_extra_isize;
    uint16_t i_checksum_hi;
    uint32_t i_ctime_extra;
    uint32_t i_mtime_extra;
    uint32_t i_atime_extra;
    uint32_t i_crtime;
    uint32_t i_crtime_extra;
    uint32_t i_version_hi;
    uint32_t i_projid;
};
#pragma pack(pop)

class Ext4Parser {
public:
    explicit Ext4Parser(DiskReader* reader, uint64_t partition_offset = 0);

    bool parse_superblock();
    bool is_valid() const;

    void scan_inodes(const FileFoundCallback& on_file,
                     const ProgressCallback&  on_progress);

    bool extract_file(const RecoveredFile& file, const std::string& output_path);

private:
    DiskReader* m_reader;
    uint64_t    m_partition_offset;
    Ext4Superblock m_sb{};
    bool        m_valid = false;
    uint32_t    m_block_size = 0;
    uint32_t    m_inodes_per_group = 0;
    uint32_t    m_inode_size = 256;
    uint32_t    m_group_count = 0;

    bool read_inode(uint32_t inode_no, Ext4Inode& out);
    uint64_t block_to_offset(uint32_t block) const;
    std::vector<uint32_t> get_inode_blocks(const Ext4Inode& inode);
    std::string detect_extension(uint32_t inode_no);
};

} // namespace lazarus
