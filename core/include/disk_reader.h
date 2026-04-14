#pragma once
#include "types.h"
#include <string>
#include <vector>
#include <memory>
#include <cstdint>

#ifdef _WIN32
  #include <windows.h>
#else
  #include <fcntl.h>
  #include <unistd.h>
#endif

namespace lazarus {

class DiskReader {
public:
    explicit DiskReader(const std::string& device_path);
    ~DiskReader();

    bool        open();
    void        close();
    bool        is_open() const;

    bool        read_sectors(uint64_t lba, uint32_t count, uint8_t* buffer);
    bool        read_bytes(uint64_t offset, uint32_t length, uint8_t* buffer);

    uint64_t    get_total_sectors() const;
    uint32_t    get_sector_size()   const;
    uint64_t    get_total_size()    const;
    DiskInfo    get_disk_info()     const;

    static std::vector<DiskInfo> enumerate_drives();

private:
    std::string  m_path;
    uint32_t     m_sector_size  = 512;
    uint64_t     m_total_sectors = 0;

#ifdef _WIN32
    HANDLE       m_handle = INVALID_HANDLE_VALUE;
    bool         query_geometry();
#else
    int          m_fd = -1;
    bool         query_geometry_posix();
#endif
};

} // namespace lazarus
