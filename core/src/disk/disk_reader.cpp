#include "../../include/disk_reader.h"
#include <cstring>
#include <stdexcept>
#include <algorithm>

#ifdef _WIN32
#include <winioctl.h>
#include <setupapi.h>
#pragma comment(lib, "setupapi.lib")
#endif

namespace lazarus {

DiskReader::DiskReader(const std::string& device_path)
    : m_path(device_path) {}

DiskReader::~DiskReader() { close(); }

bool DiskReader::open() {
#ifdef _WIN32
    m_handle = CreateFileA(
        m_path.c_str(),
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        nullptr,
        OPEN_EXISTING,
        FILE_FLAG_NO_BUFFERING | FILE_FLAG_RANDOM_ACCESS,
        nullptr
    );
    if (m_handle == INVALID_HANDLE_VALUE) return false;
    return query_geometry();
#else
    m_fd = ::open(m_path.c_str(), O_RDONLY | O_LARGEFILE);
    if (m_fd < 0) return false;
    return query_geometry_posix();
#endif
}

void DiskReader::close() {
#ifdef _WIN32
    if (m_handle != INVALID_HANDLE_VALUE) {
        CloseHandle(m_handle);
        m_handle = INVALID_HANDLE_VALUE;
    }
#else
    if (m_fd >= 0) { ::close(m_fd); m_fd = -1; }
#endif
}

bool DiskReader::is_open() const {
#ifdef _WIN32
    return m_handle != INVALID_HANDLE_VALUE;
#else
    return m_fd >= 0;
#endif
}

bool DiskReader::read_sectors(uint64_t lba, uint32_t count, uint8_t* buffer) {
    uint64_t offset = lba * static_cast<uint64_t>(m_sector_size);
    uint32_t bytes  = count * m_sector_size;
    return read_bytes(offset, bytes, buffer);
}

bool DiskReader::read_bytes(uint64_t offset, uint32_t length, uint8_t* buffer) {
    if (!is_open() || length == 0) return false;
#ifdef _WIN32
    // Align to sector boundary for unbuffered I/O
    uint64_t aligned_offset = (offset / m_sector_size) * m_sector_size;
    uint32_t lead           = static_cast<uint32_t>(offset - aligned_offset);
    uint32_t aligned_len    = ((lead + length + m_sector_size - 1) / m_sector_size) * m_sector_size;

    std::vector<uint8_t> tmp(aligned_len);

    LARGE_INTEGER li;
    li.QuadPart = static_cast<LONGLONG>(aligned_offset);
    if (!SetFilePointerEx(m_handle, li, nullptr, FILE_BEGIN)) return false;

    DWORD read = 0;
    if (!ReadFile(m_handle, tmp.data(), aligned_len, &read, nullptr)) return false;
    if (read < lead + length) return false;

    std::memcpy(buffer, tmp.data() + lead, length);
    return true;
#else
    ssize_t r = pread(m_fd, buffer, length, static_cast<off_t>(offset));
    return r == static_cast<ssize_t>(length);
#endif
}

uint64_t DiskReader::get_total_sectors() const { return m_total_sectors; }
uint32_t DiskReader::get_sector_size()   const { return m_sector_size;   }
uint64_t DiskReader::get_total_size()    const { return m_total_sectors * m_sector_size; }

DiskInfo DiskReader::get_disk_info() const {
    DiskInfo info;
    info.device_path  = m_path;
    info.total_size   = get_total_size();
    info.sector_size  = m_sector_size;
    info.cluster_size = 0;
    info.fs_type      = FileSystem::UNKNOWN;
    return info;
}

#ifdef _WIN32
bool DiskReader::query_geometry() {
    DISK_GEOMETRY_EX geom{};
    DWORD bytes = 0;
    if (DeviceIoControl(m_handle, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX,
                        nullptr, 0, &geom, sizeof(geom), &bytes, nullptr)) {
        m_sector_size   = geom.Geometry.BytesPerSector;
        m_total_sectors = geom.DiskSize.QuadPart / m_sector_size;
        return true;
    }
    // Fallback: use GetFileSizeEx for image files
    LARGE_INTEGER sz{};
    if (GetFileSizeEx(m_handle, &sz)) {
        m_sector_size   = 512;
        m_total_sectors = sz.QuadPart / 512;
        return m_total_sectors > 0;
    }
    return false;
}

std::vector<DiskInfo> DiskReader::enumerate_drives() {
    std::vector<DiskInfo> drives;
    for (int i = 0; i < 16; ++i) {
        std::string path = "\\\\.\\PhysicalDrive" + std::to_string(i);
        HANDLE h = CreateFileA(path.c_str(), GENERIC_READ,
                               FILE_SHARE_READ | FILE_SHARE_WRITE,
                               nullptr, OPEN_EXISTING,
                               FILE_FLAG_NO_BUFFERING, nullptr);
        if (h == INVALID_HANDLE_VALUE) continue;

        DISK_GEOMETRY_EX geom{};
        DWORD bytes = 0;
        DiskInfo di;
        di.device_path = path;
        if (DeviceIoControl(h, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX,
                            nullptr, 0, &geom, sizeof(geom), &bytes, nullptr)) {
            di.sector_size  = geom.Geometry.BytesPerSector;
            di.total_size   = geom.DiskSize.QuadPart;
        }
        // Get drive label via volume
        char vol[MAX_PATH] = {};
        std::string volPath = "\\\\.\\PhysicalDrive" + std::to_string(i);
        di.label   = "PhysicalDrive" + std::to_string(i);
        di.fs_type = FileSystem::UNKNOWN;
        drives.push_back(di);
        CloseHandle(h);
    }
    return drives;
}
#else
bool DiskReader::query_geometry_posix() {
#include <sys/ioctl.h>
#ifdef __APPLE__
    uint32_t ssize = 512;
    uint64_t total = 0;
    ioctl(m_fd, DKIOCGETBLOCKSIZE, &ssize);
    ioctl(m_fd, DKIOCGETBLOCKCOUNT, &total);
    m_sector_size   = ssize;
    m_total_sectors = total;
#else // Linux
    uint64_t total = 0;
    ioctl(m_fd, BLKGETSIZE64, &total);
    m_sector_size   = 512;
    m_total_sectors = total / 512;
#endif
    return m_total_sectors > 0;
}

std::vector<DiskInfo> DiskReader::enumerate_drives() {
    std::vector<DiskInfo> drives;
    // On Linux scan /dev/sd?, /dev/nvme*, /dev/disk*
    for (char c = 'a'; c <= 'z'; ++c) {
        std::string path = "/dev/sd";
        path += c;
        DiskInfo di; di.device_path = path;
        drives.push_back(di);
    }
    return drives;
}
#endif

} // namespace lazarus
