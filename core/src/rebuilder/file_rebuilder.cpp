#include "../../include/file_rebuilder.h"
#include <fstream>
#include <filesystem>
#include <algorithm>
#include <sstream>
#include <iomanip>

namespace lazarus {

FileRebuilder::FileRebuilder(DiskReader* reader, uint64_t cluster_size,
                              const std::string& output_dir)
    : m_reader(reader), m_cluster_size(cluster_size), m_output_dir(output_dir) {}

bool FileRebuilder::rebuild(const RecoveredFile& file, std::string& out_path) {
    if (file.runs.empty()) return false;
    std::filesystem::create_directories(m_output_dir);

    // Sanitize filename
    std::string safe_name = file.name;
    for (char& c : safe_name)
        if (c == '/' || c == '\\' || c == ':' || c == '*' || c == '?' ||
            c == '"' || c == '<' || c == '>' || c == '|') c = '_';

    out_path = m_output_dir + "/" + safe_name;

    // Avoid overwrite collision
    if (std::filesystem::exists(out_path)) {
        std::ostringstream ss;
        ss << m_output_dir << "/"
           << std::hex << std::setw(8) << std::setfill('0') << file.mft_ref
           << "_" << safe_name;
        out_path = ss.str();
    }

    return rebuild_from_runs(file.runs, file.size, safe_name, out_path);
}

bool FileRebuilder::rebuild_from_runs(const std::vector<ClusterRun>& runs,
                                       uint64_t real_size,
                                       const std::string& /*filename*/,
                                       std::string& out_path) {
    std::ofstream out(out_path, std::ios::binary | std::ios::trunc);
    if (!out) return false;

    std::vector<uint8_t> buf(IO_BUFFER);
    uint64_t remaining = real_size;

    for (const auto& run : runs) {
        if (remaining == 0) break;

        if (run.lcn < 0) {
            // Sparse run: write zeros
            uint64_t sparse = run.length * m_cluster_size;
            uint64_t to_zero = std::min(sparse, remaining);
            std::vector<uint8_t> zeros(std::min<uint64_t>(to_zero, IO_BUFFER), 0);
            while (to_zero > 0) {
                uint64_t chunk = std::min<uint64_t>(to_zero, IO_BUFFER);
                out.write(reinterpret_cast<const char*>(zeros.data()), chunk);
                to_zero  -= chunk;
                remaining -= chunk;
            }
            continue;
        }

        for (uint64_t c = 0; c < run.length && remaining > 0; ) {
            // Read multiple clusters at once up to IO_BUFFER
            uint64_t clusters_in_buf = IO_BUFFER / m_cluster_size;
            uint64_t clusters_to_read = std::min<uint64_t>(
                clusters_in_buf, run.length - c);
            uint64_t max_from_remaining =
                (remaining + m_cluster_size - 1) / m_cluster_size;
            clusters_to_read = std::min(clusters_to_read, max_from_remaining);

            uint64_t offset = static_cast<uint64_t>(run.lcn + c) * m_cluster_size;
            uint32_t bytes  = static_cast<uint32_t>(clusters_to_read * m_cluster_size);

            if (buf.size() < bytes) buf.resize(bytes);
            if (!m_reader->read_bytes(offset, bytes, buf.data())) {
                // Partial failure: write zeros for unreadable clusters
                std::fill(buf.begin(), buf.begin() + bytes, 0);
            }

            uint64_t to_write = std::min<uint64_t>(bytes, remaining);
            out.write(reinterpret_cast<const char*>(buf.data()),
                      static_cast<std::streamsize>(to_write));
            remaining -= to_write;
            c += clusters_to_read;
        }
    }

    return !out.fail();
}

} // namespace lazarus
