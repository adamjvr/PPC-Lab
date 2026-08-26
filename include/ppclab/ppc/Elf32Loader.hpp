// SPDX-License-Identifier: GPL-3.0-only

#pragma once

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
};

struct Elf32ImageInfo {
    std::uint16_t type = 0;
    std::uint16_t machine = 0;
    std::uint32_t entry = 0;
    std::uint32_t flags = 0;
    std::vector<Elf32SegmentInfo> loadSegments{};
};

class Elf32Loader {
public:
    // Inspect a 32-bit big-endian PowerPC ELF executable without mapping it.
    static bool inspectFile(const std::string& path,
                            Elf32ImageInfo& info,
                            std::string& error);

    // Map PT_LOAD segments into PPC Lab memory with permissions derived from
    // p_flags. ET_EXEC is supported; relocatable/shared objects are rejected
    // until relocation support exists.
    static bool loadFile(const std::string& path,
                         Memory& memory,
                         Elf32ImageInfo& info,
                         std::string& error);
};

[[nodiscard]] std::string elf32SegmentFlags(std::uint32_t flags);

} // namespace ppclab::ppc
