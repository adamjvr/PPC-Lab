// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/ImportStubs.hpp"

#include <cmath>
#include <vector>

namespace ppclab::ppc {

const char* importStubKindName(ImportStubKind kind) noexcept {
    switch (kind) {
    case ImportStubKind::Pow: return "pow";
    case ImportStubKind::Cos: return "cos";
    case ImportStubKind::Sqrt: return "sqrt";
    case ImportStubKind::Sin: return "sin";
    case ImportStubKind::Exp: return "exp";
    case ImportStubKind::BlockMoveData: return "blockmove";
    }
    return "unknown";
}

bool parseImportStubKind(std::string_view name, ImportStubKind& out) noexcept {
    if (name == "pow") out = ImportStubKind::Pow;
    else if (name == "cos") out = ImportStubKind::Cos;
    else if (name == "sqrt") out = ImportStubKind::Sqrt;
    else if (name == "sin") out = ImportStubKind::Sin;
    else if (name == "exp") out = ImportStubKind::Exp;
    else if (name == "blockmove" || name == "BlockMoveData" || name == "memmove")
        out = ImportStubKind::BlockMoveData;
    else return false;
    return true;
}

const ImportStubBinding* findImportStub(const std::vector<ImportStubBinding>& bindings,
                                        std::uint32_t address) noexcept {
    for (const auto& binding : bindings) {
        if (binding.address == address) return &binding;
    }
    return nullptr;
}

ImportStubResult executeImportStub(const ImportStubBinding& binding,
                                   Memory& memory,
                                   CpuState& cpu) {
    switch (binding.kind) {
    case ImportStubKind::Pow:
        cpu.fpr[1] = std::pow(cpu.fpr[1], cpu.fpr[2]);
        return {true, true, false, "pow via host libm (execution aid; rounding not fidelity-qualified)"};
    case ImportStubKind::Cos:
        cpu.fpr[1] = std::cos(cpu.fpr[1]);
        return {true, true, false, "cos via host libm (execution aid; rounding not fidelity-qualified)"};
    case ImportStubKind::Sqrt:
        cpu.fpr[1] = std::sqrt(cpu.fpr[1]);
        return {true, true, false, "sqrt via host libm (execution aid; rounding not fidelity-qualified)"};
    case ImportStubKind::Sin:
        cpu.fpr[1] = std::sin(cpu.fpr[1]);
        return {true, true, false, "sin via host libm (execution aid; rounding not fidelity-qualified)"};
    case ImportStubKind::Exp:
        cpu.fpr[1] = std::exp(cpu.fpr[1]);
        return {true, true, false, "exp via host libm (execution aid; rounding not fidelity-qualified)"};
    case ImportStubKind::BlockMoveData: {
        const std::uint32_t source = cpu.gpr[3];
        const std::uint32_t destination = cpu.gpr[4];
        const std::uint32_t count = cpu.gpr[5];
        if (count > 0x01000000U)
            return {true, false, true, "blockmove refused implausible byte count"};
        std::vector<std::uint8_t> bytes(count);
        if (count != 0 && !memory.readBytes(source, bytes))
            return {true, false, true, "blockmove source is unreadable"};
        if (count != 0 && !memory.writeBytes(destination, bytes))
            return {true, false, true, "blockmove destination is unwritable"};
        return {true, true, true, binding.name.empty() ? "blockmove" : binding.name};
    }
    }
    return {false, false, false, "unknown import stub"};
}

} // namespace ppclab::ppc
