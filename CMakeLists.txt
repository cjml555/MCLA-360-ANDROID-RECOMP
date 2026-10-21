# mcla - ReXGlue Recompiled Project
#
# SDK boilerplate lives in generated/rexglue.cmake.

cmake_minimum_required(VERSION 3.25)
project(mcla LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# On PC the test backend is Direct3D 12; on Android it is Vulkan.
if(ANDROID)
    set(REXGLUE_USE_D3D12 OFF CACHE BOOL "Android uses Vulkan" FORCE)
    set(REXGLUE_USE_VULKAN ON CACHE BOOL "Android uses Vulkan" FORCE)
else()
    set(REXGLUE_USE_D3D12 ON CACHE BOOL "PC test backend" FORCE)
    set(REXGLUE_USE_VULKAN OFF CACHE BOOL "PC test backend" FORCE)
endif()
set(REXGLUE_ENABLE_TRACY OFF CACHE BOOL "No profiler dependency" FORCE)
set(REXGLUE_ENABLE_FIDELITYFX OFF CACHE BOOL "Not needed yet" FORCE)
set(REXGLUE_BUILD_TESTS OFF CACHE BOOL "Build the game target only" FORCE)
set(REXGLUE_VERSION_OVERRIDE "0.10.0-dev.android" CACHE STRING "Shared local SDK")
set(REXGLUE_RECOMP_DEBUG_INFO "none" CACHE STRING "Keep the build small")

include(generated/rexglue.cmake)

# The SDK normally writes its binaries back into its own source checkout
# (sdk/out/<preset>/), which the game executable cannot reach. On Linux the SDK
# deliberately has no POST_BUILD staging (only Windows/macOS do) because its
# INSTALL_RPATH is $ORIGIN: it expects librexruntime.so to land NEXT TO the
# executable. So stage into CMAKE_BINARY_DIR itself, not a subdirectory.
function(mcla_stage_sdk_outputs directory)
    get_property(local_targets DIRECTORY "${directory}" PROPERTY BUILDSYSTEM_TARGETS)
    foreach(local_target IN LISTS local_targets)
        get_target_property(local_type ${local_target} TYPE)
        if(NOT local_type STREQUAL "INTERFACE_LIBRARY" AND NOT local_type STREQUAL "UTILITY")
            set_target_properties(${local_target} PROPERTIES
                RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
                LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
                ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/sdk-archives")
        endif()
    endforeach()
    get_property(child_directories DIRECTORY "${directory}" PROPERTY SUBDIRECTORIES)
    foreach(child_directory IN LISTS child_directories)
        mcla_stage_sdk_outputs("${child_directory}")
    endforeach()
endfunction()
if(REXSDK_DIR AND NOT ANDROID)
    mcla_stage_sdk_outputs("${REXSDK_DIR}")
endif()

# Sources
set(MCLA_SOURCES
    src/main.cpp
)

# Android: the game is libmain.so, which SDL3's activity loads and starts
# through SDL_main. The project may add its own sources to the target.
if(ANDROID)
    add_library(mcla SHARED ${MCLA_SOURCES})
    set_target_properties(mcla PROPERTIES OUTPUT_NAME main)
elseif(WIN32)
    add_executable(mcla WIN32 ${MCLA_SOURCES})
else()
    add_executable(mcla ${MCLA_SOURCES})
endif()

rexglue_setup_target(mcla GPU_PLUGINS xenos)

# rexruntime links imgui PRIVATE, so its include path never reaches the title
# even though rex_app.h -> rex/ui/imgui_dialog.h -> imgui.h needs it. Link the
# UI dependencies directly. (rexglue_switch.cmake does the same for Switch.)
foreach(ui_dependency imgui renderdoc)
    if(TARGET ${ui_dependency})
        target_link_libraries(mcla PRIVATE ${ui_dependency})
    endif()
endforeach()

if(ANDROID)
    # The SDK's own SDL entry point selects the app name of the shared
    # nfsmw project. Keep the SDK untouched and select "mcla" here.
    get_target_property(mcla_app_sources mcla SOURCES)
    list(FILTER mcla_app_sources EXCLUDE REGEX "(^|/)windowed_app_main_sdl\\.cpp$")
    set_property(TARGET mcla PROPERTY SOURCES "${mcla_app_sources}")
    target_sources(mcla PRIVATE android/app/src/main/cpp/mcla_entry.cpp)
endif()
