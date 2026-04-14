#include "../../include/apfs_parser.h"
#include <cstring>

namespace lazarus {

ApfsParser::ApfsParser(DiskReader* reader, uint64_t offset)
    : m_reader(reader), m_offset(offset) {}

bool ApfsParser::parse_container() {
    uint8_t buf[4096];
    if (!m_reader->read_bytes(m_offset, 4096, buf)) return false;

    auto* nx = reinterpret_cast<APFSNxSuperblock*>(buf);
    if (nx->nx_magic != APFS_MAGIC_NX) return false;

    std::memcpy(&m_nx, nx, sizeof(m_nx));
    m_block_size = m_nx.nx_block_size;
    m_valid = true;
    return true;
}

bool ApfsParser::is_valid() const { return m_valid; }

uint64_t ApfsParser::block_to_offset(uint64_t block) const {
    return m_offset + block * m_block_size;
}

void ApfsParser::scan_volumes(const FileFoundCallback& /*on_file*/,
                               const ProgressCallback&  on_progress) {
    // APFS B-tree parsing is complex; minimal skeleton here
    // Full implementation requires object map traversal
    ScanProgress done;
    done.finished = true;
    done.percent  = 100.f;
    on_progress(done);
}

} // namespace lazarus
