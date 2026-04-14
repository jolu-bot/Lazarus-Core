#pragma once
#include "types.h"
#include "disk_reader.h"
#include "ntfs_parser.h"
#include "ext4_parser.h"
#include "apfs_parser.h"
#include "file_carver.h"
#include "thread_pool.h"
#include <memory>
#include <atomic>
#include <string>
#include <vector>

namespace lazarus {

struct ScanOptions {
    std::string device_path;
    std::string output_dir;
    bool        scan_ntfs     = true;
    bool        scan_ext4     = true;
    bool        scan_apfs     = true;
    bool        enable_carving = true;
    bool        deep_scan     = false;
    size_t      thread_count  = 0; // 0 = auto
    uint64_t    start_sector  = 0;
    uint64_t    end_sector    = 0; // 0 = all
    std::vector<std::string> target_extensions; // empty = all
};

class ScanEngine {
public:
    ScanEngine(const ScanOptions& opts,
               FileFoundCallback  on_file,
               ProgressCallback   on_progress);
    ~ScanEngine();

    void start();
    void stop();
    bool is_running() const;
    ScanProgress get_progress() const;
    const std::vector<RecoveredFile>& get_results() const;

private:
    ScanOptions              m_opts;
    FileFoundCallback        m_on_file;
    ProgressCallback         m_on_progress;

    std::unique_ptr<DiskReader>   m_reader;
    std::unique_ptr<ThreadPool>   m_pool;

    mutable std::mutex       m_results_mutex;
    std::vector<RecoveredFile> m_results;
    std::atomic<bool>        m_running{false};
    std::atomic<uint64_t>    m_files_found{0};
    ScanProgress             m_progress{};
    mutable std::mutex       m_progress_mutex;

    FileSystem detect_filesystem();
    void run_ntfs_scan();
    void run_ext4_scan();
    void run_apfs_scan();
    void run_carving_scan();
    void add_result(RecoveredFile& file);
    void update_progress(const ScanProgress& p);
};

} // namespace lazarus
