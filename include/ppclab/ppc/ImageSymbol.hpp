// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace ppclab::ppc {

struct ImageSymbol {
    std::string name{};
    std::uint32_t value = 0;
    std::uint32_t size = 0;
    std::uint32_t sectionIndex = 0;
    std::uint8_t binding = 0;
    std::uint8_t type = 0;
    bool defined = false;
    bool imported = false;
};

struct SymbolBinding {
    std::string name{};
    std::uint32_t address = 0;
};

[[nodiscard]] inline const ImageSymbol* findImageSymbol(const std::vector<ImageSymbol>& symbols,
                                                         const std::string& name) noexcept {
    for (const auto& symbol : symbols) {
        if (symbol.name == name) return &symbol;
    }
    return nullptr;
}

[[nodiscard]] inline bool findSymbolBinding(const std::vector<SymbolBinding>& bindings,
                                            const std::string& name,
                                            std::uint32_t& address) noexcept {
    for (const auto& binding : bindings) {
        if (binding.name == name) {
            address = binding.address;
            return true;
        }
    }
    return false;
}

} // namespace ppclab::ppc
