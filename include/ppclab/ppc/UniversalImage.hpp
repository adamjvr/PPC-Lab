// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include "ppclab/ppc/ImageSymbol.hpp"
#include "ppclab/ppc/Memory.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace ppclab::ppc {

enum class UniversalImageFormat : std::uint8_t {
    Unknown = 0,
    Elf32PpcBe,
    MachOPpc32Be,
    PefCfmPpc,
};

struct UniversalImageInfo {
    UniversalImageFormat format = UniversalImageFormat::Unknown;
    std::uint32_t entry = 0;
    std::vector<ImageSymbol> symbols{};
};

class UniversalImageLoader {
public:
    [[nodiscard]] static UniversalImageFormat detectFile(const std::string& path);
    [[nodiscard]] static const char* formatName(UniversalImageFormat format) noexcept;

    // Inspect a supported container without mapping it into guest memory.
    static bool inspectFile(const std::string& path,
                            UniversalImageInfo& info,
                            std::string& error);

    // Auto-detect and load a supported container into guest memory.
    static bool loadFile(const std::string& path,
                         Memory& memory,
                         UniversalImageInfo& info,
                         std::string& error,
                         std::uint32_t imageBase = 0x10000000U,
                         const std::vector<SymbolBinding>& bindings = {});
};

} // namespace ppclab::ppc
