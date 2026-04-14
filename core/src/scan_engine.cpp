#include "../../include/scan_engine.h"
#include <filesystem>
#include <algorithm>
#include <chrono>

namespace lazarus {

ScanEngine::ScanEngine(const ScanOptions& opts,
                        FileFoundCallback  on_file,
                        ProgressCallback   on_progress)
    : m_opts(opts), m_on_file(std::move(on_file)),
      m_on_progress(std::move(on_progress)) {}

ScanEngine::~ScanEngine() { stop(); }

bool ScanEngine::is_running() const { return m_running.load(); }
const std::vector<RecoveredFile>& ScanEngine::get_results() const { return m_results; }
ScanProgress ScanEngine::get_progress() const {
    std::lock_guard<std::mutex> lock(m_progress_mutex);
    return m_progress;
}

void ScanEngine::add_result(RecoveredFile& file) {
    file.id = m_files_found.fetch_add(1);
    std::lock_guard<std::mutex> lk(m_results_mutex);
    m_results.push_back(file);
    m_on_file(file);
}

void ScanEngine::update_progress(const ScanProgress& p) {
    std::lock_guard<std::mutex> lk(m_progress_mutex);
    m_progress = p;
    m_on_progress(p);
}

FileSystem ScanEngine::detect_filesystem() {
    uint8_t buf[512];
    if (!m_reader->read_bytes(0, 512, buf)) return FileSystem::UNKNOWN;

    // NTFS: check OEM ID
    if (std::memcmp(buf + 3, "NTFS    ", 8) == 0) return FileSystem::NTFS;

    // EXT: check magic at offset 0x438
    uint8_t ext_buf[2];
    if (m_reader->read_bytes(0x438, 2, ext_buf))
        if (ext_buf[0] == 0x53 && ext_buf[1] == 0xEF) return FileSystem::EXT4;

    // APFS: check at offset 0x20
    uint8_t apfs_buf[4];
    if (m_reader->read_bytes(0x20, 4, apfs_buf))
        if (std::memcmp(apfs_buf, "NXSB", 4) == 0) return FileSystem::APFS;

    return FileSystem::UNKNOWN;
}

void ScanEngine::start() {
    if (m_running.exchange(true)) return;
    std::filesystem::create_directories(m_opts.output_dir);

    m_reader = std::make_unique<DiskReader>(m_opts.device_path);
    if (!m_reader->open()) {
        m_running.store(false);
        ScanProgress err;
        err.finished = true;
        err.current_path = "ERROR: Cannot open device";
        update_progress(err);
        return;
    }

    size_t threads = m_opts.thread_count > 0
        ? m_opts.thread_count
        : std::max(2u, std::thread::hardware_concurrency());
    m_pool = std::make_unique<ThreadPool>(threads);

    auto fs_type = detect_filesystem();

    auto file_cb = [this](const RecoveredFile& f) {
        RecoveredFile copy = f;
        add_result(copy);
    };
    auto prog_cb = [this](const ScanProgress& p) {
        update_progress(p);
    };

    if (m_opts.scan_ntfs && (fs_type == FileSystem::NTFS || fs_type == FileSystem::UNKNOWN)) {
        auto fut = m_pool->enqueue([this, file_cb, prog_cb] { run_ntfs_scan(); });
    }
    if (m_opts.scan_ext4 && (fs_type == FileSystem::EXT4 || fs_type == FileSystem::UNKNOWN)) {
        auto fut = m_pool->enqueue([this, file_cb, prog_cb] { run_ext4_scan(); });
    }
    if (m_opts.scan_apfs && (fs_type == FileSystem::APFS || fs_type == FileSystem::UNKNOWN)) {
        auto fut = m_pool->enqueue([this, file_cb, prog_cb] { run_apfs_scan(); });
    }
    if (m_opts.enable_carving) {
        auto fut = m_pool->enqueue([this, file_cb, prog_cb] { run_carving_scan(); });
    }

    // Wait in background thread
    std::thread([this] {
        m_pool->wait_all();
        m_running.store(false);
        ScanProgress done;
        done.finished         = true;
        done.files_found      = m_files_found.load();
        done.files_recoverable = m_files_found.load();
        done.percent          = 100.f;
        update_progress(done);
    }).detach();
}

void ScanEngine::stop() {
    m_running.store(false);
    if (m_pool) m_pool->shutdown();
}

void ScanEngine::run_ntfs_scan() {
    NTFSParser parser(m_reader.get());
    if (!parser.parse_boot_sector()) return;

    parser.scan_mft(
        [this](const RecoveredFile& f) { RecoveredFile c=f; add_result(c); },
        [this](const ScanProgress& p)  { update_progress(p); }
    );
}

void ScanEngine::run_ext4_scan() {
    Ext4Parser parser(m_reader.get());
    if (!parser.parse_superblock()) return;

    parser.scan_inodes(
        [this](const RecoveredFile& f) { RecoveredFile c=f; add_result(c); },
        [this](const ScanProgress& p)  { update_progress(p); }
    );
}

void ScanEngine::run_apfs_scan() {
    ApfsParser parser(m_reader.get());
    if (!parser.parse_container()) return;

    parser.scan_volumes(
        [this](const RecoveredFile& f) { RecoveredFile c=f; add_result(c); },
        [this](const ScanProgress& p)  { update_progress(p); }
    );
}

void ScanEngine::run_carving_scan() {
    FileCarver carver(
        m_reader.get(),
        m_opts.output_dir + "/carved",
        [this](const RecoveredFile& f) { RecoveredFile c=f; add_result(c); },
        [this](const ScanProgress& p)  { update_progress(p); }
    );
    carver.load_default_signatures();
    carver.carve(m_opts.start_sector, m_opts.end_sector);
}

} // namespace lazarus
