#include "../../include/file_carver.h"
#include <cstring>
#include <algorithm>
#include <fstream>
#include <filesystem>
#include <sstream>
#include <iomanip>

namespace lazarus {

FileCarver::FileCarver(DiskReader* reader,
                       const std::string& output_dir,
                       const FileFoundCallback& on_found,
                       const ProgressCallback&  on_progress)
    : m_reader(reader), m_output_dir(output_dir),
      m_on_found(on_found), m_on_progress(on_progress) {}

void FileCarver::add_signature(const CarverSignature& sig) {
    m_signatures.push_back(sig);
}

void FileCarver::load_default_signatures() {
    // JPEG
    add_signature({"JPEG", "jpg", FileType::IMAGE,
        {0xFF, 0xD8, 0xFF}, {0xFF, 0xD9}, 50*1024*1024, true});
    // PNG
    add_signature({"PNG", "png", FileType::IMAGE,
        {0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A},
        {0x49,0x45,0x4E,0x44,0xAE,0x42,0x60,0x82},
        50*1024*1024, true});
    // MP4 / MOV (detect ftyp atom)
    add_signature({"MP4", "mp4", FileType::VIDEO,
        {0x00,0x00,0x00,0x00,'f','t','y','p'}, {}, 4ULL*1024*1024*1024, false});
    // PDF
    add_signature({"PDF", "pdf", FileType::DOCUMENT,
        {0x25,0x50,0x44,0x46,0x2D},          // %PDF-
        {0x25,0x25,0x45,0x4F,0x46},          // %%EOF
        500*1024*1024, true});
    // ZIP / DOCX / XLSX
    add_signature({"ZIP", "zip", FileType::ARCHIVE,
        {0x50,0x4B,0x03,0x04}, {0x50,0x4B,0x05,0x06}, 500*1024*1024, true});
    // MP3
    add_signature({"MP3", "mp3", FileType::AUDIO,
        {0xFF,0xFB}, {}, 50*1024*1024, false});
    add_signature({"MP3_ID3", "mp3", FileType::AUDIO,
        {0x49,0x44,0x33}, {}, 50*1024*1024, false}); // ID3
    // GIF
    add_signature({"GIF", "gif", FileType::IMAGE,
        {0x47,0x49,0x46,0x38}, {0x00,0x3B}, 50*1024*1024, true});
    // BMP
    add_signature({"BMP", "bmp", FileType::IMAGE,
        {0x42,0x4D}, {}, 100*1024*1024, false});
    // AVI
    add_signature({"AVI", "avi", FileType::VIDEO,
        {0x52,0x49,0x46,0x46}, {}, 4ULL*1024*1024*1024, false});
    // WAV
    add_signature({"WAV", "wav", FileType::AUDIO,
        {0x52,0x49,0x46,0x46,0,0,0,0,0x57,0x41,0x56,0x45}, {}, 500*1024*1024, false});
    // DOCX/XLSX header same as ZIP (already covered)
}

bool FileCarver::match_header(const uint8_t* buf, size_t buf_len,
                               const CarverSignature& sig, size_t offset) {
    if (sig.header.empty()) return false;
    if (offset + sig.header.size() > buf_len) return false;

    // Special MP4: ftyp is at offset 4 from box start
    if (sig.type == "MP4") {
        if (offset + 8 > buf_len) return false;
        return std::memcmp(buf + offset + 4, "ftyp", 4) == 0;
    }

    return std::memcmp(buf + offset, sig.header.data(), sig.header.size()) == 0;
}

bool FileCarver::match_footer(const uint8_t* buf, size_t buf_len,
                               const CarverSignature& sig, size_t offset) {
    if (!sig.use_footer || sig.footer.empty()) return false;
    if (offset + sig.footer.size() > buf_len) return false;
    return std::memcmp(buf + offset, sig.footer.data(), sig.footer.size()) == 0;
}

bool FileCarver::save_carved_file(const CarvedFile& cf, const uint8_t* data,
                                   size_t len, uint64_t counter,
                                   std::string& out_path) {
    std::filesystem::create_directories(m_output_dir);
    std::ostringstream ss;
    ss << m_output_dir << "/carved_"
       << std::setw(8) << std::setfill('0') << counter
       << "_" << std::hex << cf.start_offset
       << "." << cf.extension;
    out_path = ss.str();
    std::ofstream f(out_path, std::ios::binary);
    if (!f) return false;
    f.write(reinterpret_cast<const char*>(data), len);
    return true;
}

RecoveredFile FileCarver::make_recovered(const CarvedFile& cf,
                                          const std::string& path,
                                          uint64_t id) {
    RecoveredFile rf;
    rf.id           = id;
    rf.name         = std::filesystem::path(path).filename().string();
    rf.extension    = cf.extension;
    rf.size         = cf.size;
    rf.status       = cf.complete ? FileStatus::ACTIVE : FileStatus::PARTIAL;
    rf.type         = cf.file_type;
    rf.fs           = FileSystem::RAW;
    rf.recoverable  = true;
    rf.confidence   = cf.confidence;
    rf.preview_path = path;
    rf.path         = path;
    return rf;
}

void FileCarver::carve(uint64_t start_sector, uint64_t end_sector) {
    m_stop = false;
    uint64_t total_sectors = m_reader->get_total_sectors();
    if (end_sector == 0 || end_sector > total_sectors)
        end_sector = total_sectors;

    uint32_t sec_size   = m_reader->get_sector_size();
    uint64_t buf_sectors = BUFFER_SIZE / sec_size;
    std::vector<uint8_t> buffer(BUFFER_SIZE + OVERLAP);
    std::vector<uint8_t> overlap_buf(OVERLAP, 0);

    uint64_t file_counter = 0;

    // Active carving state per signature
    struct ActiveCarve {
        size_t   sig_idx;
        uint64_t start_offset;
        uint64_t current_size;
        std::vector<uint8_t> data;
        bool active;
    };
    std::vector<ActiveCarve> active(m_signatures.size());
    for (size_t i = 0; i < m_signatures.size(); ++i)
        active[i] = {i, 0, 0, {}, false};

    uint64_t cur = start_sector;
    while (cur < end_sector && !m_stop) {
        uint64_t batch = std::min<uint64_t>(buf_sectors, end_sector - cur);
        uint32_t bytes = static_cast<uint32_t>(batch * sec_size);

        // Prepend overlap
        std::memcpy(buffer.data(), overlap_buf.data(), OVERLAP);
        if (!m_reader->read_sectors(cur, static_cast<uint32_t>(batch),
                                     buffer.data() + OVERLAP)) {
            cur += batch;
            continue;
        }

        size_t total_buf = OVERLAP + bytes;
        uint64_t base_offset = (cur * sec_size) - OVERLAP;

        for (size_t pos = 0; pos < total_buf; ++pos) {
            for (size_t si = 0; si < m_signatures.size(); ++si) {
                const auto& sig = m_signatures[si];
                auto& ac = active[si];

                // Check for header match (start new carve)
                if (!ac.active && match_header(buffer.data(), total_buf, sig, pos)) {
                    ac.active       = true;
                    ac.start_offset = base_offset + pos;
                    ac.current_size = 0;
                    ac.data.clear();
                    ac.data.reserve(std::min<uint64_t>(sig.max_size > 0
                        ? sig.max_size : 10*1024*1024, 50*1024*1024));
                }

                if (ac.active) {
                    ac.data.push_back(buffer[pos]);
                    ++ac.current_size;

                    // Check footer
                    bool end_found = false;
                    if (sig.use_footer && !sig.footer.empty()) {
                        if (ac.current_size >= sig.footer.size()) {
                            size_t check_pos = pos - sig.footer.size() + 1;
                            if (pos >= sig.footer.size() - 1 &&
                                match_footer(buffer.data(), total_buf,
                                             sig, pos - sig.footer.size() + 1)) {
                                end_found = true;
                            }
                        }
                    }

                    // Max size check
                    if (sig.max_size > 0 && ac.current_size >= sig.max_size)
                        end_found = true;

                    if (end_found) {
                        CarvedFile cf;
                        cf.start_offset = ac.start_offset;
                        cf.end_offset   = base_offset + pos;
                        cf.size         = ac.current_size;
                        cf.extension    = sig.extension;
                        cf.file_type    = sig.file_type;
                        cf.complete     = sig.use_footer && !sig.footer.empty();
                        cf.confidence   = cf.complete ? 0.90f : 0.60f;

                        std::string out_path;
                        if (save_carved_file(cf, ac.data.data(), ac.data.size(),
                                             file_counter, out_path)) {
                            RecoveredFile rf = make_recovered(cf, out_path, file_counter);
                            m_on_found(rf);
                            ++file_counter;
                        }
                        ac.active = false;
                        ac.data.clear();
                    }
                }
            }
        }

        // Save overlap
        if (total_buf >= OVERLAP)
            std::memcpy(overlap_buf.data(), buffer.data() + total_buf - OVERLAP, OVERLAP);

        cur += batch;

        ScanProgress prog;
        prog.sectors_total   = end_sector - start_sector;
        prog.sectors_scanned = cur - start_sector;
        prog.files_found     = file_counter;
        prog.files_recoverable = file_counter;
        prog.percent = static_cast<float>(cur - start_sector) /
                       (end_sector - start_sector) * 100.f;
        prog.finished = false;
        m_on_progress(prog);
    }

    ScanProgress done;
    done.sectors_total    = end_sector - start_sector;
    done.sectors_scanned  = end_sector - start_sector;
    done.files_found      = file_counter;
    done.files_recoverable = file_counter;
    done.percent  = 100.f;
    done.finished = true;
    m_on_progress(done);
}

void FileCarver::stop() { m_stop = true; }

} // namespace lazarus
