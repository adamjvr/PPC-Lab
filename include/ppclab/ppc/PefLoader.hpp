// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include "ppclab/ppc/ImageSymbol.hpp"
#include "ppclab/ppc/Memory.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace ppclab::ppc {

struct PefSectionInfo {
    std::uint32_t index = 0;
    std::uint32_t defaultAddress = 0;
    std::uint32_t totalLength = 0;
    std::uint32_t unpackedLength = 0;
    std::uint32_t containerLength = 0;
    std::uint32_t containerOffset = 0;
    std::uint8_t kind = 0;
    std::uint8_t shareKind = 0;
    std::uint8_t alignmentPower = 0;
    std::uint32_t mappedAddress = 0;
};

struct PefImageInfo {
    std::uint32_t architecture = 0;
    std::uint32_t formatVersion = 0;
    std::uint16_t sectionCount = 0;
    std::uint16_t instantiatedSectionCount = 0;
    std::int32_t mainSection = -1;
    std::uint32_t mainOffset = 0;
    std::int32_t initSection = -1;
    std::uint32_t initOffset = 0;
    std::int32_t termSection = -1;
    std::uint32_t termOffset = 0;
    std::uint32_t entry = 0;
    std::uint32_t initTransitionVector = 0;
    std::uint32_t termTransitionVector = 0;
    std::uint32_t importCount = 0;
    std::uint32_t relocationSectionCount = 0;
    std::uint32_t relocationChunkCount = 0;
    std::vector<PefSectionInfo> sections{};
    std::vector<ImageSymbol> symbols{};
};

class PefLoader {
public:
    // Inspect a PEF ('Joy!'/'peff') PowerPC ('pwpc') container.
    static bool inspectFile(const std::string& path,
                            PefImageInfo& info,
                            std::string& error);

    // Instantiate code/data/pidata sections, resolve supplied imports, apply
    // the standard PEF relocation instruction set, and discover main/init/term.
    static bool loadFile(const std::string& path,
                         Memory& memory,
                         PefImageInfo& info,
                         std::string& error,
                         std::uint32_t imageBase = 0x10000000U,
                         const std::vector<SymbolBinding>& bindings = {});
};

[[nodiscard]] std::string pefSectionKindName(std::uint8_t kind);

} // namespace ppclab::ppc
