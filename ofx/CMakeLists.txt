# Kerf FX OpenFX plugin. cmake -B build -DOFX_INCLUDE=<openfx>/include && cmake --build build --config Release
cmake_minimum_required(VERSION 3.16)
# universal macOS binary; must be set before project()
set(CMAKE_OSX_ARCHITECTURES "arm64;x86_64" CACHE STRING "")
set(CMAKE_OSX_DEPLOYMENT_TARGET "11.0" CACHE STRING "")
project(KerfFX CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded")  # static CRT: no Visual C++ redistributable needed

# HarfBuzz's single-file build (text shaping, needed for Indian scripts); stb_truetype is header-only
add_library(KerfFX MODULE kerf_fx.cpp captions.cpp ${HB_DIR}/src/harfbuzz.cc)
target_include_directories(KerfFX PRIVATE ${OFX_INCLUDE} ${HB_DIR}/src ${STB_DIR})
if(MSVC)
  target_compile_options(KerfFX PRIVATE /utf-8 /bigobj)
  target_link_libraries(KerfFX PRIVATE ws2_32)  # the Transcribe button talks to the local engine
endif()
set_target_properties(KerfFX PROPERTIES PREFIX "" SUFFIX ".ofx" CXX_VISIBILITY_PRESET hidden)
find_package(Threads REQUIRED)
target_link_libraries(KerfFX PRIVATE Threads::Threads)
if(NOT MSVC)
  target_compile_options(KerfFX PRIVATE -O3 -Wall)
endif()
