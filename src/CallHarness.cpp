// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/CallHarness.hpp"
#include "ppclab/ppc/Elf32Loader.hpp"
#include "ppclab/ppc/MachOLoader.hpp"
#include "ppclab/ppc/PefLoader.hpp"

#include <algorithm>
#include <bit>
#include <fstream>

namespace ppclab::ppc {
namespace {

std::size_t fileSize(const std::string& path) {
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    if (!in) return 0;
    return static_cast<std::size_t>(in.tellg());
}

bool chooseSymbolEntry(const std::string& requested,
                       const std::vector<ImageSymbol>& symbols,
                       std::uint32_t& entry,
                       std::string& error) {
    if (requested.empty()) return true;
    const auto* symbol = findImageSymbol(symbols, requested);
    if (!symbol || !symbol->defined) {
        error = "entry symbol not found/resolved: " + requested;
        return false;
    }
    entry = symbol->value;
    return true;
}

} // namespace

bool CallHarness::prepare(const CallConfig& config,
                          Memory& memory,
                          CpuState& cpu,
                          std::string& error) {
    const bool hasRaw = !config.image.codePath.empty();
    const bool hasElf = !config.image.elfPath.empty();
    const bool hasMacho = !config.image.machoPath.empty();
    const bool hasPef = !config.image.pefPath.empty();
    const unsigned inputCount = static_cast<unsigned>(hasRaw) + static_cast<unsigned>(hasElf) +
                                static_cast<unsigned>(hasMacho) + static_cast<unsigned>(hasPef);
    if (inputCount != 1) {
        error = "exactly one of --code, --elf, --macho or --pef is required";
        return false;
    }

    std::uint32_t imageEntry = 0;
    if (hasElf) {
        Elf32ImageInfo elf{};
        if (!Elf32Loader::loadFile(config.image.elfPath, memory, elf, error,
                                   config.image.imageBase, config.image.symbolBindings)) return false;
        imageEntry = elf.entry;
        if (!chooseSymbolEntry(config.entrySymbol, elf.symbols, imageEntry, error)) return false;
    } else if (hasMacho) {
        MachOImageInfo macho{};
        if (!MachOLoader::loadFile(config.image.machoPath, memory, macho, error,
                                   config.image.imageBase, config.image.symbolBindings)) return false;
        imageEntry = macho.entry;
        if (!chooseSymbolEntry(config.entrySymbol, macho.symbols, imageEntry, error)) return false;
    } else if (hasPef) {
        PefImageInfo pef{};
        if (!PefLoader::loadFile(config.image.pefPath, memory, pef, error,
                                 config.image.imageBase, config.image.symbolBindings)) return false;
        imageEntry = pef.entry;
        if (!chooseSymbolEntry(config.entrySymbol, pef.symbols, imageEntry, error)) return false;
    } else {
        if (!config.entrySymbol.empty()) {
            error = "--entry-symbol requires ELF, Mach-O or PEF symbol metadata";
            return false;
        }
        const auto codeSize = fileSize(config.image.codePath);
        if (codeSize == 0) {
            error = "cannot read code image: " + config.image.codePath;
            return false;
        }
        if (!memory.loadFile(config.image.codeBase, config.image.codePath, codeSize,
                             MemoryPerm::Read | MemoryPerm::Execute, "code")) {
            error = "failed to map code image";
            return false;
        }
    }

    if (!config.image.dataPath.empty()) {
        const auto dataSize = fileSize(config.image.dataPath);
        if (dataSize == 0) {
            error = "cannot read data image: " + config.image.dataPath;
            return false;
        }
        const auto mapped = std::max(config.image.dataMapSize, dataSize);
        if (!memory.loadFile(config.image.dataBase, config.image.dataPath, mapped,
                             MemoryPerm::Read | MemoryPerm::Write, "data")) {
            error = "failed to map data image";
            return false;
        }
    } else if (hasRaw) {
        if (!memory.map(config.image.dataBase, config.image.dataMapSize,
                        MemoryPerm::Read | MemoryPerm::Write, "data")) {
            error = "failed to map data region";
            return false;
        }
    }

    if (!memory.map(config.execution.importBase, config.execution.importSize,
                    MemoryPerm::Read | MemoryPerm::Execute, "imports")) {
        error = "failed to map import trap region (possibly overlaps the input image)";
        return false;
    }
    if (!memory.map(config.image.heapBase, config.image.heapSize,
                    MemoryPerm::Read | MemoryPerm::Write, "heap")) {
        error = "failed to map heap (possibly overlaps the input image)";
        return false;
    }
    if (!memory.map(config.image.stackBase, config.image.stackSize,
                    MemoryPerm::Read | MemoryPerm::Write, "stack")) {
        error = "failed to map stack (possibly overlaps the input image)";
        return false;
    }

    cpu.gpr[1] = config.image.stackBase + static_cast<std::uint32_t>(config.image.stackSize) - 0x40U;
    cpu.gpr[1] &= ~0x0fU;
    cpu.gpr[2] = config.toc;
    cpu.lr = config.execution.returnAddress;
    cpu.pc = config.entry != 0 ? config.entry : imageEntry;

    if (config.transitionVector != 0) {
        std::uint32_t entry = 0, toc = 0;
        if (!memory.read32(config.transitionVector, entry) ||
            !memory.read32(config.transitionVector + 4U, toc)) {
            error = "cannot read transition vector";
            return false;
        }
        cpu.pc = entry;
        cpu.gpr[2] = toc;
        cpu.gpr[12] = config.transitionVector;
    } else if (cpu.pc == 0) {
        error = hasRaw ? "--entry or --transition-vector is required"
                       : "image has no discoverable entry; supply --entry, --entry-symbol or --transition-vector";
        return false;
    }

    for (const auto& assignment : config.registers) {
        if (assignment.index >= cpu.gpr.size()) {
            error = "invalid GPR assignment";
            return false;
        }
        cpu.gpr[assignment.index] = assignment.value;
    }
    for (const auto& assignment : config.floatRegisters) {
        if (assignment.index >= cpu.fpr.size()) {
            error = "invalid FPR assignment";
            return false;
        }
        cpu.fpr[assignment.index] = assignment.value;
    }
    for (const auto& write : config.writes32) {
        if (!memory.write32(write.address, write.value)) {
            error = "failed --write-u32 at requested address";
            return false;
        }
    }
    for (const auto& write : config.writesFloat) {
        const auto bits = std::bit_cast<std::uint32_t>(write.value);
        if (!memory.write32(write.address, bits)) {
            error = "failed --write-f32 at requested address";
            return false;
        }
    }
    return true;
}

CallResult CallHarness::run(const CallConfig& config, ExecutionBackend& backend) {
    CallResult result{};
    std::string error;
    if (!prepare(config, result.memory, result.cpu, error)) {
        result.execution.reason = StopReason::InvalidConfiguration;
        result.execution.message = std::move(error);
        return result;
    }
    result.execution = backend.run(result.memory, result.cpu, config.execution);
    return result;
}

} // namespace ppclab::ppc
