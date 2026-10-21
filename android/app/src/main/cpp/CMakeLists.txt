cmake_minimum_required(VERSION 3.25)
project(mcla_android LANGUAGES C CXX)

# The game project is five levels up from android/app/src/main/cpp
# (cpp -> main -> src -> app -> android -> project root): it holds the
# ReXGlue manifest, the generated code and the app hooks. The SDK is a
# sibling of it.
get_filename_component(MCLA_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../../.." ABSOLUTE)
if(NOT REXSDK_DIR)
    get_filename_component(REXSDK_DIR "${MCLA_ROOT}/../nfsmw-android/sdk" ABSOLUTE)
endif()
set(REXSDK_DIR "${REXSDK_DIR}" CACHE PATH "ReXGlue SDK sources" FORCE)

# SDL ships its own Android project (SDLActivity) and the port loads it as a
# shared library, so the Java side can subclass it.
set(SDL_SHARED ON CACHE BOOL "SDLActivity loads libSDL3.so" FORCE)
set(SDL_STATIC OFF CACHE BOOL "Use shared SDL" FORCE)

# The game project: its CMakeLists includes generated/rexglue.cmake, which
# pulls the SDK in and defines the `mcla` executable target.
add_subdirectory("${MCLA_ROOT}" "mcla-app")

target_link_options(mcla PRIVATE "-Wl,-z,max-page-size=16384")

# The Xenos GPU emulation lives in the SDK as a plugin; the game loads it by
# name (config.gpu_plugin = "xenos" in src/mcla_app.h).
target_link_libraries(mcla PRIVATE rexgpu-xenos)

# The Android entry point: ReXGlue's SDL main(), adapted to register the
# "mcla" app creator.
target_sources(mcla PRIVATE mcla_entry.cpp)

# The FPS counters the launcher's readout and the per-frame CSV read.
target_sources(mcla PRIVATE mcla_performance.cpp)

# The on-screen gamepad's bridge: the Java overlay hands the pad's state here
# and the SDK publishes it as the synthetic touch controller.
target_sources(mcla PRIVATE android_touchpad.cpp)

# The SDK compiles the perf counters in every build except Release. The
# Android APK is Release, and the counters are what the launcher's FPS
# readout and the per-frame CSV need, so turn them on here too: they are a
# few atomics per frame.
# (The SDK patch does the same for the runtime; this target is the game
# project, which the SDK does not touch.)
target_compile_definitions(mcla PRIVATE REXGLUE_ENABLE_PERF_COUNTERS)

if(TARGET SDL3-shared)
    set_target_properties(SDL3-shared PROPERTIES OUTPUT_NAME SDL3 DEBUG_POSTFIX ""
        RELEASE_POSTFIX "" RELWITHDEBINFO_POSTFIX "" MINSIZEREL_POSTFIX "")
endif()

# 16 GB of RAM on the development machine: cap the concurrency so a parallel
# link of the recompiled game does not exhaust it.
set_property(GLOBAL PROPERTY JOB_POOLS mcla_compile=4 mcla_link=1)
set(CMAKE_JOB_POOL_COMPILE mcla_compile CACHE STRING "Compile concurrency" FORCE)
foreach(mcla_target mcla mcla_recomp rexruntime rexgpu-xenos)
    if(TARGET ${mcla_target})
        set_property(TARGET ${mcla_target} PROPERTY JOB_POOL_COMPILE mcla_compile)
        set_property(TARGET ${mcla_target} PROPERTY JOB_POOL_LINK mcla_link)
    endif()
endforeach()
