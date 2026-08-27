// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/BuiltinInterpreter.hpp"
#include "ppclab/ppc/CallHarness.hpp"
#include "ppclab/ppc/MachOLoader.hpp"

#include <cassert>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <vector>

namespace {

void put32(std::vector<std::uint8_t>& bytes, std::size_t offset, std::uint32_t value) {
    bytes[offset] = static_cast<std::uint8_t>(value >> 24U);
    bytes[offset + 1] = static_cast<std::uint8_t>(value >> 16U);
    bytes[offset + 2] = static_cast<std::uint8_t>(value >> 8U);
    bytes[offset + 3] = static_cast<std::uint8_t>(value);
}

void putName(std::vector<std::uint8_t>& bytes, std::size_t offset, const char* text) {
    for (std::size_t i = 0; text[i] != '\0' && i < 16; ++i) bytes[offset + i] = text[i];
}

std::filesystem::path makeMacho(const std::filesystem::path& directory) {
    constexpr std::uint32_t vmAddress = 0x00100000U;
    constexpr std::uint32_t fileOffset = 0x100U;
    constexpr std::uint32_t segmentCommandSize = 124U;
    constexpr std::uint32_t threadCommandSize = 20U;

    std::vector<std::uint8_t> bytes(0x108U, 0);
    put32(bytes, 0, 0xfeedfaceU); // MH_MAGIC
    put32(bytes, 4, 18U);         // CPU_TYPE_POWERPC
    put32(bytes, 8, 0U);
    put32(bytes, 12, 2U);         // MH_EXECUTE
    put32(bytes, 16, 2U);         // ncmds
    put32(bytes, 20, segmentCommandSize + threadCommandSize);
    put32(bytes, 24, 0U);

    std::size_t offset = 28U;
    put32(bytes, offset, 1U); // LC_SEGMENT
    put32(bytes, offset + 4U, segmentCommandSize);
    putName(bytes, offset + 8U, "__TEXT");
    put32(bytes, offset + 24U, vmAddress);
    put32(bytes, offset + 28U, 0x100U);
    put32(bytes, offset + 32U, fileOffset);
    put32(bytes, offset + 36U, 8U);
    put32(bytes, offset + 40U, 5U);
    put32(bytes, offset + 44U, 5U);
    put32(bytes, offset + 48U, 1U); // nsects
    putName(bytes, offset + 56U, "__text");
    putName(bytes, offset + 72U, "__TEXT");
    put32(bytes, offset + 88U, vmAddress);
    put32(bytes, offset + 92U, 8U);
    put32(bytes, offset + 96U, fileOffset);
    put32(bytes, offset + 100U, 2U);
    put32(bytes, offset + 112U, 0x80000400U);

    offset += segmentCommandSize;
    put32(bytes, offset, 5U); // LC_UNIXTHREAD
    put32(bytes, offset + 4U, threadCommandSize);
    put32(bytes, offset + 8U, 1U);  // synthetic flavor
    put32(bytes, offset + 12U, 1U); // one state word
    put32(bytes, offset + 16U, vmAddress);

    put32(bytes, fileOffset, 0x38630007U);      // addi r3,r3,7
    put32(bytes, fileOffset + 4U, 0x4e800020U); // blr

    const auto path = directory / "fixture.macho";
    std::ofstream out(path, std::ios::binary);
    out.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    return path;
}

} // namespace

int main() {
    namespace fs = std::filesystem;
    const auto directory = fs::temp_directory_path() / "ppc_lab_macho";
    fs::remove_all(directory);
    fs::create_directories(directory);
    const auto path = makeMacho(directory);

    ppclab::ppc::MachOImageInfo info{};
    std::string error;
    assert(ppclab::ppc::MachOLoader::inspectFile(path.string(), info, error));
    assert(info.fileType == 2U);
    assert(info.entry == 0x00100000U);

    ppclab::ppc::Memory memory;
    assert(ppclab::ppc::MachOLoader::loadFile(path.string(), memory, info, error));
    assert(info.entry == 0x00100000U);
    assert(memory.executable(info.entry, 4U));

    ppclab::ppc::CallConfig config{};
    config.image.machoPath = path.string();
    config.registers.push_back({3U, 5U});
    ppclab::ppc::BuiltinInterpreter backend;
    const auto result = ppclab::ppc::CallHarness::run(config, backend);
    assert(result.execution.reason == ppclab::ppc::StopReason::Returned);
    assert(result.cpu.gpr[3] == 12U);

    fs::remove_all(directory);
    return 0;
}
