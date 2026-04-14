cmake_minimum_required(VERSION 3.16)
project(lazarus_core VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ─── Performance flags ───────────────────────────────────────────
if(MSVC)
    add_compile_options(/O2 /W3 /MP /GL)
    add_definitions(-D_CRT_SECURE_NO_WARNINGS -DNOMINMAX)
    set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} /LTCG")
else()
    add_compile_options(-O3 -Wall -Wextra -march=native -ffast-math)
    if(CMAKE_CXX_COMPILER_ID MATCHES "GNU")
        add_compile_options(-fno-strict-aliasing)
    endif()
endif()

# ─── Sources ─────────────────────────────────────────────────────
set(LAZARUS_SOURCES
    src/disk/disk_reader.cpp
    src/ntfs/ntfs_parser.cpp
    src/ext4/ext4_parser.cpp
    src/apfs/apfs_parser.cpp
    src/carver/file_carver.cpp
    src/rebuilder/file_rebuilder.cpp
    src/scan_engine.cpp
)

# ─── Static library ──────────────────────────────────────────────
add_library(lazarus_engine STATIC ${LAZARUS_SOURCES})
target_include_directories(lazarus_engine PUBLIC include)

if(WIN32)
    target_link_libraries(lazarus_engine PRIVATE setupapi)
endif()

if(UNIX AND NOT APPLE)
    target_link_libraries(lazarus_engine PRIVATE pthread)
endif()

# ─── Node.js addon (via node-gyp/cmake-js) ───────────────────────
if(DEFINED ENV{npm_config_cmake})
    find_package(unofficial-node-addon-api CONFIG QUIET)
    if(unofficial-node-addon-api_FOUND)
        add_library(lazarus_addon SHARED src/binding.cpp)
        target_link_libraries(lazarus_addon PRIVATE
            lazarus_engine
            unofficial::node-addon-api::node-addon-api)
        set_target_properties(lazarus_addon PROPERTIES
            PREFIX "" SUFFIX ".node"
            OUTPUT_NAME "lazarus_core"
        )
    endif()
endif()

# ─── Tests ───────────────────────────────────────────────────────
option(BUILD_TESTS "Build unit tests" OFF)
if(BUILD_TESTS)
    enable_testing()

    foreach(test_name ntfs carver disk)
        add_executable(test_${test_name} tests/test_${test_name}.cpp)
        target_include_directories(test_${test_name} PRIVATE include)
        target_compile_features(test_${test_name} PRIVATE cxx_std_17)
        add_test(NAME test_${test_name} COMMAND test_${test_name})
    endforeach()
endif()
