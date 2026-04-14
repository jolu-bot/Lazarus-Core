#pragma once
#include "types.h"
#include "disk_reader.h"
#include <string>

namespace lazarus {

class FileRebuilder {
public:
    FileRebuilder(DiskReader* reader, uint64_t cluster_size,
                  const std::string& output_dir);

    bool rebuild(const RecoveredFile& file, std::string& out_path);
    bool rebuild_from_runs(const std::vector<ClusterRun>& runs,
                           uint64_t real_size,
                           const std::string& filename,
                           std::string& out_path);

private:
    DiskReader*  m_reader;
    uint64_t     m_cluster_size;
    std::string  m_output_dir;

    static constexpr size_t IO_BUFFER = 1 * 1024 * 1024; // 1MB chunks
};

} // namespace lazarus
