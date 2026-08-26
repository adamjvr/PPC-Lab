// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/BuiltinInterpreter.hpp"
#include "ppclab/ppc/ImportStubs.hpp"

#include <bit>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>

namespace ppclab::ppc {
namespace {

std::int32_t signExtend16(std::uint32_t value) noexcept {
    return static_cast<std::int16_t>(value & 0xffffU);
}
std::int32_t signExtend14Shift2(std::uint32_t value) noexcept {
    std::int32_t v = static_cast<std::int32_t>(value & 0xfffcU);
    if (v & 0x8000) v |= static_cast<std::int32_t>(0xffff0000U);
    return v;
}
std::int32_t signExtend26(std::uint32_t value) noexcept {
    std::int32_t v = static_cast<std::int32_t>(value & 0x03fffffcU);
    if (v & 0x02000000) v |= static_cast<std::int32_t>(0xfc000000U);
    return v;
}

std::uint32_t rotl32(std::uint32_t x, unsigned n) noexcept {
    n &= 31U;
    return n == 0 ? x : (x << n) | (x >> (32U - n));
}

std::uint32_t ppcMask(unsigned mb, unsigned me) noexcept {
    std::uint32_t mask = 0;
    for (unsigned p = 0; p < 32; ++p) {
        const bool selected = mb <= me ? (p >= mb && p <= me) : (p >= mb || p <= me);
        if (selected) mask |= (1U << (31U - p));
    }
    return mask;
}

std::uint32_t effectiveAddressD(const CpuState& cpu, unsigned ra, std::int32_t d) noexcept {
    const std::uint32_t base = ra == 0 ? 0U : cpu.gpr[ra];
    return base + static_cast<std::uint32_t>(d);
}

std::uint32_t effectiveAddressX(const CpuState& cpu, unsigned ra, unsigned rb) noexcept {
    const std::uint32_t base = ra == 0 ? 0U : cpu.gpr[ra];
    return base + cpu.gpr[rb];
}

std::uint32_t sprNumber(std::uint32_t instruction) noexcept {
    return ((instruction >> 16U) & 0x1fU) | ((instruction >> 6U) & 0x3e0U);
}

void updateCr0(CpuState& cpu, std::int32_t value) noexcept {
    cpu.setCrField(0, value < 0, value > 0, value == 0, (cpu.xer & 0x80000000U) != 0);
}

void setCarry(CpuState& cpu, bool carry) noexcept {
    constexpr std::uint32_t kXerCa = 0x20000000U;
    if (carry) cpu.xer |= kXerCa;
    else cpu.xer &= ~kXerCa;
}

bool carrySet(const CpuState& cpu) noexcept {
    return (cpu.xer & 0x20000000U) != 0;
}

void setCompareSigned(CpuState& cpu, unsigned bf, std::int32_t a, std::int32_t b) noexcept {
    cpu.setCrField(bf, a < b, a > b, a == b, (cpu.xer & 0x80000000U) != 0);
}
void setCompareUnsigned(CpuState& cpu, unsigned bf, std::uint32_t a, std::uint32_t b) noexcept {
    cpu.setCrField(bf, a < b, a > b, a == b, (cpu.xer & 0x80000000U) != 0);
}

float singleResult(double value) noexcept {
    return static_cast<float>(value);
}

ExecutionResult fault(std::uint64_t count,
                      std::uint32_t pc,
                      std::uint32_t instruction,
                      StopReason reason,
                      std::string message) {
    return {reason, count, pc, instruction, std::move(message)};
}

std::string hex32(std::uint32_t value) {
    std::ostringstream out;
    out << "0x" << std::hex << std::setw(8) << std::setfill('0') << value;
    return out.str();
}

} // namespace

bool BuiltinInterpreter::evaluateBranchCondition(CpuState& cpu, unsigned bo, unsigned bi) noexcept {
    bool ctrOk = true;
    if ((bo & 0x04U) == 0) {
        --cpu.ctr;
        const bool ctrNonZero = cpu.ctr != 0;
        ctrOk = ctrNonZero ^ ((bo & 0x02U) != 0);
    }
    const bool condOk = (bo & 0x10U) != 0 ||
                        (cpu.crBit(bi) == ((bo & 0x08U) != 0));
    return ctrOk && condOk;
}

ExecutionResult BuiltinInterpreter::run(Memory& memory,
                                        CpuState& cpu,
                                        const ExecutionConfig& config) {
    for (std::uint64_t count = 0; count < config.instructionLimit; ++count) {
        if (cpu.pc == config.returnAddress) {
            return {StopReason::Returned, count, cpu.pc, 0, "returned through harness trampoline"};
        }
        if (cpu.pc >= config.importBase &&
            static_cast<std::uint64_t>(cpu.pc) <
                static_cast<std::uint64_t>(config.importBase) + config.importSize) {
            return fault(count, cpu.pc, 0, StopReason::ImportTrap,
                         "entered import trap range at " + hex32(cpu.pc));
        }
        if (!memory.executable(cpu.pc, 4)) {
            return fault(count, cpu.pc, 0, StopReason::MemoryFault,
                         "instruction fetch from non-executable/unmapped memory");
        }

        std::uint32_t insn = 0;
        if (!memory.read32(cpu.pc, insn)) {
            return fault(count, cpu.pc, 0, StopReason::MemoryFault, "instruction fetch failed");
        }
        const std::uint32_t currentPc = cpu.pc;
        const bool traceThis = config.trace &&
            (!config.traceRange || config.traceRange->contains(currentPc));
        if (traceThis) {
            std::cerr << hex32(currentPc) << "  " << hex32(insn) << "  "
                      << disassemble(currentPc, insn) << '\n';
        }

        cpu.pc += 4U;
        const unsigned opcode = insn >> 26U;
        const unsigned rt = (insn >> 21U) & 31U;
        const unsigned ra = (insn >> 16U) & 31U;
        const unsigned rb = (insn >> 11U) & 31U;
        const std::int32_t simm = signExtend16(insn);
        const std::uint32_t uimm = insn & 0xffffU;
        const bool rc = (insn & 1U) != 0;

        switch (opcode) {
        case 7: // mulli
            cpu.gpr[rt] = static_cast<std::uint32_t>(
                static_cast<std::int64_t>(static_cast<std::int32_t>(cpu.gpr[ra])) *
                static_cast<std::int64_t>(simm));
            break;
        case 8: { // subfic
            const std::uint32_t immediate = static_cast<std::uint32_t>(simm);
            const std::uint64_t wide = static_cast<std::uint64_t>(immediate) +
                                       static_cast<std::uint64_t>(~cpu.gpr[ra]) + 1ULL;
            cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
            setCarry(cpu, (wide >> 32U) != 0);
            break;
        }
        case 10: { // cmplwi
            const unsigned bf = (insn >> 23U) & 7U;
            setCompareUnsigned(cpu, bf, cpu.gpr[ra], uimm);
            break;
        }
        case 11: { // cmpwi
            const unsigned bf = (insn >> 23U) & 7U;
            setCompareSigned(cpu, bf, static_cast<std::int32_t>(cpu.gpr[ra]), simm);
            break;
        }
        case 12: // addic
        case 13: { // addic.
            const std::uint64_t wide = static_cast<std::uint64_t>(cpu.gpr[ra]) +
                                       static_cast<std::uint64_t>(static_cast<std::uint32_t>(simm));
            cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
            setCarry(cpu, (wide >> 32U) != 0);
            if (opcode == 13) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
            break;
        }
        case 14: // addi
            cpu.gpr[rt] = (ra == 0 ? 0U : cpu.gpr[ra]) + static_cast<std::uint32_t>(simm);
            break;
        case 15: // addis
            cpu.gpr[rt] = (ra == 0 ? 0U : cpu.gpr[ra]) +
                          (static_cast<std::uint32_t>(simm) << 16U);
            break;
        case 16: { // bc
            const unsigned bo = (insn >> 21U) & 31U;
            const unsigned bi = (insn >> 16U) & 31U;
            const std::int32_t bd = signExtend14Shift2(insn);
            const bool aa = (insn & 2U) != 0;
            const bool lk = (insn & 1U) != 0;
            const std::uint32_t next = cpu.pc;
            if (lk) cpu.lr = next;
            if (evaluateBranchCondition(cpu, bo, bi)) {
                cpu.pc = aa ? static_cast<std::uint32_t>(bd)
                            : currentPc + static_cast<std::uint32_t>(bd);
            }
            break;
        }
        case 18: { // b/bl
            const std::int32_t li = signExtend26(insn);
            const bool aa = (insn & 2U) != 0;
            const bool lk = (insn & 1U) != 0;
            if (lk) cpu.lr = cpu.pc;
            cpu.pc = aa ? static_cast<std::uint32_t>(li)
                        : currentPc + static_cast<std::uint32_t>(li);
            break;
        }
        case 19: {
            const unsigned xo = (insn >> 1U) & 0x3ffU;
            if (xo == 16U || xo == 528U) { // bclr / bcctr
                const unsigned bo = (insn >> 21U) & 31U;
                const unsigned bi = (insn >> 16U) & 31U;
                const bool lk = (insn & 1U) != 0;
                const std::uint32_t target = (xo == 16U ? cpu.lr : cpu.ctr) & ~3U;
                if (evaluateBranchCondition(cpu, bo, bi)) {
                    // Classic Mac import glue keeps the imported symbol/transition
                    // identity in r12 while loading the external entry/TOC and
                    // branching through CTR. Our relocation tooling deliberately
                    // assigns imports synthetic 4-byte identities; those are not
                    // real overlapping 8-byte transition vectors. Classify the
                    // indirect call by r12 before following the synthetic zero CTR.
                    if (xo == 528U && target == 0U &&
                        cpu.gpr[12] >= config.importBase &&
                        static_cast<std::uint64_t>(cpu.gpr[12]) <
                            static_cast<std::uint64_t>(config.importBase) + config.importSize) {
                        if (const auto* binding = findImportStub(config.importStubs, cpu.gpr[12])) {
                            const auto stub = executeImportStub(*binding, memory, cpu);
                            if (stub.handled) {
                                if (!stub.success) {
                                    return fault(count + 1U, cpu.gpr[12], insn,
                                                 StopReason::MemoryFault, stub.message);
                                }
                                // CFM import glue tail-calls the external routine;
                                // return directly to the caller's preserved LR.
                                cpu.pc = cpu.lr;
                                break;
                            }
                        }
                        return fault(count + 1U, cpu.gpr[12], insn, StopReason::ImportTrap,
                                     "CFM indirect import via r12=" + hex32(cpu.gpr[12]));
                    }
                    if (lk) cpu.lr = cpu.pc;
                    cpu.pc = target;
                }
            } else if (xo == 150U) { // isync
                // no-op in the deterministic user-space harness
            } else {
                return fault(count, currentPc, insn, StopReason::UnsupportedInstruction,
                             "unsupported opcode 19 XO=" + std::to_string(xo));
            }
            break;
        }
        case 20: { // rlwimi
            const unsigned sh = (insn >> 11U) & 31U;
            const unsigned mb = (insn >> 6U) & 31U;
            const unsigned me = (insn >> 1U) & 31U;
            const auto mask = ppcMask(mb, me);
            cpu.gpr[ra] = (cpu.gpr[ra] & ~mask) | (rotl32(cpu.gpr[rt], sh) & mask);
            if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
            break;
        }
        case 21: { // rlwinm
            const unsigned sh = (insn >> 11U) & 31U;
            const unsigned mb = (insn >> 6U) & 31U;
            const unsigned me = (insn >> 1U) & 31U;
            cpu.gpr[ra] = rotl32(cpu.gpr[rt], sh) & ppcMask(mb, me);
            if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
            break;
        }
        case 24: cpu.gpr[ra] = cpu.gpr[rt] | uimm; break; // ori
        case 25: cpu.gpr[ra] = cpu.gpr[rt] | (uimm << 16U); break; // oris
        case 26: cpu.gpr[ra] = cpu.gpr[rt] ^ uimm; break; // xori
        case 27: cpu.gpr[ra] = cpu.gpr[rt] ^ (uimm << 16U); break; // xoris
        case 28: // andi.
            cpu.gpr[ra] = cpu.gpr[rt] & uimm;
            updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
            break;
        case 29: // andis.
            cpu.gpr[ra] = cpu.gpr[rt] & (uimm << 16U);
            updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
            break;
        case 31: {
            const unsigned xo = (insn >> 1U) & 0x3ffU;
            switch (xo) {
            case 0: { // cmpw
                const unsigned bf = (insn >> 23U) & 7U;
                setCompareSigned(cpu, bf, static_cast<std::int32_t>(cpu.gpr[ra]),
                                 static_cast<std::int32_t>(cpu.gpr[rb]));
                break;
            }
            case 8: { // subfc
                const std::uint64_t wide = static_cast<std::uint64_t>(cpu.gpr[rb]) +
                                           static_cast<std::uint64_t>(~cpu.gpr[ra]) + 1ULL;
                cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
                setCarry(cpu, (wide >> 32U) != 0);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 40: // subf
                cpu.gpr[rt] = cpu.gpr[rb] - cpu.gpr[ra];
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            case 10: { // addc
                const std::uint64_t wide = static_cast<std::uint64_t>(cpu.gpr[ra]) + cpu.gpr[rb];
                cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
                setCarry(cpu, (wide >> 32U) != 0);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 266: // add
                cpu.gpr[rt] = cpu.gpr[ra] + cpu.gpr[rb];
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            case 19: // mfcr
                cpu.gpr[rt] = cpu.cr;
                break;
            case 23: { // lwzx
                std::uint32_t value = 0;
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if (!memory.read32(ea, value))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "lwzx failed");
                cpu.gpr[rt] = value;
                break;
            }
            case 24: // slw
                cpu.gpr[ra] = (cpu.gpr[rb] & 0x20U) ? 0U
                    : cpu.gpr[rt] << (cpu.gpr[rb] & 31U);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            case 26: // cntlzw
                cpu.gpr[ra] = cpu.gpr[rt] == 0 ? 32U : static_cast<std::uint32_t>(std::countl_zero(cpu.gpr[rt]));
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            case 28: // and
                cpu.gpr[ra] = cpu.gpr[rt] & cpu.gpr[rb];
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            case 32: { // cmplw
                const unsigned bf = (insn >> 23U) & 7U;
                setCompareUnsigned(cpu, bf, cpu.gpr[ra], cpu.gpr[rb]);
                break;
            }
            case 87: { // lbzx
                std::uint8_t value = 0;
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if (!memory.read8(ea, value))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "lbzx failed");
                cpu.gpr[rt] = value;
                break;
            }
            case 104: // neg
                cpu.gpr[rt] = 0U - cpu.gpr[ra];
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            case 136: { // subfe
                const std::uint64_t wide = static_cast<std::uint64_t>(cpu.gpr[rb]) +
                                           static_cast<std::uint64_t>(~cpu.gpr[ra]) +
                                           static_cast<std::uint64_t>(carrySet(cpu));
                cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
                setCarry(cpu, (wide >> 32U) != 0);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 138: { // adde
                const std::uint64_t wide = static_cast<std::uint64_t>(cpu.gpr[ra]) +
                                           cpu.gpr[rb] + static_cast<std::uint64_t>(carrySet(cpu));
                cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
                setCarry(cpu, (wide >> 32U) != 0);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 144: { // mtcrf
                const unsigned fxm = (insn >> 12U) & 0xffU;
                for (unsigned field = 0; field < 8; ++field) {
                    if ((fxm & (1U << (7U - field))) != 0) {
                        const unsigned shift = 28U - field * 4U;
                        cpu.cr = (cpu.cr & ~(0xfU << shift)) |
                                 (cpu.gpr[rt] & (0xfU << shift));
                    }
                }
                break;
            }
            case 151: { // stwx
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if (!memory.write32(ea, cpu.gpr[rt]))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "stwx failed");
                break;
            }
            case 200: { // subfze
                const std::uint64_t wide = static_cast<std::uint64_t>(~cpu.gpr[ra]) +
                                           static_cast<std::uint64_t>(carrySet(cpu));
                cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
                setCarry(cpu, (wide >> 32U) != 0);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 202: { // addze
                const std::uint64_t wide = static_cast<std::uint64_t>(cpu.gpr[ra]) +
                                           static_cast<std::uint64_t>(carrySet(cpu));
                cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
                setCarry(cpu, (wide >> 32U) != 0);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 215: { // stbx
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if (!memory.write8(ea, static_cast<std::uint8_t>(cpu.gpr[rt])))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "stbx failed");
                break;
            }
            case 235: // mullw
                cpu.gpr[rt] = static_cast<std::uint32_t>(
                    static_cast<std::int64_t>(static_cast<std::int32_t>(cpu.gpr[ra])) *
                    static_cast<std::int64_t>(static_cast<std::int32_t>(cpu.gpr[rb])));
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            case 279: { // lhzx
                std::uint16_t value = 0;
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if (!memory.read16(ea, value))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "lhzx failed");
                cpu.gpr[rt] = value;
                break;
            }
            case 316: // xor
                cpu.gpr[ra] = cpu.gpr[rt] ^ cpu.gpr[rb];
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            case 339: { // mfspr
                const unsigned spr = sprNumber(insn);
                if (spr == 1) cpu.gpr[rt] = cpu.xer;
                else if (spr == 8) cpu.gpr[rt] = cpu.lr;
                else if (spr == 9) cpu.gpr[rt] = cpu.ctr;
                else return fault(count, currentPc, insn, StopReason::UnsupportedInstruction,
                                  "unsupported mfspr SPR=" + std::to_string(spr));
                break;
            }
            case 407: { // sthx
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if (!memory.write16(ea, static_cast<std::uint16_t>(cpu.gpr[rt])))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "sthx failed");
                break;
            }
            case 444: // or
                cpu.gpr[ra] = cpu.gpr[rt] | cpu.gpr[rb];
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            case 459: // divwu
                cpu.gpr[rt] = cpu.gpr[rb] == 0U ? 0U : cpu.gpr[ra] / cpu.gpr[rb];
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            case 491: { // divw
                const auto divisor = static_cast<std::int32_t>(cpu.gpr[rb]);
                const auto dividend = static_cast<std::int32_t>(cpu.gpr[ra]);
                if (divisor == 0 ||
                    (dividend == std::numeric_limits<std::int32_t>::min() && divisor == -1)) {
                    cpu.gpr[rt] = 0U;
                } else {
                    cpu.gpr[rt] = static_cast<std::uint32_t>(dividend / divisor);
                }
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 535: // lfsx
            case 567: { // lfsux
                const auto ea = effectiveAddressX(cpu, ra, rb);
                std::uint32_t bits = 0;
                if (!memory.read32(ea, bits))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "lfsx failed");
                cpu.fpr[rt] = static_cast<double>(std::bit_cast<float>(bits));
                if (xo == 567U) cpu.gpr[ra] = ea;
                break;
            }
            case 599: // lfdx
            case 631: { // lfdux
                const auto ea = effectiveAddressX(cpu, ra, rb);
                std::uint64_t bits = 0;
                if (!memory.read64(ea, bits))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "lfdx failed");
                cpu.fpr[rt] = std::bit_cast<double>(bits);
                if (xo == 631U) cpu.gpr[ra] = ea;
                break;
            }
            case 663: // stfsx
            case 695: { // stfsux
                const auto ea = effectiveAddressX(cpu, ra, rb);
                const auto value = static_cast<float>(cpu.fpr[rt]);
                if (!memory.write32(ea, std::bit_cast<std::uint32_t>(value)))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "stfsx failed");
                if (xo == 695U) cpu.gpr[ra] = ea;
                break;
            }
            case 727: // stfdx
            case 759: { // stfdux
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if (!memory.write64(ea, std::bit_cast<std::uint64_t>(cpu.fpr[rt])))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "stfdx failed");
                if (xo == 759U) cpu.gpr[ra] = ea;
                break;
            }
            case 467: { // mtspr
                const unsigned spr = sprNumber(insn);
                if (spr == 1) cpu.xer = cpu.gpr[rt];
                else if (spr == 8) cpu.lr = cpu.gpr[rt];
                else if (spr == 9) cpu.ctr = cpu.gpr[rt];
                else return fault(count, currentPc, insn, StopReason::UnsupportedInstruction,
                                  "unsupported mtspr SPR=" + std::to_string(spr));
                break;
            }
            case 536: { // srw
                const unsigned shift = cpu.gpr[rb] & 0x3fU;
                cpu.gpr[ra] = shift >= 32 ? 0U : cpu.gpr[rt] >> shift;
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            }
            case 598: // sync
                break;
            case 824: { // srawi
                const unsigned sh = rb;
                cpu.gpr[ra] = static_cast<std::uint32_t>(
                    static_cast<std::int32_t>(cpu.gpr[rt]) >> sh);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            }
            case 922: // extsh
                cpu.gpr[ra] = static_cast<std::uint32_t>(
                    static_cast<std::int32_t>(static_cast<std::int16_t>(cpu.gpr[rt])));
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            case 954: // extsb
                cpu.gpr[ra] = static_cast<std::uint32_t>(
                    static_cast<std::int32_t>(static_cast<std::int8_t>(cpu.gpr[rt])));
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            default:
                return fault(count, currentPc, insn, StopReason::UnsupportedInstruction,
                             "unsupported opcode 31 XO=" + std::to_string(xo));
            }
            break;
        }
        case 32: // lwz
        case 33: { // lwzu
            std::uint32_t value = 0;
            const auto ea = effectiveAddressD(cpu, ra, simm);
            if (!memory.read32(ea, value))
                return fault(count, currentPc, insn, StopReason::MemoryFault, "lwz failed");
            cpu.gpr[rt] = value;
            if (opcode == 33) cpu.gpr[ra] = ea;
            break;
        }
        case 34: // lbz
        case 35: { // lbzu
            std::uint8_t value = 0;
            const auto ea = effectiveAddressD(cpu, ra, simm);
            if (!memory.read8(ea, value))
                return fault(count, currentPc, insn, StopReason::MemoryFault, "lbz failed");
            cpu.gpr[rt] = value;
            if (opcode == 35) cpu.gpr[ra] = ea;
            break;
        }
        case 36: // stw
        case 37: { // stwu
            const auto ea = effectiveAddressD(cpu, ra, simm);
            if (!memory.write32(ea, cpu.gpr[rt]))
                return fault(count, currentPc, insn, StopReason::MemoryFault, "stw failed");
            if (opcode == 37) cpu.gpr[ra] = ea;
            break;
        }
        case 38: // stb
        case 39: { // stbu
            const auto ea = effectiveAddressD(cpu, ra, simm);
            if (!memory.write8(ea, static_cast<std::uint8_t>(cpu.gpr[rt])))
                return fault(count, currentPc, insn, StopReason::MemoryFault, "stb failed");
            if (opcode == 39) cpu.gpr[ra] = ea;
            break;
        }
        case 40: // lhz
        case 41: { // lhzu
            std::uint16_t value = 0;
            const auto ea = effectiveAddressD(cpu, ra, simm);
            if (!memory.read16(ea, value))
                return fault(count, currentPc, insn, StopReason::MemoryFault, "lhz failed");
            cpu.gpr[rt] = value;
            if (opcode == 41) cpu.gpr[ra] = ea;
            break;
        }
        case 42: // lha
        case 43: { // lhau
            std::uint16_t value = 0;
            const auto ea = effectiveAddressD(cpu, ra, simm);
            if (!memory.read16(ea, value))
                return fault(count, currentPc, insn, StopReason::MemoryFault, "lha failed");
            cpu.gpr[rt] = static_cast<std::uint32_t>(
                static_cast<std::int32_t>(static_cast<std::int16_t>(value)));
            if (opcode == 43) cpu.gpr[ra] = ea;
            break;
        }
        case 44: // sth
        case 45: { // sthu
            const auto ea = effectiveAddressD(cpu, ra, simm);
            if (!memory.write16(ea, static_cast<std::uint16_t>(cpu.gpr[rt])))
                return fault(count, currentPc, insn, StopReason::MemoryFault, "sth failed");
            if (opcode == 45) cpu.gpr[ra] = ea;
            break;
        }
        case 46: { // lmw
            std::uint32_t ea = effectiveAddressD(cpu, ra, simm);
            for (unsigned reg = rt; reg < 32; ++reg, ea += 4U) {
                if (!memory.read32(ea, cpu.gpr[reg]))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "lmw failed");
            }
            break;
        }
        case 47: { // stmw
            std::uint32_t ea = effectiveAddressD(cpu, ra, simm);
            for (unsigned reg = rt; reg < 32; ++reg, ea += 4U) {
                if (!memory.write32(ea, cpu.gpr[reg]))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "stmw failed");
            }
            break;
        }
        case 48: // lfs
        case 49: { // lfsu
            std::uint32_t bits = 0;
            const auto ea = effectiveAddressD(cpu, ra, simm);
            if (!memory.read32(ea, bits))
                return fault(count, currentPc, insn, StopReason::MemoryFault, "lfs failed");
            cpu.fpr[rt] = static_cast<double>(std::bit_cast<float>(bits));
            if (opcode == 49) cpu.gpr[ra] = ea;
            break;
        }
        case 50: // lfd
        case 51: { // lfdu
            std::uint64_t bits = 0;
            const auto ea = effectiveAddressD(cpu, ra, simm);
            if (!memory.read64(ea, bits))
                return fault(count, currentPc, insn, StopReason::MemoryFault, "lfd failed");
            cpu.fpr[rt] = std::bit_cast<double>(bits);
            if (opcode == 51) cpu.gpr[ra] = ea;
            break;
        }
        case 52: // stfs
        case 53: { // stfsu
            const auto ea = effectiveAddressD(cpu, ra, simm);
            const float value = static_cast<float>(cpu.fpr[rt]);
            if (!memory.write32(ea, std::bit_cast<std::uint32_t>(value)))
                return fault(count, currentPc, insn, StopReason::MemoryFault, "stfs failed");
            if (opcode == 53) cpu.gpr[ra] = ea;
            break;
        }
        case 54: // stfd
        case 55: { // stfdu
            const auto ea = effectiveAddressD(cpu, ra, simm);
            if (!memory.write64(ea, std::bit_cast<std::uint64_t>(cpu.fpr[rt])))
                return fault(count, currentPc, insn, StopReason::MemoryFault, "stfd failed");
            if (opcode == 55) cpu.gpr[ra] = ea;
            break;
        }
        case 59: { // single-precision FP A-form
            const unsigned frt = rt, fra = ra, frb = rb, frc = (insn >> 6U) & 31U;
            const unsigned xo = (insn >> 1U) & 31U;
            double result = 0.0;
            switch (xo) {
            case 18: result = singleResult(cpu.fpr[fra] / cpu.fpr[frb]); break; // fdivs
            case 20: result = singleResult(cpu.fpr[fra] - cpu.fpr[frb]); break; // fsubs
            case 21: result = singleResult(cpu.fpr[fra] + cpu.fpr[frb]); break; // fadds
            case 25: result = singleResult(cpu.fpr[fra] * cpu.fpr[frc]); break; // fmuls
            case 28: result = singleResult(std::fma(cpu.fpr[fra], cpu.fpr[frc], -cpu.fpr[frb])); break;
            case 29: result = singleResult(std::fma(cpu.fpr[fra], cpu.fpr[frc], cpu.fpr[frb])); break;
            case 30: result = singleResult(-std::fma(cpu.fpr[fra], cpu.fpr[frc], -cpu.fpr[frb])); break;
            case 31: result = singleResult(-std::fma(cpu.fpr[fra], cpu.fpr[frc], cpu.fpr[frb])); break;
            default:
                return fault(count, currentPc, insn, StopReason::UnsupportedInstruction,
                             "unsupported opcode 59 XO=" + std::to_string(xo));
            }
            cpu.fpr[frt] = result;
            break;
        }
        case 63: {
            const unsigned frt = rt, fra = ra, frb = rb, frc = (insn >> 6U) & 31U;
            const unsigned xo5 = (insn >> 1U) & 31U;
            if (xo5 == 25U || (xo5 >= 28U && xo5 <= 31U)) {
                double result = 0.0;
                if (xo5 == 25U) result = cpu.fpr[fra] * cpu.fpr[frc];
                else if (xo5 == 28U) result = std::fma(cpu.fpr[fra], cpu.fpr[frc], -cpu.fpr[frb]);
                else if (xo5 == 29U) result = std::fma(cpu.fpr[fra], cpu.fpr[frc], cpu.fpr[frb]);
                else if (xo5 == 30U) result = -std::fma(cpu.fpr[fra], cpu.fpr[frc], -cpu.fpr[frb]);
                else result = -std::fma(cpu.fpr[fra], cpu.fpr[frc], cpu.fpr[frb]);
                cpu.fpr[frt] = result;
                break;
            }
            const unsigned xo = (insn >> 1U) & 0x3ffU;
            switch (xo) {
            case 0: // fcmpu
            case 32: { // fcmpo
                const unsigned bf = (insn >> 23U) & 7U;
                const double a = cpu.fpr[fra], b = cpu.fpr[frb];
                if (std::isnan(a) || std::isnan(b)) cpu.setCrField(bf, false, false, false, true);
                else cpu.setCrField(bf, a < b, a > b, a == b, false);
                break;
            }
            case 12: cpu.fpr[frt] = static_cast<double>(static_cast<float>(cpu.fpr[frb])); break; // frsp
            case 18: cpu.fpr[frt] = cpu.fpr[fra] / cpu.fpr[frb]; break; // fdiv
            case 20: cpu.fpr[frt] = cpu.fpr[fra] - cpu.fpr[frb]; break; // fsub
            case 21: cpu.fpr[frt] = cpu.fpr[fra] + cpu.fpr[frb]; break; // fadd
            case 40: cpu.fpr[frt] = -cpu.fpr[frb]; break; // fneg
            case 72: cpu.fpr[frt] = cpu.fpr[frb]; break; // fmr
            case 264: cpu.fpr[frt] = std::fabs(cpu.fpr[frb]); break; // fabs
            default:
                return fault(count, currentPc, insn, StopReason::UnsupportedInstruction,
                             "unsupported opcode 63 XO=" + std::to_string(xo));
            }
            break;
        }
        default:
            return fault(count, currentPc, insn, StopReason::UnsupportedInstruction,
                         "unsupported primary opcode=" + std::to_string(opcode));
        }
    }
    return {StopReason::InstructionLimit, config.instructionLimit, cpu.pc, 0,
            "instruction limit reached"};
}

