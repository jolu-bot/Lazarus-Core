#include <napi.h>
#include <memory>
#include <thread>
#include "../include/scan_engine.h"
#include "../include/disk_reader.h"
#include "../include/file_rebuilder.h"

using namespace lazarus;

// ─── TSFN helpers ────────────────────────────────────────────────
using TSFN_File     = Napi::TypedThreadSafeFunction<std::nullptr_t, RecoveredFile, 
                        [](Napi::Env env, Napi::Function fn, std::nullptr_t*, RecoveredFile* data) {
                            Napi::Object obj = Napi::Object::New(env);
                            obj.Set("id",         Napi::Number::New(env, (double)data->id));
                            obj.Set("name",       Napi::String::New(env, data->name));
                            obj.Set("extension",  Napi::String::New(env, data->extension));
                            obj.Set("size",       Napi::Number::New(env, (double)data->size));
                            obj.Set("status",     Napi::Number::New(env, (int)data->status));
                            obj.Set("type",       Napi::Number::New(env, (int)data->type));
                            obj.Set("confidence", Napi::Number::New(env, data->confidence));
                            obj.Set("path",       Napi::String::New(env, data->path));
                            obj.Set("recoverable",Napi::Boolean::New(env, data->recoverable));
                            fn.Call({obj});
                            delete data;
                        }>;

// ─── EnumerateDrives ─────────────────────────────────────────────
Napi::Value EnumerateDrives(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();
    auto drives = DiskReader::enumerate_drives();
    Napi::Array arr = Napi::Array::New(env, drives.size());
    for (size_t i = 0; i < drives.size(); ++i) {
        Napi::Object obj = Napi::Object::New(env);
        obj.Set("path",      Napi::String::New(env, drives[i].device_path));
        obj.Set("label",     Napi::String::New(env, drives[i].label));
        obj.Set("totalSize", Napi::Number::New(env, (double)drives[i].total_size));
        obj.Set("sectorSize",Napi::Number::New(env, drives[i].sector_size));
        arr[i] = obj;
    }
    return arr;
}

