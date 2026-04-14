#pragma once
#include "types.h"
#include "disk_reader.h"
#include <cstdint>
#include <string>

namespace lazarus {

// APFS Container Superblock magic
static constexpr uint32_t APFS_MAGIC_NX   = 0x4253584E; // 'NXSB'
static constexpr uint32_t APFS_MAGIC_APSB = 0x42535041; // 'APSB'

#pragma pack(push, 1)
struct APFSObjPhys {
    uint8_t  o_cksum[8];
    uint64_t o_oid;
    uint64_t o_xid;
    uint32_t o_type;
    uint32_t o_subtype;
};

struct APFSNxSuperblock {
    APFSObjPhys nx_o;
    uint32_t    nx_magic;
    uint32_t    nx_block_size;
    uint64_t    nx_block_count;
    uint64_t    nx_features;
    uint64_t    nx_readonly_compatible_features;
    uint64_t    nx_incompatible_features;
    uint8_t     nx_uuid[16];
    uint64_t    nx_next_oid;
    uint64_t    nx_next_xid;
    uint32_t    nx_xp_desc_blocks;
    uint32_t    nx_xp_data_blocks;
    int64_t     nx_xp_desc_base;
    int64_t     nx_xp_data_base;
    uint32_t    nx_xp_desc_next;
    uint32_t    nx_xp_data_next;
    uint32_t    nx_xp_desc_index;
    uint32_t    nx_xp_desc_len;
    uint32_t    nx_xp_data_index;
    uint32_t    nx_xp_data_len;
    uint64_t    nx_spaceman_oid;
    uint64_t    nx_omap_oid;
    uint64_t    nx_reaper_oid;
    // simplified - full struct is larger
};
#pragma pack(pop)

class ApfsParser {
public:
    explicit ApfsParser(DiskReader* reader, uint64_t offset = 0);

    bool parse_container();
    bool is_valid() const;

    void scan_volumes(const FileFoundCallback& on_file,
                      const ProgressCallback&  on_progress);

private:
    DiskReader*     m_reader;
    uint64_t        m_offset;
    APFSNxSuperblock m_nx{};
    bool            m_valid = false;
    uint32_t        m_block_size = 4096;

    uint64_t block_to_offset(uint64_t block) const;
    bool     verify_checksum(const uint8_t* buf, size_t size) const;
};

} // namespace lazarus
