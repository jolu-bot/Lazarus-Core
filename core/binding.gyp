{
  "targets": [{
    "target_name": "lazarus_core",
    "cflags!":    [ "-fno-exceptions" ],
    "cflags_cc!": [ "-fno-exceptions" ],
    "sources": [
      "src/binding.cpp",
      "src/disk/disk_reader.cpp",
      "src/ntfs/ntfs_parser.cpp",
      "src/ext4/ext4_parser.cpp",
      "src/apfs/apfs_parser.cpp",
      "src/carver/file_carver.cpp",
      "src/rebuilder/file_rebuilder.cpp",
      "src/scan_engine.cpp"
    ],
    "include_dirs": [
      "include",
      "<!@(node -p \"require('node-addon-api').include\")"
    ],
    "defines": [ "NAPI_DISABLE_CPP_EXCEPTIONS" ],
    "conditions": [
      ["OS=='win'", {
        "msvs_settings": {
          "VCCLCompilerTool": {
            "ExceptionHandling": 1,
            "Optimization": 2,
            "AdditionalOptions": [ "/std:c++17" ]
          }
        },
        "libraries": [ "-lsetupapi" ]
      }],
      ["OS=='mac'", {
        "xcode_settings": {
          "GCC_ENABLE_CPP_EXCEPTIONS": "YES",
          "CLANG_CXX_LANGUAGE_STANDARD": "c++17",
          "MACOSX_DEPLOYMENT_TARGET": "10.15"
        }
      }],
      ["OS=='linux'", {
        "cflags_cc": [ "-std=c++17" ]
      }]
    ]
  }]
}
