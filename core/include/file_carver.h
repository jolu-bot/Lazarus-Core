#pragma once
#include "types.h"
#include "disk_reader.h"
#include <vector>
#include <string>
#include <functional>
#include <cstdint>

namespace lazarus {

struct CarverSignature {
    std::string   type;
    std::string   extension;
    FileType      file_type;
    std::vector<uint8_t> header;
    std::vector<uint8_t> footer;       // empty = use size heuristic
    uint64_t      max_size;            // 0 = unlimited
    bool          use_footer;
};

struct CarvedFile {
    uint64_t    start_offset;
    uint64_t    end_offset;
    uint64_t    size;
    std::string extension;
    FileType    file_type;
    bool        complete;     // footer found
    float       confidence;
};

class FileCarver {
public:
    FileCarver(DiskReader* reader,
               const std::string& output_dir,
               const FileFoundCallback& on_found,
               const ProgressCallback&  on_progress);

    void add_signature(const CarverSignature& sig);
    void load_default_signatures();

    void carve(uint64_t start_sector = 0, uint64_t end_sector = 0);
    void stop();

private:
    DiskReader*      m_reader;
    std::string      m_output_dir;
    FileFoundCallback m_on_found;
    ProgressCallback  m_on_progress;
    std::vector<CarverSignature> m_signatures;
    bool             m_stop = false;

    static constexpr size_t BUFFER_SIZE = 4 * 1024 * 1024; // 4MB
    static constexpr size_t OVERLAP     = 32;               // header overlap

    bool match_header(const uint8_t* buf, size_t buf_len,
                      const CarverSignature& sig, size_t offset);
    bool match_footer(const uint8_t* buf, size_t buf_len,
                      const CarverSignature& sig, size_t offset);
    bool save_carved_file(const CarvedFile& cf, const uint8_t* data, size_t len,
                          uint64_t counter, std::string& out_path);
    RecoveredFile make_recovered(const CarvedFile& cf,
                                 const std::string& path, uint64_t id);
};

} // namespace lazarus
