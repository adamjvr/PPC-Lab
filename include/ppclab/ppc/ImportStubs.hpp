// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include "ppclab/ppc/Cpu.hpp"
#include "ppclab/ppc/Memory.hpp"

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace ppclab::ppc {

enum class ImportStubKind : std::uint8_t {
    Pow,
    Cos,
    Sqrt,
    Sin,
    Exp,
    BlockMoveData,
};

struct ImportStubBinding {
    std::uint32_t address = 0;
    ImportStubKind kind = ImportStubKind::BlockMoveData;
    std::string name{};
};

struct ImportStubResult {
    bool handled = false;
    bool success = false;
    bool fidelityExact = false;
    std::string message{};
};

[[nodiscard]] const char* importStubKindName(ImportStubKind kind) noexcept;
[[nodiscard]] bool parseImportStubKind(std::string_view name, ImportStubKind& out) noexcept;
[[nodiscard]] const ImportStubBinding* findImportStub(
    const std::vector<ImportStubBinding>& bindings,
    std::uint32_t address) noexcept;
[[nodiscard]] ImportStubResult executeImportStub(const ImportStubBinding& binding,
                                                 Memory& memory,
                                                 CpuState& cpu);

} // namespace ppclab::ppc
