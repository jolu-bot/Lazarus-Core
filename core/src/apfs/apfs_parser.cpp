#include "../../include/apfs_parser.h"
#include <cstring>
#include <algorithm>
#include <string>

namespace lazarus {

// ─── APFS internal structs (translation-unit scope) ─────────────
#pragma pack(push,1)
struct OmapKey  { uint64_t ok_oid,ok_xid; };
struct OmapVal  { uint32_t ov_flags,ov_size; uint64_t ov_paddr; };
struct OmapPhys { uint8_t o_cksum[8];uint64_t o_oid,o_xid;uint32_t o_type,o_subtype; uint32_t om_flags,om_snap_count,om_tree_type,om_snap_tree_type; uint64_t om_tree_oid,om_snap_tree_oid; uint32_t om_most_recent_snap,om_pending_revert_min,om_pending_revert_max; };
struct BtNode   { uint8_t btn_o[32]; uint16_t btn_flags,btn_level; uint32_t btn_nkeys; uint16_t btn_table_space_off,btn_table_space_len,btn_free_space_off,btn_free_space_len,btn_key_free_list_off,btn_key_free_list_len,btn_val_free_list_off,btn_val_free_list_len; };
struct KVoff    { uint16_t k,v; };
struct KVloc    { uint16_t off,len; };
struct JKey     { uint64_t obj_id_and_type; };
struct JInode   { uint64_t parent_id,private_id,create_time,mod_time,change_time,access_time,internal_flags; int32_t nlink; uint32_t def_prot_class,write_gen_counter,bsd_flags,owner,group; uint16_t mode,pad1; uint64_t uncompressed_size; };
struct JExtent  { uint64_t len_and_flags,phys_block_num,crypto_id; };
struct VolSB    { uint8_t o[32]; uint32_t apfs_magic,apfs_fs_index; uint64_t apfs_features,apfs_readonly_compat,apfs_incompat,apfs_unmount_time,apfs_fs_reserve,apfs_fs_quota,apfs_fs_alloc; uint8_t meta_crypto[32]; uint32_t root_tree_type,extref_tree_type,snap_meta_tree_type,pad; uint64_t omap_oid,root_tree_oid; };
#pragma pack(pop)

static constexpr uint64_t JT_MASK  = 0xF000000000000000ULL;
static constexpr uint64_t JT_SHIFT = 60;
static constexpr uint64_t JOI_MASK = 0x0FFFFFFFFFFFFFFFULL;
static constexpr int JTYPE_INODE   = 3;
static constexpr int JTYPE_DIRREC  = 9;
static constexpr int JTYPE_EXTENT  = 8;
static constexpr uint16_t BTN_LEAF  = 0x0002;
static constexpr uint16_t BTN_ROOT  = 0x0001;
static constexpr uint16_t BTN_FIXED = 0x0004;

ApfsParser::ApfsParser(DiskReader* reader,uint64_t offset):m_reader(reader),m_offset(offset){}

bool ApfsParser::parse_container(){
    std::vector<uint8_t> buf(4096);
    if(!m_reader->read_bytes(m_offset,4096,buf.data()))return false;
    auto* nx=reinterpret_cast<APFSNxSuperblock*>(buf.data());
    if(nx->nx_magic!=APFS_MAGIC_NX)return false;
    std::memcpy(&m_nx,nx,sizeof(m_nx));
    m_block_size=m_nx.nx_block_size?m_nx.nx_block_size:4096;
    m_valid=true; return true;
}
bool ApfsParser::is_valid()const{return m_valid;}
uint64_t ApfsParser::block_to_offset(uint64_t b)const{return m_offset+b*m_block_size;}
bool ApfsParser::read_block(uint64_t paddr,std::vector<uint8_t>& buf)const{
    buf.resize(m_block_size);
    return m_reader->read_bytes(block_to_offset(paddr),m_block_size,buf.data());
}

// ─── omap B-tree lookup: OmapKey→OmapVal.ov_paddr ───────────────
uint64_t ApfsParser::omap_btree_lookup(uint64_t paddr,uint64_t oid,uint64_t xid_max)const{
    std::vector<uint8_t> buf;
    if(!read_block(paddr,buf))return 0;
    auto* nd=reinterpret_cast<BtNode*>(buf.data());
    const uint8_t* base=buf.data();
    const uint8_t* ka=base+sizeof(BtNode);
    size_t ve=m_block_size; if(nd->btn_flags&BTN_ROOT)ve-=40;
    bool leaf=(nd->btn_flags&BTN_LEAF)!=0;
    uint32_t nk=nd->btn_nkeys; if(nk>512)return 0;
    uint64_t best_xid=0,best_paddr=0;
    for(uint32_t i=0;i<nk;i++){
        auto* toc=reinterpret_cast<const KVoff*>(ka+nd->btn_table_space_off);
        uint16_t koff=toc[i].k, voff=toc[i].v;
        const uint8_t* kp=ka+koff;
        if(kp+sizeof(OmapKey)>base+m_block_size)continue;
        auto* ok=reinterpret_cast<const OmapKey*>(kp);
        if(ok->ok_oid!=oid||ok->ok_xid>xid_max)continue;
        if(leaf){
            if(ve<sizeof(OmapVal)+voff)continue;
            auto* ov=reinterpret_cast<const OmapVal*>(base+ve-voff-sizeof(OmapVal));
            if(ok->ok_xid>best_xid){best_xid=ok->ok_xid;best_paddr=ov->ov_paddr;}
        } else {
            if(ve<8+voff)continue;
            uint64_t child; std::memcpy(&child,base+ve-voff-8,8);
            uint64_t r=omap_btree_lookup(child,oid,xid_max);
            if(r)return r;
        }
    }
    return best_paddr;
}

// ─── omap_lookup: resolve OmapPhys header → omap_btree ──────────
uint64_t ApfsParser::omap_lookup(uint64_t omap_paddr,uint64_t oid)const{
    std::vector<uint8_t> buf;
    if(!read_block(omap_paddr,buf))return 0;
    auto* om=reinterpret_cast<OmapPhys*>(buf.data());
    uint32_t otype=om->o_type&0xFFFF;
    if(otype==0x000B)
        return omap_btree_lookup(om->om_tree_oid,oid,UINT64_MAX);
    return omap_btree_lookup(omap_paddr,oid,UINT64_MAX);
}

// ─── walk_fstree: recurse FS B-tree collecting inodes & extents ──
void ApfsParser::walk_fstree(uint64_t paddr,uint64_t vol_omap,
                              ApfsInodeMap& inodes,ApfsExtentMap& extents)const{
    std::vector<uint8_t> buf;
    if(!read_block(paddr,buf))return;
    auto* nd=reinterpret_cast<BtNode*>(buf.data());
    const uint8_t* base=buf.data();
    const uint8_t* ka=base+sizeof(BtNode);
    size_t ve=m_block_size; if(nd->btn_flags&BTN_ROOT)ve-=40;
    bool leaf=(nd->btn_flags&BTN_LEAF)!=0;
    uint32_t nk=nd->btn_nkeys; if(nk>4096)return;
    auto* toc=reinterpret_cast<const KVloc*>(ka+nd->btn_table_space_off);
    for(uint32_t i=0;i<nk;i++){
        const KVloc* ktoc=toc+i*2;
        const KVloc* vtoc=toc+i*2+1;
        const uint8_t* kp=ka+ktoc->off;
        if(kp+sizeof(JKey)>base+m_block_size)continue;
        auto* jk=reinterpret_cast<const JKey*>(kp);
        uint64_t oid=jk->obj_id_and_type&JOI_MASK;
        int jtype=(int)((jk->obj_id_and_type&JT_MASK)>>JT_SHIFT);
        if(!leaf){
            if(vtoc->off+8>ve)continue;
            uint64_t child_oid; std::memcpy(&child_oid,base+ve-vtoc->off-8,8);
            uint64_t cp=omap_lookup(vol_omap,child_oid);
            if(cp)walk_fstree(cp,vol_omap,inodes,extents);
            continue;
        }
        // Leaf: extract record by type
        const uint8_t* vp=base+ve-vtoc->off;
        if(jtype==JTYPE_INODE&&vtoc->len>=sizeof(JInode)){
            auto* ji=reinterpret_cast<const JInode*>(vp);
            ApfsInodeInfo ii; ii.inode_id=oid; ii.parent_id=ji->parent_id; ii.mode=ji->mode;
            ii.size=ji->uncompressed_size; ii.nlink=ji->nlink; ii.mod_ns=ji->mod_time;
            auto it=inodes.find(oid);
            if(it!=inodes.end()){ii.name=it->second.name;inodes[oid]=ii;}
            else inodes[oid]=ii;
        } else if(jtype==JTYPE_DIRREC){
            const char* nm=reinterpret_cast<const char*>(kp+sizeof(JKey)+4);
            size_t ml=(base+m_block_size)-(const uint8_t*)nm;
            std::string name(nm,strnlen(nm,std::min(ml,(size_t)255)));
            uint64_t child_oid=0; if(vtoc->len>=8)std::memcpy(&child_oid,vp,8);
            inodes[child_oid].name=name; inodes[child_oid].parent_id=oid;
        } else if(jtype==JTYPE_EXTENT&&vtoc->len>=sizeof(JExtent)){
            auto* fe=reinterpret_cast<const JExtent*>(vp);
            uint64_t len=fe->len_and_flags&0x00FFFFFFFFFFFFFFULL;
            if(fe->phys_block_num>0&&len>0){
                ApfsExtentInfo e; e.inode_id=oid; e.phys_block=fe->phys_block_num; e.length=len;
                uint64_t loff=0; if(ktoc->len>=sizeof(JKey)+8)std::memcpy(&loff,kp+sizeof(JKey),8);
                e.logical_off=loff;
                extents[oid].push_back(e);
            }
        }
    }
}

// ─── scan_volumes: entry point ──────────────────────────────────
void ApfsParser::scan_volumes(const FileFoundCallback& on_file,const ProgressCallback& on_progress){
    if(!m_valid){ScanProgress d;d.finished=true;d.percent=100.f;on_progress(d);return;}
    // Scan up to 64K blocks for APSB volumes
    uint64_t scan_end=std::min(m_nx.nx_block_count,(uint64_t)65536);
    std::vector<uint64_t> vol_paddrs;
    std::vector<uint8_t> buf;
    for(uint64_t blk=1;blk<scan_end&&vol_paddrs.size()<32;blk++){
        if(!read_block(blk,buf))continue;
        uint32_t magic=0; std::memcpy(&magic,buf.data()+32,4); // after ObjPhys (32 bytes)
        if(magic==APFS_MAGIC_APSB)vol_paddrs.push_back(blk);
    }
    if(vol_paddrs.empty()){ScanProgress d;d.finished=true;d.percent=100.f;on_progress(d);return;}
    uint64_t total_found=0;
    for(size_t vi=0;vi<vol_paddrs.size();vi++){
        ScanProgress prog; prog.percent=(float)vi/vol_paddrs.size()*90.f; on_progress(prog);
        if(!read_block(vol_paddrs[vi],buf))continue;
        auto* vol=reinterpret_cast<VolSB*>(buf.data());
        if(vol->apfs_magic!=APFS_MAGIC_APSB)continue;
        if(!vol->root_tree_oid||!vol->omap_oid)continue;
        uint64_t fs_root=omap_lookup(vol->omap_oid,vol->root_tree_oid);
        if(!fs_root)continue;
        ApfsInodeMap inodes; ApfsExtentMap extents;
        walk_fstree(fs_root,vol->omap_oid,inodes,extents);
        // Emit RecoveredFile for each regular inode
        for(auto& [inode_id,info]:inodes){
            if((info.mode&0xF000)!=0x8000)continue;
            RecoveredFile rf;
            rf.inode=inode_id; rf.size=info.size;
            rf.name=info.name.empty()?"inode_"+std::to_string(inode_id):info.name;
            auto dot=rf.name.rfind('.'); if(dot!=std::string::npos)rf.extension=rf.name.substr(dot);
            rf.status=(info.nlink<=0)?FileStatus::DELETED:FileStatus::ACTIVE;
            rf.fs=FileSystem::APFS; rf.recoverable=!extents[inode_id].empty();
            rf.confidence=rf.recoverable?0.9f:0.3f;
            for(auto& e:extents[inode_id]){ClusterRun cr;cr.lcn=(int64_t)e.phys_block;cr.length=(e.length+m_block_size-1)/m_block_size;rf.runs.push_back(cr);}
            on_file(rf); ++total_found;
            if(total_found%100==0){ScanProgress p;p.files_found=total_found;p.percent=prog.percent;on_progress(p);}
        }
    }
    ScanProgress done;done.finished=true;done.percent=100.f;done.files_found=total_found;on_progress(done);
}

} // namespace lazarus
