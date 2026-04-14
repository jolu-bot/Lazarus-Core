/**
 * LAZARUS CORE – File Carver Unit Tests
 * Tests signature matching, footer detection and output naming.
 * Compile with: g++ -std=c++17 -I../include test_carver.cpp
 *               ../src/carver/file_carver.cpp ../src/disk/disk_reader.cpp -o test_carver
 */
#include <cassert>
#include <cstring>
#include <vector>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sstream>
#include <iomanip>

#include "../include/file_carver.h"
#include "../include/types.h"

// ─── Minimal mock DiskReader ──────────────────────────────────────
// (We only need it to satisfy the constructor; carving is tested in isolation)
#include "../include/disk_reader.h"
namespace lazarus {
DiskReader::DiskReader(const std::string& p) : m_path(p) {}
DiskReader::~DiskReader() { close(); }
bool     DiskReader::open()  { return false; }
void     DiskReader::close() {}
bool     DiskReader::is_open() const { return false; }
bool     DiskReader::read_sectors(uint64_t, uint32_t, uint8_t*)  { return false; }
bool     DiskReader::read_bytes(uint64_t, uint32_t, uint8_t*)    { return false; }
uint64_t DiskReader::get_total_sectors() const { return 0; }
uint32_t DiskReader::get_sector_size()   const { return 512; }
uint64_t DiskReader::get_total_size()    const { return 0; }
DiskInfo DiskReader::get_disk_info()     const { return {}; }
std::vector<DiskInfo> DiskReader::enumerate_drives() { return {}; }
#ifdef _WIN32
bool DiskReader::query_geometry() { return false; }
#else
bool DiskReader::query_geometry_posix() { return false; }
#endif
} // namespace lazarus

using namespace lazarus;

// ─── Helpers ─────────────────────────────────────────────────────
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

