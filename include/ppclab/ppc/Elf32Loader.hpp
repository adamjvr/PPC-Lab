// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include "ppclab/ppc/ImageSymbol.hpp"
#include "ppclab/ppc/Memory.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace ppclab::ppc {

struct Elf32SegmentInfo {
    std::uint32_t index = 0;
    std::uint32_t fileOffset = 0;
    std::uint32_t virtualAddress = 0;
    std::uint32_t physicalAddress = 0;
    std::uint32_t fileSize = 0;
    std::uint32_t memorySize = 0;
    std::uint32_t flags = 0;
    std::uint32_t alignment = 0;
    std::uint32_t mappedAddress = 0;
};

struct Elf32SectionInfo {
    std::uint32_t index = 0;
    std::string name{};
    std::uint32_t type = 0;
    std::uint32_t flags = 0;
    std::uint32_t address = 0;
    std::uint32_t fileOffset = 0;
    std::uint32_t size = 0;
    std::uint32_t link = 0;
    std::uint32_t info = 0;
    std::uint32_t alignment = 0;
    std::uint32_t entrySize = 0;
    std::uint32_t mappedAddress = 0;
};

struct Elf32ImageInfo {
    std::uint16_t type = 0;
    std::uint16_t machine = 0;
    std::uint32_t originalEntry = 0;
    std::uint32_t entry = 0;
    std::uint32_t flags = 0;
    std::uint32_t loadBias = 0;
    std::uint32_t relocationCount = 0;
    std::vector<Elf32SegmentInfo> loadSegments{};
    std::vector<Elf32SectionInfo> sections{};
    std::vector<ImageSymbol> symbols{};
};

class Elf32Loader {
public:
    // Inspect ELF32/MSB/EM_PPC ET_EXEC, ET_DYN or ET_REL metadata without mapping it.
    static bool inspectFile(const std::string& path,
                            Elf32ImageInfo& info,
                            std::string& error);

    // Load fixed executables, shared/PIE images, or relocatable objects. ET_DYN
    // and ET_REL are rebased at imageBase. Undefined symbols used by supported
    // relocations are resolved from bindings.
    static bool loadFile(const std::string& path,
                         Memory& memory,
                         Elf32ImageInfo& info,
                         std::string& error,
                         std::uint32_t imageBase = 0x10000000U,
                         const std::vector<SymbolBinding>& bindings = {});
};

[[nodiscard]] std::string elf32SegmentFlags(std::uint32_t flags);
[[nodiscard]] std::string elf32TypeName(std::uint16_t type);

} // namespace ppclab::ppc