std::string BuiltinInterpreter::disassemble(std::uint32_t, std::uint32_t insn) {
    std::ostringstream out;
    const unsigned opcode = insn >> 26U;
    const unsigned rt = (insn >> 21U) & 31U;
    const unsigned ra = (insn >> 16U) & 31U;
    const unsigned rb = (insn >> 11U) & 31U;
    const auto simm = signExtend16(insn);
    switch (opcode) {
    case 14: out << "addi r" << rt << ",r" << ra << ',' << simm; break;
    case 15: out << "addis r" << rt << ",r" << ra << ',' << simm; break;
    case 18: out << (((insn & 1U) != 0) ? "bl" : "b"); break;
    case 24: out << "ori r" << ra << ",r" << rt << ",0x" << std::hex << (insn & 0xffffU); break;
    case 32: out << "lwz r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 36: out << "stw r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 37: out << "stwu r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 48: out << "lfs f" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 50: out << "lfd f" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 52: out << "stfs f" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 54: out << "stfd f" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 59: out << "fp59 xo=" << ((insn >> 1U) & 31U) << " f" << rt << ",f" << ra << ",f" << rb; break;
    case 63: out << "fp63 xo=" << ((insn >> 1U) & 0x3ffU) << " f" << rt << ",f" << ra << ",f" << rb; break;
    case 31: out << "op31 xo=" << ((insn >> 1U) & 0x3ffU); break;
    case 19: out << "op19 xo=" << ((insn >> 1U) & 0x3ffU); break;
    default: out << "op" << opcode;
    }
    return out.str();
}

} // namespace ppclab::ppc