// ─── StartScan ───────────────────────────────────────────────────
Napi::Value StartScan(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();
    if (info.Length() < 3 || !info[0].IsObject() ||
        !info[1].IsFunction() || !info[2].IsFunction()) {
        Napi::TypeError::New(env, "Expected (options, onFile, onProgress)")
            .ThrowAsJavaScriptException();
        return env.Undefined();
    }

    Napi::Object opts   = info[0].As<Napi::Object>();
    Napi::Function onFile = info[1].As<Napi::Function>();
    Napi::Function onProg = info[2].As<Napi::Function>();

    ScanOptions sopts;
    sopts.device_path    = opts.Get("devicePath").As<Napi::String>();
    sopts.output_dir     = opts.Get("outputDir").As<Napi::String>();
    sopts.scan_ntfs      = opts.Has("scanNTFS")    ? opts.Get("scanNTFS").As<Napi::Boolean>()    : true;
    sopts.scan_ext4      = opts.Has("scanEXT4")    ? opts.Get("scanEXT4").As<Napi::Boolean>()    : true;
    sopts.scan_apfs      = opts.Has("scanAPFS")    ? opts.Get("scanAPFS").As<Napi::Boolean>()    : true;
    sopts.enable_carving = opts.Has("enableCarving")? opts.Get("enableCarving").As<Napi::Boolean>(): true;
    sopts.deep_scan      = opts.Has("deepScan")    ? opts.Get("deepScan").As<Napi::Boolean>()    : false;
    sopts.thread_count   = opts.Has("threads")     ? (size_t)opts.Get("threads").As<Napi::Number>().Int32Value(): 0;

    // Thread-safe callbacks
    auto tsfn_file = Napi::ThreadSafeFunction::New(env, onFile, "onFile", 0, 1);
    auto tsfn_prog = Napi::ThreadSafeFunction::New(env, onProg, "onProg", 0, 1);

    auto* engine = new ScanEngine(
        sopts,
        [tsfn_file](const RecoveredFile& f) mutable {
            auto* copy = new RecoveredFile(f);
            tsfn_file.NonBlockingCall(copy, [](Napi::Env env, Napi::Function fn, RecoveredFile* data) {
                Napi::Object obj = Napi::Object::New(env);
                obj.Set("id",         Napi::Number::New(env, (double)data->id));
                obj.Set("name",       Napi::String::New(env, data->name));
                obj.Set("extension",  Napi::String::New(env, data->extension));
                obj.Set("size",       Napi::Number::New(env, (double)data->size));
                obj.Set("status",     Napi::Number::New(env, (int)data->status));
                obj.Set("type",       Napi::Number::New(env, (int)data->type));
                obj.Set("confidence", Napi::Number::New(env, data->confidence));
                obj.Set("path",       Napi::String::New(env, data->path));
                obj.Set("recoverable",Napi::Boolean::New(env, data->recoverable));
                fn.Call({obj});
                delete data;
            });
        },
        [tsfn_prog](const ScanProgress& p) mutable {
            auto* copy = new ScanProgress(p);
            tsfn_prog.NonBlockingCall(copy, [](Napi::Env env, Napi::Function fn, ScanProgress* data) {
                Napi::Object obj = Napi::Object::New(env);
                obj.Set("sectorsTotal",    Napi::Number::New(env, (double)data->sectors_total));
                obj.Set("sectorsScanned",  Napi::Number::New(env, (double)data->sectors_scanned));
                obj.Set("filesFound",      Napi::Number::New(env, (double)data->files_found));
                obj.Set("filesRecoverable",Napi::Number::New(env, (double)data->files_recoverable));
                obj.Set("percent",         Napi::Number::New(env, data->percent));
                obj.Set("finished",        Napi::Boolean::New(env, data->finished));
                obj.Set("currentPath",     Napi::String::New(env, data->current_path));
                fn.Call({obj});
                delete data;
            });
        }
    );

    // Run scan in background thread
    std::thread([engine, tsfn_file, tsfn_prog]() mutable {
        engine->start();
        engine->get_results(); // blocks until done via wait_all
        delete engine;
        tsfn_file.Release();
        tsfn_prog.Release();
    }).detach();

    return env.Undefined();
}

// ─── RecoverFile ─────────────────────────────────────────────────
Napi::Value RecoverFile(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();
    if (info.Length() < 3) {
        Napi::TypeError::New(env, "Expected (devicePath, file, outputDir)")
            .ThrowAsJavaScriptException();
        return env.Undefined();
    }

    std::string device_path = info[0].As<Napi::String>();
    Napi::Object file_obj   = info[1].As<Napi::Object>();
    std::string output_dir  = info[2].As<Napi::String>();

    RecoveredFile rf;
    rf.name       = file_obj.Get("name").As<Napi::String>();
    rf.size       = (uint64_t)file_obj.Get("size").As<Napi::Number>().Int64Value();
    rf.mft_ref    = (uint64_t)file_obj.Get("id").As<Napi::Number>().Int64Value();
    rf.recoverable = true;

    DiskReader reader(device_path);
    if (!reader.open()) {
        return Napi::Boolean::New(env, false);
    }

    // For now, assume NTFS-based recovery
    NTFSParser ntfs(&reader);
    bool ok = false;
    if (ntfs.parse_boot_sector()) {
        std::string out_path;
        ok = ntfs.extract_file(rf, output_dir + "/" + rf.name);
    }

    return Napi::Boolean::New(env, ok);
}

// ─── Module Init ─────────────────────────────────────────────────
Napi::Object Init(Napi::Env env, Napi::Object exports) {
    exports.Set("enumerateDrives", Napi::Function::New(env, EnumerateDrives));
    exports.Set("startScan",       Napi::Function::New(env, StartScan));
    exports.Set("recoverFile",     Napi::Function::New(env, RecoverFile));
    return exports;
}

NODE_API_MODULE(lazarus_core, Init)
