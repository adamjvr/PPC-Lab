// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include "ppclab/ppc/ImageSymbol.hpp"
#include "ppclab/ppc/Memory.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace ppclab::ppc {

struct MachOSegmentInfo {
    std::string name{};
    std::uint32_t vmAddress = 0;
    std::uint32_t vmSize = 0;
    std::uint32_t fileOffset = 0;
    std::uint32_t fileSize = 0;
    std::uint32_t maxProt = 0;
    std::uint32_t initProt = 0;
    std::uint32_t mappedAddress = 0;
};

struct MachOSectionInfo {
    std::uint32_t ordinal = 0;
    std::string sectionName{};
    std::string segmentName{};
    std::uint32_t address = 0;
    std::uint32_t size = 0;
    std::uint32_t fileOffset = 0;
    std::uint32_t alignmentPower = 0;
    std::uint32_t relocationOffset = 0;
    std::uint32_t relocationCount = 0;
    std::uint32_t flags = 0;
    std::uint32_t mappedAddress = 0;
};

struct MachOImageInfo {
    std::uint32_t fileType = 0;
    std::uint32_t flags = 0;
    std::uint32_t entry = 0;
    std::uint32_t loadBias = 0;
    bool fatContainer = false;
    std::uint32_t sliceOffset = 0;
    std::uint32_t sliceSize = 0;
    std::vector<MachOSegmentInfo> segments{};
    std::vector<MachOSectionInfo> sections{};
    std::vector<ImageSymbol> symbols{};
};

class MachOLoader {
public:
    // Inspect thin or fat 32-bit big-endian PowerPC Mach-O files.
    static bool inspectFile(const std::string& path,
                            MachOImageInfo& info,
                            std::string& error);

    // Load MH_EXECUTE/MH_BUNDLE at their VM addresses, MH_DYLIB rebased so its
    // first segment starts at imageBase, and MH_OBJECT sections at imageBase.
    // Common non-scattered PowerPC relocations are applied; unresolved external
    // symbols can be supplied through bindings.
    static bool loadFile(const std::string& path,
                         Memory& memory,
                         MachOImageInfo& info,
                         std::string& error,
                         std::uint32_t imageBase = 0x10000000U,
                         const std::vector<SymbolBinding>& bindings = {});
};

[[nodiscard]] std::string machoFileTypeName(std::uint32_t type);
[[nodiscard]] std::string machoVmProtection(std::uint32_t protection);

} // namespace ppclab::ppc
