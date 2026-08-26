# SPDX-License-Identifier: GPL-3.0-only

find_path(UNICORN_INCLUDE_DIR
    NAMES unicorn/unicorn.h
    PATH_SUFFIXES include)

find_library(UNICORN_LIBRARY
    NAMES unicorn unicorn2)

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(Unicorn
    REQUIRED_VARS UNICORN_INCLUDE_DIR UNICORN_LIBRARY)

if(Unicorn_FOUND AND NOT TARGET Unicorn::Unicorn)
    add_library(Unicorn::Unicorn UNKNOWN IMPORTED)
    set_target_properties(Unicorn::Unicorn PROPERTIES
        IMPORTED_LOCATION "${UNICORN_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${UNICORN_INCLUDE_DIR}")
endif()
