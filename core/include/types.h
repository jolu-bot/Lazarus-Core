#pragma once
#include <cstdint>
#include <string>
#include <vector>
#include <functional>

namespace lazarus {

enum class FileSystem { UNKNOWN, NTFS, EXT4, APFS, FAT32, RAW };
enum class FileStatus { ACTIVE, DELETED, FRAGMENTED, PARTIAL };
enum class FileType   { UNKNOWN, IMAGE, VIDEO, AUDIO, DOCUMENT, ARCHIVE, OTHER };

struct ClusterRun {
    int64_t  lcn;    // Logical Cluster Number (-1 = sparse)
    uint64_t length; // Length in clusters
};

struct RecoveredFile {
    uint64_t              id;
    std::string           name;
    std::string           extension;
    uint64_t              size;
    uint64_t              mft_ref;
    uint64_t              inode;
    FileStatus            status;
    FileType              type;
    FileSystem            fs;
    std::vector<ClusterRun> runs;
    std::string           path;
    bool                  recoverable;
    float                 confidence; // 0.0 - 1.0
    std::string           preview_path;
};

struct ScanProgress {
    uint64_t sectors_total;
    uint64_t sectors_scanned;
    uint64_t files_found;
    uint64_t files_recoverable;
    float    percent;
    bool     finished;
    std::string current_path;
};

struct DiskInfo {
    std::string device_path;
    std::string label;
    uint64_t    total_size;
    uint64_t    sector_size;
    uint64_t    cluster_size;
    FileSystem  fs_type;
};

using ProgressCallback = std::function<void(const ScanProgress&)>;
using FileFoundCallback = std::function<void(const RecoveredFile&)>;

} // namespace lazarus
