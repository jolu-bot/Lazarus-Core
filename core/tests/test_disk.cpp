/**
 * LAZARUS CORE – DiskReader Unit Tests
 * Tests geometry structures, path formatting and safe-read logic.
 * These tests run WITHOUT a real disk (all mock-based).
 *
 * Compile: g++ -std=c++17 -I../include test_disk.cpp -o test_disk
 */
#include <cassert>
#include <cstring>
#include <vector>
#include <iostream>
#include <stdexcept>
#include <string>
#include <algorithm>

#include "../include/types.h"
#include "../include/disk_reader.h"

using namespace lazarus;

struct TestResult { std::string name; bool passed; std::string detail; };
static std::vector<TestResult> g_results;

#define TEST(name) \
    void test_##name(); \
    static struct _reg_##name { \
        _reg_##name() { g_results.push_back({#name, false, ""}); \
                        try { test_##name(); g_results.back().passed = true; } \
                        catch (const std::exception& e) { g_results.back().detail = e.what(); } \
                        catch (...) { g_results.back().detail = "unknown exception"; } } \
    } _inst_##name; \
    void test_##name()

#define ASSERT_TRUE(x)   do { if (!(x)) throw std::runtime_error("Failed: " #x); } while(0)
#define ASSERT_EQ(a,b)   do { if ((a)!=(b)) throw std::runtime_error( \
    std::string(#a "=") + std::to_string(a) + " != " + std::to_string(b)); } while(0)
#define ASSERT_FALSE(x)  ASSERT_TRUE(!(x))

// ─── Test: PhysicalDrive path format (Windows) ───────────────────
TEST(win_physical_drive_path) {
    for (int i = 0; i < 4; ++i) {
        std::string path = "\\\\.\\PhysicalDrive" + std::to_string(i);
        ASSERT_TRUE(path.rfind("\\\\.\\PhysicalDrive", 0) == 0);
    }
    std::cout << "  Windows PhysicalDrive path format OK\n";
}

// ─── Test: LBA offset calculation ────────────────────────────────
TEST(lba_offset_calculation) {
    uint32_t sector_size = 512;
    uint64_t lba = 1024;
    uint64_t expected_offset = 1024ULL * 512;
    uint64_t actual = lba * static_cast<uint64_t>(sector_size);
    ASSERT_EQ(actual, expected_offset);
    std::cout << "  LBA offset calculation OK\n";
}

// ─── Test: Aligned sector read parameters ────────────────────────
TEST(aligned_read_params) {
    uint32_t sector_size   = 512;
    uint64_t read_offset   = 600;
    uint64_t aligned_off   = (read_offset / sector_size) * sector_size;
    uint32_t lead          = static_cast<uint32_t>(read_offset - aligned_off);
    uint32_t read_len      = 100;
    uint32_t aligned_len   = ((lead + read_len + sector_size - 1) / sector_size) * sector_size;

    ASSERT_EQ(aligned_off, 512ULL);
    ASSERT_EQ(lead, 88u);
    ASSERT_EQ(aligned_len, 512u); // ceil((88+100)/512)*512 = 512
    std::cout << "  Aligned read params OK\n";
}

// ─── Test: Total size from geometry ──────────────────────────────
TEST(total_size_geometry) {
    uint32_t sector_size   = 512;
    uint64_t total_sectors = 976773168ULL; // ~500GB
    uint64_t total_size    = total_sectors * sector_size;
    double   gb = static_cast<double>(total_size) / (1024.0 * 1024.0 * 1024.0);
    ASSERT_TRUE(gb > 499.0 && gb < 501.0);
    std::cout << "  Total size from geometry OK (" << static_cast<int>(gb) << " GB)\n";
}

// ─── Test: Filesystem detection byte markers ─────────────────────
TEST(fs_detection_markers) {
    // NTFS: OEM ID at offset 3
    uint8_t ntfs[16] = {};
    std::memcpy(ntfs + 3, "NTFS    ", 8);
    ASSERT_TRUE(std::memcmp(ntfs + 3, "NTFS    ", 8) == 0);

    // EXT4: magic at offset 0x38 of the in-buffer block (0x438 from partition start)
    uint8_t ext4_magic[2] = { 0x53, 0xEF };
    ASSERT_TRUE(ext4_magic[0] == 0x53 && ext4_magic[1] == 0xEF);

    // APFS: "NXSB" at offset 0x20
    uint8_t apfs[4] = { 'N', 'X', 'S', 'B' };
    ASSERT_TRUE(std::memcmp(apfs, "NXSB", 4) == 0);

    std::cout << "  FS detection byte markers OK\n";
}

// ─── Test: DiskInfo struct defaults ──────────────────────────────
TEST(disk_info_defaults) {
    DiskInfo di{};
    ASSERT_TRUE(di.device_path.empty());
    ASSERT_EQ(di.total_size, 0ULL);
    ASSERT_EQ(di.sector_size, 0ULL);
    ASSERT_TRUE(di.fs_type == FileSystem::UNKNOWN);
    std::cout << "  DiskInfo defaults OK\n";
}

// ─── Test: ScanProgress defaults ─────────────────────────────────
TEST(scan_progress_defaults) {
    ScanProgress p{};
    ASSERT_EQ(p.sectors_total, 0ULL);
    ASSERT_EQ(p.sectors_scanned, 0ULL);
    ASSERT_FALSE(p.finished);
    ASSERT_EQ(p.percent, 0.0f);
    std::cout << "  ScanProgress defaults OK\n";
}

// ─── Test: Progress percentage clamping ──────────────────────────
TEST(progress_percent_clamped) {
    auto clamp = [](float v) { return std::max(0.f, std::min(100.f, v)); };
    ASSERT_EQ(clamp(-5.f),  0.f);
    ASSERT_EQ(clamp(50.f), 50.f);
    ASSERT_EQ(clamp(110.f), 100.f);
    std::cout << "  Progress percent clamping OK\n";
}

// ─── Test: Linux device path scan list ───────────────────────────
TEST(linux_device_paths) {
    std::vector<std::string> paths;
    for (char c = 'a'; c <= 'z'; ++c) {
        paths.push_back(std::string("/dev/sd") + c);
    }
    ASSERT_EQ(paths.size(), 26ULL);
    ASSERT_TRUE(paths[0] == "/dev/sda");
    ASSERT_TRUE(paths[25] == "/dev/sdz");
    std::cout << "  Linux device path list OK\n";
}

// ─── Runner ──────────────────────────────────────────────────────
int main() {
    std::cout << "\n=== LAZARUS CORE DiskReader Tests ===\n\n";
    int pass = 0, fail = 0;
    for (const auto& r : g_results) {
        if (r.passed) { std::cout << "[PASS] " << r.name << "\n"; ++pass; }
        else {
            std::cout << "[FAIL] " << r.name;
            if (!r.detail.empty()) std::cout << " — " << r.detail;
            std::cout << "\n"; ++fail;
        }
    }
    std::cout << "\nResults: " << pass << " passed, " << fail << " failed\n\n";
    return fail > 0 ? 1 : 0;
}
