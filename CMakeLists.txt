# mcla - ReXGlue Recompiled Project
#
# SDK boilerplate lives in generated/rexglue.cmake.

cmake_minimum_required(VERSION 3.25)
project(mcla LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

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
if(REXSDK_DIR)
    mcla_stage_sdk_outputs("${REXSDK_DIR}")
endif()

# Sources
set(MCLA_SOURCES
    src/main.cpp
)

if(WIN32)
    add_executable(mcla WIN32 ${MCLA_SOURCES})
else()
    add_executable(mcla ${MCLA_SOURCES})
endif()

rexglue_setup_target(mcla)

# rexruntime links imgui PRIVATE, so its include path never reaches the title
# even though rex_app.h -> rex/ui/imgui_dialog.h -> imgui.h needs it. Link the
# UI dependencies directly. (rexglue_switch.cmake does the same for Switch.)
foreach(ui_dependency imgui renderdoc)
    if(TARGET ${ui_dependency})
        target_link_libraries(mcla PRIVATE ${ui_dependency})
    endif()
endforeach()
