# SPDX-License-Identifier: GPL-3.0-only

cmake_minimum_required(VERSION 3.20)
project(PPCLab VERSION 0.4.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(PPC_LAB_ENABLE_UNICORN "Enable Unicorn PPC32 backend when development files are available" ON)
option(PPC_LAB_ENABLE_SANITIZERS "Build with AddressSanitizer and UBSan" OFF)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
if(PPC_LAB_ENABLE_UNICORN)
    find_package(Unicorn QUIET)
endif()

add_library(ppc_lab STATIC
    src/Memory.cpp
    src/ImportStubs.cpp
    src/Execution.cpp
    src/CallHarness.cpp
    src/Elf32Loader.cpp
    src/MachOLoader.cpp
    src/PefLoader.cpp
    src/BuiltinInterpreter.cpp
    src/UnicornBackend.cpp
    src/Microtests.cpp)

target_include_directories(ppc_lab PUBLIC include)

if(PPC_LAB_ENABLE_SANITIZERS AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(ppc_lab PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(ppc_lab PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
endif()

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(ppc_lab PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(Unicorn_FOUND)
    target_compile_definitions(ppc_lab PRIVATE PPC_LAB_HAVE_UNICORN=1)
    target_link_libraries(ppc_lab PRIVATE Unicorn::Unicorn)
    message(STATUS "PPC Lab: Unicorn backend ENABLED")
else()
    message(STATUS "PPC Lab: Unicorn backend unavailable; builtin backend ENABLED")
endif()

add_executable(ppc_lab_cli tools/ppc_lab.cpp)
target_link_libraries(ppc_lab_cli PRIVATE ppc_lab)
set_target_properties(ppc_lab_cli PROPERTIES OUTPUT_NAME ppc-lab)

add_executable(ppc_lab_tests tests/test_ppc_harness.cpp)
target_link_libraries(ppc_lab_tests PRIVATE ppc_lab)
add_executable(ppc_lab_call_tests tests/test_call_harness.cpp)
target_link_libraries(ppc_lab_call_tests PRIVATE ppc_lab)
add_executable(ppc_lab_elf32_tests tests/test_elf32_loader.cpp)
target_link_libraries(ppc_lab_elf32_tests PRIVATE ppc_lab)
add_executable(ppc_lab_elf32_reloc_tests tests/test_elf32_relocations.cpp)
target_link_libraries(ppc_lab_elf32_reloc_tests PRIVATE ppc_lab)
add_executable(ppc_lab_macho_tests tests/test_macho_loader.cpp)
target_link_libraries(ppc_lab_macho_tests PRIVATE ppc_lab)
add_executable(ppc_lab_pef_tests tests/test_pef_loader.cpp)
target_link_libraries(ppc_lab_pef_tests PRIVATE ppc_lab)
add_executable(ppc_lab_import_stub_tests tests/test_import_stubs.cpp)
target_link_libraries(ppc_lab_import_stub_tests PRIVATE ppc_lab)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(ppc_lab_tests PRIVATE -UNDEBUG)
    target_compile_options(ppc_lab_call_tests PRIVATE -UNDEBUG)
    target_compile_options(ppc_lab_elf32_tests PRIVATE -UNDEBUG)
    target_compile_options(ppc_lab_elf32_reloc_tests PRIVATE -UNDEBUG)
    target_compile_options(ppc_lab_macho_tests PRIVATE -UNDEBUG)
    target_compile_options(ppc_lab_pef_tests PRIVATE -UNDEBUG)
    target_compile_options(ppc_lab_import_stub_tests PRIVATE -UNDEBUG)
endif()

enable_testing()
add_test(NAME ppc_lab_tests COMMAND ppc_lab_tests)
add_test(NAME ppc_lab_call_tests COMMAND ppc_lab_call_tests)
add_test(NAME ppc_lab_elf32_tests COMMAND ppc_lab_elf32_tests)
add_test(NAME ppc_lab_elf32_reloc_tests COMMAND ppc_lab_elf32_reloc_tests)
add_test(NAME ppc_lab_macho_tests COMMAND ppc_lab_macho_tests)
add_test(NAME ppc_lab_pef_tests COMMAND ppc_lab_pef_tests)
add_test(NAME ppc_lab_import_stub_tests COMMAND ppc_lab_import_stub_tests)
add_test(NAME ppc_lab_cli_selftest COMMAND ppc-lab selftest --backend builtin)
find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_Interpreter_FOUND)
    add_test(NAME ppc_lab_result_tools COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_result_tools.py)
    add_test(NAME ppc_lab_cli_elf COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_cli_elf.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_cli_binary_intake COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_cli_binary_intake.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_research_tools COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_research_tools.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_repository_invariants COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/scripts/check_repository_invariants.py)
endif()
