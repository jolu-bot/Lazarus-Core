#pragma once
#include "types.h"
#include "disk_reader.h"
#include <cstdint>
#include <string>
#include <vector>
#include <unordered_map>

namespace lazarus {

static constexpr uint32_t APFS_MAGIC_NX=0x4253584E;
static constexpr uint32_t APFS_MAGIC_APSB=0x42535041;

#pragma pack(push,1)
struct APFSObjPhys{uint8_t o_cksum[8];uint64_t o_oid;uint64_t o_xid;uint32_t o_type;uint32_t o_subtype;};
struct APFSNxSuperblock{
    APFSObjPhys nx_o;
    uint32_t nx_magic,nx_block_size;
    uint64_t nx_block_count,nx_features,nx_readonly_compatible_features,nx_incompatible_features;
    uint8_t nx_uuid[16];
    uint64_t nx_next_oid,nx_next_xid;
    uint32_t nx_xp_desc_blocks,nx_xp_data_blocks;
    int64_t nx_xp_desc_base,nx_xp_data_base;
    uint32_t nx_xp_desc_next,nx_xp_data_next,nx_xp_desc_index,nx_xp_desc_len,nx_xp_data_index,nx_xp_data_len;
    uint64_t nx_spaceman_oid,nx_omap_oid,nx_reaper_oid;
};
#pragma pack(pop)
struct ApfsInodeInfo{uint64_t inode_id=0,parent_id=0,size=0,mod_ns=0;uint16_t mode=0;int32_t nlink=1;std::string name;};
struct ApfsExtentInfo{uint64_t inode_id=0,logical_off=0,phys_block=0,length=0;};
using ApfsInodeMap=std::unordered_map<uint64_t,ApfsInodeInfo>;
using ApfsExtentMap=std::unordered_map<uint64_t,std::vector<ApfsExtentInfo>>;

class ApfsParser{
public:
    explicit ApfsParser(DiskReader* reader,uint64_t offset=0);
    bool parse_container();
    bool is_valid() const;
    void scan_volumes(const FileFoundCallback& on_file,const ProgressCallback& on_progress);
private:
    DiskReader* m_reader; uint64_t m_offset;
    APFSNxSuperblock m_nx{}; bool m_valid=false; uint32_t m_block_size=4096;
    uint64_t block_to_offset(uint64_t block) const;
    bool read_block(uint64_t paddr,std::vector<uint8_t>& buf) const;
    uint64_t omap_btree_lookup(uint64_t btree_paddr,uint64_t oid,uint64_t xid_max) const;
    uint64_t omap_lookup(uint64_t omap_paddr,uint64_t oid) const;
    void walk_fstree(uint64_t paddr,uint64_t vol_omap_paddr,ApfsInodeMap& inodes,ApfsExtentMap& extents) const;
};

} // namespace lazarus