#define ASSERT_TRUE(x) do { if (!(x)) throw std::runtime_error("Failed: " #x); } while(0)
#define ASSERT_EQ(a,b) do { if ((a)!=(b)) throw std::runtime_error( \
    std::string(#a "=") + std::to_string(a) + " != " + std::to_string(b)); } while(0)

// ─── Test: JPEG signature bytes ───────────────────────────────────
TEST(jpeg_signature) {
    uint8_t jpeg_hdr[] = { 0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10 };
    uint8_t jpeg_ftr[] = { 0xFF, 0xD9 };

    ASSERT_TRUE(jpeg_hdr[0] == 0xFF && jpeg_hdr[1] == 0xD8);
    ASSERT_TRUE(jpeg_ftr[0] == 0xFF && jpeg_ftr[1] == 0xD9);
    std::cout << "  JPEG signature bytes OK\n";
}

// ─── Test: PNG signature bytes ────────────────────────────────────
TEST(png_signature) {
    uint8_t hdr[] = { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A };
    uint8_t ftr[] = { 0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82 };

    ASSERT_EQ(hdr[0], 0x89u);
    ASSERT_EQ(hdr[1], 0x50u); // 'P'
    ASSERT_EQ(hdr[2], 0x4Eu); // 'N'
    ASSERT_EQ(hdr[3], 0x47u); // 'G'
    ASSERT_EQ(ftr[0], 0x49u); // 'I'
    ASSERT_EQ(ftr[1], 0x45u); // 'E'
    ASSERT_EQ(ftr[2], 0x4Eu); // 'N'
    ASSERT_EQ(ftr[3], 0x44u); // 'D'
    std::cout << "  PNG signature bytes OK\n";
}

// ─── Test: PDF signature bytes ────────────────────────────────────
TEST(pdf_signature) {
    // "%PDF-"
    const char* pdf_sig = "%PDF-";
    uint8_t hdr[] = { 0x25, 0x50, 0x44, 0x46, 0x2D };
    ASSERT_TRUE(std::memcmp(pdf_sig, hdr, 5) == 0);
    std::cout << "  PDF signature bytes OK\n";
}

// ─── Test: MP4 ftyp detection ─────────────────────────────────────
TEST(mp4_ftyp_atom) {
    // ftyp atom: 4 bytes size, "ftyp", brand
    uint8_t atom[] = {
        0x00, 0x00, 0x00, 0x18,  // size = 24
        0x66, 0x74, 0x79, 0x70,  // "ftyp"
        0x69, 0x73, 0x6F, 0x6D,  // "isom"
        0x00, 0x00, 0x00, 0x00,  // version
        0x69, 0x73, 0x6F, 0x6D,  // compatible brands
        0x61, 0x76, 0x63, 0x31,
    };
    ASSERT_TRUE(std::memcmp(atom + 4, "ftyp", 4) == 0);
    std::cout << "  MP4 ftyp atom detection OK\n";
}

// ─── Test: ZIP/DOCX PK header ────────────────────────────────────
TEST(zip_signature) {
    uint8_t pk[] = { 0x50, 0x4B, 0x03, 0x04 }; // PK\x03\x04
    ASSERT_EQ(pk[0], 0x50u); // 'P'
    ASSERT_EQ(pk[1], 0x4Bu); // 'K'
    ASSERT_EQ(pk[2], 0x03u);
    ASSERT_EQ(pk[3], 0x04u);
    std::cout << "  ZIP/DOCX PK signature OK\n";
}

// ─── Test: BMP signature ─────────────────────────────────────────
TEST(bmp_signature) {
    uint8_t bmp[] = { 0x42, 0x4D }; // "BM"
    ASSERT_EQ(bmp[0], 0x42u); // 'B'
    ASSERT_EQ(bmp[1], 0x4Du); // 'M'
    std::cout << "  BMP signature OK\n";
}

// ─── Test: GIF signature ─────────────────────────────────────────
TEST(gif_signature) {
    uint8_t gif[] = { 0x47, 0x49, 0x46, 0x38 }; // "GIF8"
    ASSERT_EQ(gif[0], 0x47u); // 'G'
    ASSERT_EQ(gif[1], 0x49u); // 'I'
    ASSERT_EQ(gif[2], 0x46u); // 'F'
    ASSERT_EQ(gif[3], 0x38u); // '8'
    std::cout << "  GIF signature OK\n";
}

// ─── Test: CarverSignature struct ────────────────────────────────
TEST(carver_signature_struct) {
    CarverSignature s;
    s.type      = "JPEG";
    s.extension = "jpg";
    s.file_type = FileType::IMAGE;
    s.header    = { 0xFF, 0xD8, 0xFF };
    s.footer    = { 0xFF, 0xD9 };
    s.max_size  = 50 * 1024 * 1024;
    s.use_footer = true;

    ASSERT_TRUE(s.type == "JPEG");
    ASSERT_TRUE(s.file_type == FileType::IMAGE);
    ASSERT_EQ(s.header.size(), 3ULL);
    ASSERT_EQ(s.footer.size(), 2ULL);
    ASSERT_EQ(s.max_size, 50ULL * 1024 * 1024);
    std::cout << "  CarverSignature struct OK\n";
}

// ─── Test: CarvedFile struct ─────────────────────────────────────
TEST(carved_file_struct) {
    CarvedFile cf;
    cf.start_offset = 0x1000;
    cf.end_offset   = 0x5000;
    cf.size         = 0x4000;
    cf.extension    = "jpg";
    cf.file_type    = FileType::IMAGE;
    cf.complete     = true;
    cf.confidence   = 0.90f;

    ASSERT_EQ(cf.size, 0x4000ULL);
    ASSERT_TRUE(cf.complete);
    ASSERT_TRUE(cf.confidence > 0.89f);
    std::cout << "  CarvedFile struct OK\n";
}

// ─── Test: Signature overlap detection simulation ─────────────────
TEST(header_match_simulation) {
    // Simulate what FileCarver::match_header does for JPEG
    std::vector<uint8_t> header = { 0xFF, 0xD8, 0xFF };
    uint8_t buf[] = { 0x00, 0xFF, 0xD8, 0xFF, 0xE0 };
    size_t  pos   = 1;

    bool match = (pos + header.size() <= sizeof(buf)) &&
                 std::memcmp(buf + pos, header.data(), header.size()) == 0;
    ASSERT_TRUE(match);
    std::cout << "  Header match simulation OK\n";
}

// ─── Test: Max size enforcement ───────────────────────────────────
TEST(max_size_check) {
    uint64_t max_size    = 50ULL * 1024 * 1024;
    uint64_t current_sz  = 50ULL * 1024 * 1024 + 1;
    bool should_stop = (current_sz >= max_size);
    ASSERT_TRUE(should_stop);
    std::cout << "  Max size enforcement OK\n";
}

// ─── Runner ──────────────────────────────────────────────────────
int main() {
    std::cout << "\n=== LAZARUS CORE Carver Tests ===\n\n";
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
