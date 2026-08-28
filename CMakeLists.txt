# SPDX-License-Identifier: GPL-3.0-only

cmake_minimum_required(VERSION 3.20)
project(PPCLab VERSION 3.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(PPC_LAB_ENABLE_UNICORN "Enable Unicorn PPC32 backend when development files are available" ON)
option(PPC_LAB_ENABLE_SANITIZERS "Build with AddressSanitizer and UBSan" OFF)

include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

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
    src/UniversalImage.cpp
    src/BuiltinInterpreter.cpp
    src/UnicornBackend.cpp
    src/Microtests.cpp)

target_include_directories(ppc_lab PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>)
target_compile_features(ppc_lab PUBLIC cxx_std_20)

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
target_compile_definitions(ppc_lab_cli PRIVATE PPC_LAB_VERSION="${PROJECT_VERSION}")
set_target_properties(ppc_lab PROPERTIES EXPORT_NAME core)
set_target_properties(ppc_lab_cli PROPERTIES OUTPUT_NAME ppc-lab EXPORT_NAME cli)


install(TARGETS ppc_lab ppc_lab_cli
    EXPORT PPCLabTargets
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    INCLUDES DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(FILES LICENSE README.md CHANGELOG.md DESTINATION ${CMAKE_INSTALL_DOCDIR})
install(DIRECTORY docs/ DESTINATION ${CMAKE_INSTALL_DOCDIR}/docs)
install(DIRECTORY schemas/ DESTINATION ${CMAKE_INSTALL_DATADIR}/ppc-lab/schemas)
install(PROGRAMS scripts/ppc_lab_worker.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-worker)
install(PROGRAMS scripts/ppc_lab_orchestrate.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-orchestrate)
install(PROGRAMS scripts/ppc_lab_fleet.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-fleet)
install(PROGRAMS scripts/ppc_lab_evidence.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-evidence)
install(FILES scripts/ppc_trace_intelligence.py DESTINATION ${CMAKE_INSTALL_BINDIR})
install(PROGRAMS scripts/ppc_trace_capture.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-trace-capture)
install(PROGRAMS scripts/ppc_trace_analyze.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-trace-analyze)
install(PROGRAMS scripts/ppc_trace_diff.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-trace-diff)
install(PROGRAMS scripts/ppc_lab_api.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-api)
# v1.8 differential triage stays a standard-library client of stable trace/worker protocols.
install(PROGRAMS scripts/ppc_lab_corpus.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-corpus)
install(PROGRAMS scripts/ppc_lab_triage.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-triage)
install(PROGRAMS scripts/ppc_lab_explore.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-explore)
install(PROGRAMS scripts/ppc_lab_prioritize.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-prioritize)
install(PROGRAMS scripts/ppc_lab_campaign.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-campaign)
install(PROGRAMS scripts/ppc_lab_schedule.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-schedule)
install(PROGRAMS scripts/ppc_lab_control.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-control)
install(PROGRAMS scripts/ppc_lab_knowledge.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-knowledge)
install(PROGRAMS scripts/ppc_lab_hypothesize.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-hypothesize)
install(PROGRAMS scripts/ppc_lab_platform.py DESTINATION ${CMAKE_INSTALL_BINDIR} RENAME ppc-lab-platform)
install(EXPORT PPCLabTargets
    FILE PPCLabTargets.cmake
    NAMESPACE PPCLab::
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/PPCLab)
configure_package_config_file(
    cmake/PPCLabConfig.cmake.in
    ${CMAKE_CURRENT_BINARY_DIR}/PPCLabConfig.cmake
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/PPCLab)
write_basic_package_version_file(
    ${CMAKE_CURRENT_BINARY_DIR}/PPCLabConfigVersion.cmake
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY SameMajorVersion)
install(FILES
    ${CMAKE_CURRENT_BINARY_DIR}/PPCLabConfig.cmake
    ${CMAKE_CURRENT_BINARY_DIR}/PPCLabConfigVersion.cmake
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/PPCLab)

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
add_executable(ppc_lab_execution_coverage_tests tests/test_execution_coverage.cpp)
target_link_libraries(ppc_lab_execution_coverage_tests PRIVATE ppc_lab)
add_executable(ppc_lab_property_tests tests/test_interpreter_properties.cpp)
target_link_libraries(ppc_lab_property_tests PRIVATE ppc_lab)
add_executable(ppc_lab_backend_parity_tests tests/test_backend_parity.cpp)
target_link_libraries(ppc_lab_backend_parity_tests PRIVATE ppc_lab)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(ppc_lab_tests PRIVATE -UNDEBUG)
    target_compile_options(ppc_lab_call_tests PRIVATE -UNDEBUG)
    target_compile_options(ppc_lab_elf32_tests PRIVATE -UNDEBUG)
    target_compile_options(ppc_lab_elf32_reloc_tests PRIVATE -UNDEBUG)
    target_compile_options(ppc_lab_macho_tests PRIVATE -UNDEBUG)
    target_compile_options(ppc_lab_pef_tests PRIVATE -UNDEBUG)
    target_compile_options(ppc_lab_import_stub_tests PRIVATE -UNDEBUG)
    target_compile_options(ppc_lab_execution_coverage_tests PRIVATE -UNDEBUG)
    target_compile_options(ppc_lab_property_tests PRIVATE -UNDEBUG)
    target_compile_options(ppc_lab_backend_parity_tests PRIVATE -UNDEBUG)
endif()

enable_testing()
add_test(NAME ppc_lab_tests COMMAND ppc_lab_tests)
add_test(NAME ppc_lab_call_tests COMMAND ppc_lab_call_tests)
add_test(NAME ppc_lab_elf32_tests COMMAND ppc_lab_elf32_tests)
add_test(NAME ppc_lab_elf32_reloc_tests COMMAND ppc_lab_elf32_reloc_tests)
add_test(NAME ppc_lab_macho_tests COMMAND ppc_lab_macho_tests)
add_test(NAME ppc_lab_pef_tests COMMAND ppc_lab_pef_tests)
add_test(NAME ppc_lab_import_stub_tests COMMAND ppc_lab_import_stub_tests)
add_test(NAME ppc_lab_execution_coverage_tests COMMAND ppc_lab_execution_coverage_tests)
add_test(NAME ppc_lab_property_tests COMMAND ppc_lab_property_tests)
add_test(NAME ppc_lab_backend_parity_tests COMMAND ppc_lab_backend_parity_tests)
add_test(NAME ppc_lab_cli_selftest COMMAND ppc-lab selftest --backend builtin)
find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_Interpreter_FOUND)
    add_test(NAME ppc_lab_result_tools COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_result_tools.py)
    add_test(NAME ppc_lab_cli_elf COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_cli_elf.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_cli_binary_intake COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_cli_binary_intake.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_research_tools COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_research_tools.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_malformed_intake COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_malformed_intake.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_repository_invariants COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/scripts/check_repository_invariants.py)
    add_test(NAME ppc_lab_install_contract COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_install_contract.py ${CMAKE_COMMAND} ${CMAKE_BINARY_DIR})
    add_test(NAME ppc_lab_worker_protocol COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_worker_protocol.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_orchestration COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_orchestration.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_fleet COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_fleet.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_evidence_store COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_evidence_store.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_http_api COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_http_api.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_trace_intelligence COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_trace_intelligence.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_behavioral_corpus COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_behavioral_corpus.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_differential_triage COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_differential_triage.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_guided_exploration COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_guided_exploration.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_campaign_intelligence COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_campaign_intelligence.py)
    add_test(NAME ppc_lab_autonomous_campaign COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_autonomous_campaign.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_campaign_scheduler COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_campaign_scheduler.py)
    add_test(NAME ppc_lab_campaign_control_plane COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_campaign_control_plane.py)
    add_test(NAME ppc_lab_knowledge_graph COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_knowledge_graph.py)
    add_test(NAME ppc_lab_hypothesis_engine COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_hypothesis_engine.py)
    add_test(NAME ppc_lab_platform_consolidation COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_platform_consolidation.py $<TARGET_FILE:ppc_lab_cli>)
    add_test(NAME ppc_lab_platform_acceptance COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_platform_acceptance.py $<TARGET_FILE:ppc_lab_cli>)
    set_tests_properties(ppc_lab_platform_acceptance PROPERTIES RUN_SERIAL TRUE TIMEOUT 180)
endif()
