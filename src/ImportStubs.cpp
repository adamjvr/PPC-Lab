// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/ImportStubs.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

namespace ppclab::ppc {

const char* importStubKindName(ImportStubKind kind) noexcept {
    switch (kind) {
    case ImportStubKind::Pow: return "pow";
    case ImportStubKind::Cos: return "cos";
    case ImportStubKind::Sqrt: return "sqrt";
    case ImportStubKind::Sin: return "sin";
    case ImportStubKind::Exp: return "exp";
    case ImportStubKind::Fabs: return "fabs";
    case ImportStubKind::Floor: return "floor";
    case ImportStubKind::Ceil: return "ceil";
    case ImportStubKind::BlockMoveData: return "blockmove";
    case ImportStubKind::Memcpy: return "memcpy";
    case ImportStubKind::Memmove: return "memmove";
    case ImportStubKind::Memset: return "memset";
    case ImportStubKind::Bzero: return "bzero";
    }
    return "unknown";
}

bool parseImportStubKind(std::string_view name, ImportStubKind& out) noexcept {
    if (name == "pow") out = ImportStubKind::Pow;
    else if (name == "cos") out = ImportStubKind::Cos;
    else if (name == "sqrt") out = ImportStubKind::Sqrt;
    else if (name == "sin") out = ImportStubKind::Sin;
    else if (name == "exp") out = ImportStubKind::Exp;
    else if (name == "fabs") out = ImportStubKind::Fabs;
    else if (name == "floor") out = ImportStubKind::Floor;
    else if (name == "ceil") out = ImportStubKind::Ceil;
    else if (name == "blockmove" || name == "blockmovedata") out = ImportStubKind::BlockMoveData;
    else if (name == "memcpy") out = ImportStubKind::Memcpy;
    else if (name == "memmove") out = ImportStubKind::Memmove;
    else if (name == "memset") out = ImportStubKind::Memset;
    else if (name == "bzero") out = ImportStubKind::Bzero;
    else return false;
    return true;
}

const ImportStubBinding* findImportStub(const std::vector<ImportStubBinding>& bindings,
                                        std::uint32_t address) noexcept {
    for (const auto& binding : bindings) if (binding.address == address) return &binding;
    return nullptr;
}

namespace {
ImportStubResult ok(bool exact = true) { return {true, true, exact, {}}; }
ImportStubResult bad(std::string message) { return {true, false, false, std::move(message)}; }

bool readRange(const Memory& memory, std::uint32_t address, std::uint32_t count,
               std::vector<std::uint8_t>& bytes) {
    if (count > 0x01000000U) return false;
    bytes.resize(count);
    return count == 0 || memory.readBytes(address, bytes);
}
}

ImportStubResult executeImportStub(const ImportStubBinding& binding,
                                   Memory& memory,
                                   CpuState& cpu) {
    switch (binding.kind) {
    case ImportStubKind::Pow: cpu.fpr[1] = std::pow(cpu.fpr[1], cpu.fpr[2]); return ok(false);
    case ImportStubKind::Cos: cpu.fpr[1] = std::cos(cpu.fpr[1]); return ok(false);
    case ImportStubKind::Sqrt: cpu.fpr[1] = std::sqrt(cpu.fpr[1]); return ok(false);
    case ImportStubKind::Sin: cpu.fpr[1] = std::sin(cpu.fpr[1]); return ok(false);
    case ImportStubKind::Exp: cpu.fpr[1] = std::exp(cpu.fpr[1]); return ok(false);
    case ImportStubKind::Fabs: cpu.fpr[1] = std::fabs(cpu.fpr[1]); return ok(false);
    case ImportStubKind::Floor: cpu.fpr[1] = std::floor(cpu.fpr[1]); return ok(false);
    case ImportStubKind::Ceil: cpu.fpr[1] = std::ceil(cpu.fpr[1]); return ok(false);
    case ImportStubKind::BlockMoveData: {
        const auto source = cpu.gpr[3], destination = cpu.gpr[4], count = cpu.gpr[5];
        std::vector<std::uint8_t> bytes;
        if (!readRange(memory, source, count, bytes) || (count && !memory.writeBytes(destination, bytes)))
            return bad("BlockMoveData source/destination is outside mapped memory");
        return ok();
    }
    case ImportStubKind::Memcpy:
    case ImportStubKind::Memmove: {
        const auto destination = cpu.gpr[3], source = cpu.gpr[4], count = cpu.gpr[5];
        std::vector<std::uint8_t> bytes;
        if (!readRange(memory, source, count, bytes) || (count && !memory.writeBytes(destination, bytes)))
            return bad("memcpy/memmove source/destination is outside mapped memory");
        cpu.gpr[3] = destination;
        return ok();
    }
    case ImportStubKind::Memset: {
        const auto destination = cpu.gpr[3];
        const auto value = static_cast<std::uint8_t>(cpu.gpr[4]);
        const auto count = cpu.gpr[5];
        if (count > 0x01000000U) return bad("memset count is unreasonable");
        std::vector<std::uint8_t> bytes(count, value);
        if (count && !memory.writeBytes(destination, bytes)) return bad("memset destination is outside mapped memory");
        cpu.gpr[3] = destination;
        return ok();
    }
    case ImportStubKind::Bzero: {
        const auto destination = cpu.gpr[3], count = cpu.gpr[4];
        if (count > 0x01000000U) return bad("bzero count is unreasonable");
        std::vector<std::uint8_t> bytes(count, 0);
        if (count && !memory.writeBytes(destination, bytes)) return bad("bzero destination is outside mapped memory");
        return ok();
    }
    }
    return {false, false, false, "unknown import stub"};
}

} // namespace ppclab::ppc
