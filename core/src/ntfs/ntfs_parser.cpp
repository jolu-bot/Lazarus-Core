#include "../../include/ntfs_parser.h"
#include <cstring>
#include <algorithm>
#include <codecvt>
#include <locale>
#include <fstream>
#include <filesystem>
#include <stdexcept>

namespace lazarus {

static constexpr uint32_t ATTR_STANDARD_INFO = 0x10;
static constexpr uint32_t ATTR_FILE_NAME     = 0x30;
static constexpr uint32_t ATTR_DATA          = 0x80;
static constexpr uint32_t ATTR_END           = 0xFFFFFFFF;
static constexpr uint32_t MFT_RECORD_SIZE    = 1024;
static constexpr char     MFT_MAGIC[4]       = {'F','I','L','E'};
static const std::string  MFT_SIGNATURE      = "FILE";

NTFSParser::NTFSParser(DiskReader* reader) : m_reader(reader) {}

bool NTFSParser::parse_boot_sector() {
    uint8_t buf[512];
    if (!m_reader->read_bytes(0, 512, buf)) return false;
    std::memcpy(&m_boot, buf, sizeof(m_boot));

    // Validate NTFS signature
    if (std::memcmp(m_boot.oem_id, "NTFS    ", 8) != 0) return false;

    uint32_t bps = m_boot.bytes_per_sector;
    uint32_t spc = m_boot.sectors_per_cluster;
    if (bps == 0 || spc == 0) return false;

    m_cluster_size = static_cast<uint64_t>(bps) * spc;

    // MFT offset in bytes
    m_mft_offset = m_boot.mft_lcn * m_cluster_size;

    // clusters_per_mft can be negative (power of 2 encoding)
    int8_t cpm = m_boot.clusters_per_mft;
    uint32_t record_size = (cpm > 0)
        ? static_cast<uint32_t>(cpm) * m_cluster_size
        : (1u << static_cast<uint8_t>(-cpm));

    if (record_size == 0) record_size = MFT_RECORD_SIZE;

    m_valid = true;
    return true;
}

bool NTFSParser::is_valid() const { return m_valid; }

void NTFSParser::apply_fixup(uint8_t* record, uint32_t size,
                              uint16_t seq_offset, uint16_t seq_count) {
    if (seq_offset + seq_count * 2 > size) return;
    uint16_t* usa = reinterpret_cast<uint16_t*>(record + seq_offset);
    uint16_t  check = usa[0];
    for (uint16_t i = 1; i < seq_count; ++i) {
        uint8_t* sector_end = record + i * 512 - 2;
        uint16_t val;
        std::memcpy(&val, sector_end, 2);
        if (val == check) {
            std::memcpy(sector_end, &usa[i], 2);
        }
    }
}

void NTFSParser::scan_mft(const FileFoundCallback& on_file,
                           const ProgressCallback&  on_progress) {
    if (!m_valid) return;

    // Read first MFT record ($MFT itself) to get total MFT size
    std::vector<uint8_t> buf(MFT_RECORD_SIZE);
    if (!m_reader->read_bytes(m_mft_offset, MFT_RECORD_SIZE, buf.data()))
        return;

    apply_fixup(buf.data(), MFT_RECORD_SIZE,
                reinterpret_cast<MFTFileRecord*>(buf.data())->update_seq_offset,
                reinterpret_cast<MFTFileRecord*>(buf.data())->update_seq_count);

    // Parse $MFT data attribute to get full MFT runs
    auto* rec = reinterpret_cast<MFTFileRecord*>(buf.data());
    uint64_t mft_total_size = 0;
    std::vector<ClusterRun> mft_runs;

    const uint8_t* attr = buf.data() + rec->first_attr_offset;
    const uint8_t* end  = buf.data() + MFT_RECORD_SIZE;

    while (attr + sizeof(AttrHeader) <= end) {
        const auto* hdr = reinterpret_cast<const AttrHeader*>(attr);
        if (hdr->type == ATTR_END || hdr->length == 0) break;
        if (hdr->type == ATTR_DATA && hdr->non_resident) {
            const auto* nr = reinterpret_cast<const NonResidentAttr*>(
                attr + sizeof(AttrHeader));
            mft_total_size = nr->data_size;
            const uint8_t* runs = attr + sizeof(AttrHeader) +
                                  sizeof(NonResidentAttr);
            // account for name
            if (hdr->name_length > 0)
                runs = attr + hdr->name_offset + hdr->name_length * 2;
            runs = attr + nr->data_run_offset;
            mft_runs = parse_data_runs(runs, (end - runs));
            break;
        }
        attr += hdr->length;
    }

    uint64_t total_records = mft_runs.empty()
        ? (mft_total_size / MFT_RECORD_SIZE)
        : (mft_total_size / MFT_RECORD_SIZE);
    if (total_records == 0) total_records = 1000000; // fallback

    uint64_t record_no = 0;
    uint64_t files_found = 0;

    auto read_and_process = [&](uint64_t offset_bytes, uint64_t count) {
        std::vector<uint8_t> chunk(MFT_RECORD_SIZE * 64); // 64 records at a time
        for (uint64_t i = 0; i < count; i += 64) {
            uint64_t batch = std::min<uint64_t>(64, count - i);
            uint64_t off   = offset_bytes + i * MFT_RECORD_SIZE;
            uint32_t bytes = static_cast<uint32_t>(batch * MFT_RECORD_SIZE);
            if (!m_reader->read_bytes(off, bytes, chunk.data())) continue;

            for (uint64_t j = 0; j < batch; ++j) {
                uint8_t* raw = chunk.data() + j * MFT_RECORD_SIZE;
                if (std::memcmp(raw, MFT_SIGNATURE.c_str(), 4) != 0) {
                    ++record_no;
                    continue;
                }
                apply_fixup(raw, MFT_RECORD_SIZE,
                    reinterpret_cast<MFTFileRecord*>(raw)->update_seq_offset,
                    reinterpret_cast<MFTFileRecord*>(raw)->update_seq_count);
                RecoveredFile rf;
                if (parse_mft_record(raw, MFT_RECORD_SIZE, record_no, rf)) {
                    on_file(rf);
                    ++files_found;
                }
                ++record_no;
            }

            ScanProgress prog;
            prog.sectors_total    = total_records;
            prog.sectors_scanned  = record_no;
            prog.files_found      = files_found;
            prog.files_recoverable = files_found;
            prog.percent = (total_records > 0)
                ? static_cast<float>(record_no) / total_records * 100.f
                : 0.f;
            prog.finished = false;
            on_progress(prog);
        }
    };

    if (!mft_runs.empty()) {
        for (const auto& run : mft_runs) {
            if (run.lcn < 0) continue; // sparse
            uint64_t off   = static_cast<uint64_t>(run.lcn) * m_cluster_size;
            uint64_t count = (run.length * m_cluster_size) / MFT_RECORD_SIZE;
            read_and_process(off, count);
        }
    } else {
        // Fallback: linear read from MFT offset
        uint64_t count = mft_total_size / MFT_RECORD_SIZE;
        read_and_process(m_mft_offset, count);
    }

    ScanProgress done;
    done.sectors_total    = total_records;
    done.sectors_scanned  = record_no;
    done.files_found      = files_found;
    done.files_recoverable = files_found;
    done.percent = 100.f;
    done.finished = true;
    on_progress(done);
}

bool NTFSParser::parse_mft_record(const uint8_t* buf, uint32_t /*size*/,
                                   uint64_t record_no, RecoveredFile& out) {
    const auto* rec = reinterpret_cast<const MFTFileRecord*>(buf);
    bool in_use  = (rec->flags & 0x01) != 0;
    bool is_dir  = (rec->flags & 0x02) != 0;
    if (is_dir) return false;

    out.mft_ref    = record_no;
    out.status     = in_use ? FileStatus::ACTIVE : FileStatus::DELETED;
    out.recoverable = true;
    out.confidence  = in_use ? 0.95f : 0.70f;
    out.fs         = FileSystem::NTFS;

    const uint8_t* attr = buf + rec->first_attr_offset;
    const uint8_t* end  = buf + MFT_RECORD_SIZE;

    std::string best_name;
    bool has_data = false;

    while (attr + sizeof(AttrHeader) <= end) {
        const auto* hdr = reinterpret_cast<const AttrHeader*>(attr);
        if (hdr->type == ATTR_END || hdr->length == 0) break;
        if (hdr->length > static_cast<uint32_t>(end - attr)) break;

        if (hdr->type == ATTR_FILE_NAME && !hdr->non_resident) {
            const uint8_t* content = attr + sizeof(AttrHeader);
            if (hdr->name_length == 0) {
                const auto* fn = reinterpret_cast<const FileNameAttr*>(content);
                uint8_t nlen = fn->name_len;
                if (nlen > 0 && nlen <= 255) {
                    std::string n = read_utf16_name(fn->name, nlen);
                    // Prefer POSIX names (type=0)
                    if (best_name.empty() || fn->name_type == 1)
                        best_name = n;
                }
            }
        }

        if (hdr->type == ATTR_DATA) {
            has_data = true;
            if (hdr->non_resident) {
                const auto* nr = reinterpret_cast<const NonResidentAttr*>(
                    attr + sizeof(AttrHeader));
                out.size = nr->data_size;
                const uint8_t* runs = attr + nr->data_run_offset;
                out.runs = parse_data_runs(runs, end - runs);
            } else {
                // Resident data - tiny file
                out.size = *reinterpret_cast<const uint32_t*>(
                    attr + sizeof(AttrHeader) - 4); // value_length
                // Actually resident attr value length is at offset 16 in attr
                uint32_t val_len = 0;
                std::memcpy(&val_len, attr + 16, 4);
                out.size = val_len;
            }
        }

        attr += hdr->length;
    }

    if (best_name.empty() && !has_data) return false;

    out.name = best_name.empty() ? ("file_" + std::to_string(record_no)) : best_name;

    // Extract extension
    auto pos = out.name.find_last_of('.');
    if (pos != std::string::npos) {
        out.extension = out.name.substr(pos + 1);
        std::transform(out.extension.begin(), out.extension.end(),
                       out.extension.begin(), ::tolower);
    }
    out.type = classify_extension(out.extension);
    out.id   = record_no;

    return true;
}

std::vector<ClusterRun> NTFSParser::parse_data_runs(const uint8_t* runs, size_t max_len) {
    std::vector<ClusterRun> result;
    int64_t current_lcn = 0;

    for (size_t i = 0; i < max_len; ) {
        uint8_t b = runs[i++];
        if (b == 0) break;

        uint8_t len_len    = b & 0x0F;
        uint8_t offset_len = (b >> 4) & 0x0F;

        if (len_len == 0 || i + len_len + offset_len > max_len) break;

        // Read run length
        uint64_t run_len = 0;
        for (uint8_t j = 0; j < len_len; ++j)
            run_len |= static_cast<uint64_t>(runs[i + j]) << (8 * j);
        i += len_len;

        // Read run offset (signed)
        int64_t run_offset = 0;
        if (offset_len > 0) {
            uint64_t raw = 0;
            for (uint8_t j = 0; j < offset_len; ++j)
                raw |= static_cast<uint64_t>(runs[i + j]) << (8 * j);
            i += offset_len;
            // Sign-extend
            if (raw & (1ULL << (8 * offset_len - 1))) {
                raw |= (~0ULL) << (8 * offset_len);
            }
            run_offset = static_cast<int64_t>(raw);
        }

        if (offset_len == 0) {
            // Sparse run
            result.push_back({-1, run_len});
        } else {
            current_lcn += run_offset;
            result.push_back({current_lcn, run_len});
        }
    }
    return result;
}

std::string NTFSParser::read_utf16_name(const uint16_t* src, size_t len) {
    std::string result;
    result.reserve(len);
    for (size_t i = 0; i < len; ++i) {
        uint16_t c = src[i];
        if (c < 0x80) {
            result += static_cast<char>(c);
        } else if (c < 0x800) {
            result += static_cast<char>(0xC0 | (c >> 6));
            result += static_cast<char>(0x80 | (c & 0x3F));
        } else {
            result += static_cast<char>(0xE0 | (c >> 12));
            result += static_cast<char>(0x80 | ((c >> 6) & 0x3F));
            result += static_cast<char>(0x80 | (c & 0x3F));
        }
    }
    return result;
}

FileType NTFSParser::classify_extension(const std::string& ext) {
    static const std::unordered_map<std::string, FileType> map = {
        {"jpg",FileType::IMAGE},{"jpeg",FileType::IMAGE},{"png",FileType::IMAGE},
        {"gif",FileType::IMAGE},{"bmp",FileType::IMAGE},{"tiff",FileType::IMAGE},
        {"tif",FileType::IMAGE},{"webp",FileType::IMAGE},{"heic",FileType::IMAGE},
        {"raw",FileType::IMAGE},{"cr2",FileType::IMAGE},{"nef",FileType::IMAGE},
        {"mp4",FileType::VIDEO},{"avi",FileType::VIDEO},{"mov",FileType::VIDEO},
        {"mkv",FileType::VIDEO},{"wmv",FileType::VIDEO},{"flv",FileType::VIDEO},
        {"webm",FileType::VIDEO},{"m4v",FileType::VIDEO},{"3gp",FileType::VIDEO},
        {"mp3",FileType::AUDIO},{"wav",FileType::AUDIO},{"flac",FileType::AUDIO},
        {"aac",FileType::AUDIO},{"ogg",FileType::AUDIO},{"wma",FileType::AUDIO},
        {"m4a",FileType::AUDIO},{"aiff",FileType::AUDIO},
        {"pdf",FileType::DOCUMENT},{"doc",FileType::DOCUMENT},{"docx",FileType::DOCUMENT},
        {"xls",FileType::DOCUMENT},{"xlsx",FileType::DOCUMENT},{"ppt",FileType::DOCUMENT},
        {"pptx",FileType::DOCUMENT},{"txt",FileType::DOCUMENT},{"rtf",FileType::DOCUMENT},
        {"zip",FileType::ARCHIVE},{"rar",FileType::ARCHIVE},{"7z",FileType::ARCHIVE},
        {"tar",FileType::ARCHIVE},{"gz",FileType::ARCHIVE},{"bz2",FileType::ARCHIVE},
    };
    auto it = map.find(ext);
    return (it != map.end()) ? it->second : FileType::UNKNOWN;
}

bool NTFSParser::extract_file(const RecoveredFile& file, const std::string& output_path) {
    if (file.runs.empty()) return false;
    std::ofstream out(output_path, std::ios::binary | std::ios::trunc);
    if (!out) return false;

    uint64_t remaining = file.size;
    std::vector<uint8_t> buf(m_cluster_size);

    for (const auto& run : file.runs) {
        if (run.lcn < 0) {
            // Sparse: write zeros
            uint64_t sparse_bytes = run.length * m_cluster_size;
            uint64_t to_write = std::min(sparse_bytes, remaining);
            std::vector<uint8_t> zeros(std::min<uint64_t>(to_write, 65536), 0);
            while (to_write > 0) {
                uint64_t chunk = std::min<uint64_t>(to_write, zeros.size());
                out.write(reinterpret_cast<const char*>(zeros.data()), chunk);
                to_write  -= chunk;
                remaining -= chunk;
            }
            continue;
        }
        for (uint64_t c = 0; c < run.length && remaining > 0; ++c) {
            uint64_t offset = static_cast<uint64_t>(run.lcn + c) * m_cluster_size;
            uint32_t to_read = static_cast<uint32_t>(
                std::min<uint64_t>(m_cluster_size, remaining));
            if (!m_reader->read_bytes(offset, to_read, buf.data())) break;
            out.write(reinterpret_cast<const char*>(buf.data()), to_read);
            remaining -= to_read;
        }
    }
    return true;
}

} // namespace lazarus
