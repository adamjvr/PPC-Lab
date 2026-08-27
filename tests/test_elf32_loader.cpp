// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/BuiltinInterpreter.hpp"
#include "ppclab/ppc/CallHarness.hpp"
#include "ppclab/ppc/Elf32Loader.hpp"

#include <cassert>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

namespace {

void put16(std::vector<std::uint8_t>& bytes, std::size_t off, std::uint16_t value) {
    bytes.at(off) = static_cast<std::uint8_t>(value >> 8U);
    bytes.at(off + 1) = static_cast<std::uint8_t>(value);
}

void put32(std::vector<std::uint8_t>& bytes, std::size_t off, std::uint32_t value) {
    bytes.at(off) = static_cast<std::uint8_t>(value >> 24U);
    bytes.at(off + 1) = static_cast<std::uint8_t>(value >> 16U);
    bytes.at(off + 2) = static_cast<std::uint8_t>(value >> 8U);
    bytes.at(off + 3) = static_cast<std::uint8_t>(value);
}

std::filesystem::path makeElf(const std::filesystem::path& dir) {
    constexpr std::uint32_t codeAddress = 0x00100000U;
    constexpr std::uint32_t dataAddress = 0x00200000U;
    constexpr std::size_t codeOffset = 0x100;
    constexpr std::size_t dataOffset = 0x108;

    std::vector<std::uint8_t> bytes(0x10c, 0);
    bytes[0] = 0x7f;
    bytes[1] = 'E';
    bytes[2] = 'L';
    bytes[3] = 'F';
    bytes[4] = 1; // ELFCLASS32
    bytes[5] = 2; // ELFDATA2MSB
    bytes[6] = 1; // EV_CURRENT

    put16(bytes, 16, 2);  // ET_EXEC
    put16(bytes, 18, 20); // EM_PPC
    put32(bytes, 20, 1);  // EV_CURRENT
    put32(bytes, 24, codeAddress);
    put32(bytes, 28, 52); // e_phoff
    put32(bytes, 36, 0);  // e_flags
    put16(bytes, 40, 52); // e_ehsize
    put16(bytes, 42, 32); // e_phentsize
    put16(bytes, 44, 2);  // e_phnum

    // PT_LOAD code: R-X
    const std::size_t ph0 = 52;
    put32(bytes, ph0 + 0, 1);
    put32(bytes, ph0 + 4, static_cast<std::uint32_t>(codeOffset));
    put32(bytes, ph0 + 8, codeAddress);
    put32(bytes, ph0 + 12, codeAddress);
    put32(bytes, ph0 + 16, 8);
    put32(bytes, ph0 + 20, 8);
    put32(bytes, ph0 + 24, 5);
    put32(bytes, ph0 + 28, 4);

    // PT_LOAD data: RW-, with 12 bytes of BSS after the 4 file bytes.
    const std::size_t ph1 = ph0 + 32;
    put32(bytes, ph1 + 0, 1);
    put32(bytes, ph1 + 4, static_cast<std::uint32_t>(dataOffset));
    put32(bytes, ph1 + 8, dataAddress);
    put32(bytes, ph1 + 12, dataAddress);
    put32(bytes, ph1 + 16, 4);
    put32(bytes, ph1 + 20, 16);
    put32(bytes, ph1 + 24, 6);
    put32(bytes, ph1 + 28, 4);

    // addi r3,r3,7 ; blr
    put32(bytes, codeOffset + 0, 0x38630007U);
    put32(bytes, codeOffset + 4, 0x4e800020U);
    put32(bytes, dataOffset, 0x11223344U);

    const auto path = dir / "synthetic_ppc32be.elf";
    std::ofstream out(path, std::ios::binary);
    out.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    return path;
}

} // namespace

int main() {
    namespace fs = std::filesystem;
    const auto dir = fs::temp_directory_path() / "ppc_lab_elf32_test";
    fs::remove_all(dir);
    fs::create_directories(dir);
    const auto path = makeElf(dir);

    ppclab::ppc::Elf32ImageInfo info{};
    std::string error;
    assert(ppclab::ppc::Elf32Loader::inspectFile(path.string(), info, error));
    assert(info.type == 2);
    assert(info.machine == 20);
    assert(info.entry == 0x00100000U);
    assert(info.loadSegments.size() == 2);
    assert(ppclab::ppc::elf32SegmentFlags(info.loadSegments[0].flags) == "R-X");
    assert(ppclab::ppc::elf32SegmentFlags(info.loadSegments[1].flags) == "RW-");

    ppclab::ppc::Memory memory;
    assert(ppclab::ppc::Elf32Loader::loadFile(path.string(), memory, info, error));
    assert(memory.executable(0x00100000U, 4));
    assert(!memory.writable(0x00100000U, 4));
    assert(memory.writable(0x00200000U, 16));
    std::uint32_t data = 0;
    assert(memory.read32(0x00200000U, data));
    assert(data == 0x11223344U);
    assert(memory.read32(0x00200004U, data));
    assert(data == 0U); // BSS zero-fill

    ppclab::ppc::CallConfig config{};
    config.image.elfPath = path.string();
    config.registers.push_back({3, 5});
    ppclab::ppc::BuiltinInterpreter backend;
    const auto result = ppclab::ppc::CallHarness::run(config, backend);
    assert(result.execution.reason == ppclab::ppc::StopReason::Returned);
    assert(result.cpu.gpr[3] == 12U);
    assert(result.execution.instructions == 2U);

    // Reject little-endian ELF rather than silently executing swapped bytes.
    {
        std::fstream io(path, std::ios::binary | std::ios::in | std::ios::out);
        io.seekp(5);
        const char little = 1;
        io.write(&little, 1);
    }
    assert(!ppclab::ppc::Elf32Loader::inspectFile(path.string(), info, error));
    assert(error.find("big-endian") != std::string::npos);

    // ET_DYN is accepted in v0.3 and rebased by the loader.
    {
        std::fstream io(path, std::ios::binary | std::ios::in | std::ios::out);
        io.seekp(5);
        const char big = 2;
        io.write(&big, 1);
        io.seekp(16);
        const char dyn[2]{0, 3};
        io.write(dyn, 2);
    }
    assert(ppclab::ppc::Elf32Loader::inspectFile(path.string(), info, error));
    assert(info.type == 3);
    ppclab::ppc::Memory dynMemory;
    assert(ppclab::ppc::Elf32Loader::loadFile(path.string(), dynMemory, info, error, 0x10000000U));
    assert(info.entry == 0x10100000U);
    assert(dynMemory.executable(0x10100000U, 4));

    fs::remove_all(dir);
    return 0;
}
