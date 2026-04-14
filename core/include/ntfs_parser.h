#pragma once
#include "types.h"
#include "disk_reader.h"
#include <vector>
#include <memory>
#include <cstdint>
#include <string>

namespace lazarus {

// NTFS Boot Sector (BPB)
#pragma pack(push, 1)
struct NTFSBootSector {
    uint8_t  jump[3];
    uint8_t  oem_id[8];
    uint16_t bytes_per_sector;
    uint8_t  sectors_per_cluster;
    uint8_t  reserved[7];
    uint8_t  media_descriptor;
    uint8_t  reserved2[2];
    uint16_t sectors_per_track;
    uint16_t num_heads;
    uint32_t hidden_sectors;
    uint8_t  reserved3[8];
    uint64_t total_sectors;
    uint64_t mft_lcn;
    uint64_t mft_mirror_lcn;
    int8_t   clusters_per_mft;
    int8_t   reserved4[3];
    int8_t   clusters_per_index;
    int8_t   reserved5[3];
    uint64_t volume_serial;
    uint32_t checksum;
    uint8_t  boot_code[426];
    uint16_t end_marker;
};
#pragma pack(pop)

// MFT File Record header
#pragma pack(push, 1)
struct MFTFileRecord {
    uint8_t  signature[4];   // "FILE"
    uint16_t update_seq_offset;
    uint16_t update_seq_count;
    uint64_t log_seq_number;
    uint16_t sequence_number;
    uint16_t hard_link_count;
    uint16_t first_attr_offset;
    uint16_t flags;           // 0x01=in-use, 0x02=directory
    uint32_t bytes_in_use;
    uint32_t bytes_allocated;
    uint64_t base_file_record;
    uint16_t next_attr_id;
    uint16_t reserved;
    uint32_t mft_record_number;
};
#pragma pack(pop)

// Attribute header (resident)
#pragma pack(push, 1)
struct AttrHeader {
    uint32_t type;
    uint32_t length;
    uint8_t  non_resident;
    uint8_t  name_length;
    uint16_t name_offset;
    uint16_t flags;
    uint16_t attr_id;
};
#pragma pack(pop)

// Non-resident attribute extension
#pragma pack(push, 1)
struct NonResidentAttr {
    uint64_t start_vcn;
    uint64_t last_vcn;
    uint16_t data_run_offset;
    uint16_t compression_unit;
    uint32_t reserved;
    uint64_t allocated_size;
    uint64_t data_size;
    uint64_t init_size;
};
#pragma pack(pop)

// FILENAME attribute content
#pragma pack(push, 1)
struct FileNameAttr {
    uint64_t parent_ref;
    uint64_t created;
    uint64_t modified;
    uint64_t mft_modified;
    uint64_t accessed;
    uint64_t alloc_size;
    uint64_t real_size;
    uint32_t flags;
    uint32_t reparse;
    uint8_t  name_len;
    uint8_t  name_type;
    uint16_t name[1]; // UTF-16
};
#pragma pack(pop)

class NTFSParser {
public:
    explicit NTFSParser(DiskReader* reader);
    ~NTFSParser() = default;

    bool   parse_boot_sector();
    bool   is_valid() const;

    void   scan_mft(const FileFoundCallback& on_file,
                    const ProgressCallback&  on_progress);

    bool   extract_file(const RecoveredFile& file,
                        const std::string&   output_path);

    uint64_t get_cluster_size() const { return m_cluster_size; }
    uint64_t get_mft_offset()   const { return m_mft_offset;   }

private:
    DiskReader*      m_reader;
    NTFSBootSector   m_boot{};
    uint64_t         m_cluster_size = 0;
    uint64_t         m_mft_offset   = 0;
    uint64_t         m_mft_size     = 0;
    bool             m_valid = false;

    bool parse_mft_record(const uint8_t* buf, uint32_t record_size,
                          uint64_t record_no, RecoveredFile& out);
    std::vector<ClusterRun> parse_data_runs(const uint8_t* runs, size_t max_len);
    std::string read_utf16_name(const uint16_t* src, size_t len);
    FileType    classify_extension(const std::string& ext);
    void        apply_fixup(uint8_t* record, uint32_t size,
                             uint16_t seq_offset, uint16_t seq_count);
};

} // namespace lazarus
