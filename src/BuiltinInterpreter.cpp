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

std::uint16_t byteSwap16(std::uint16_t v) noexcept {
    return static_cast<std::uint16_t>((v >> 8U) | (v << 8U));
}

std::uint32_t byteSwap32(std::uint32_t v) noexcept {
    return ((v & 0x000000ffU) << 24U) | ((v & 0x0000ff00U) << 8U) |
           ((v & 0x00ff0000U) >> 8U) | ((v & 0xff000000U) >> 24U);
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

void updateCr1FromFpscr(CpuState& cpu) noexcept {
    const std::uint32_t nibble = (cpu.fpscr >> 28U) & 0xfU;
    cpu.cr = (cpu.cr & ~(0xfU << 24U)) | (nibble << 24U);
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

void setCrBit(CpuState& cpu, unsigned bi, bool value) noexcept {
    if (bi >= 32) return;
    const std::uint32_t mask = 1U << (31U - bi);
    if (value) cpu.cr |= mask;
    else cpu.cr &= ~mask;
}

void setOverflow(CpuState& cpu, bool overflow) noexcept {
    constexpr std::uint32_t kXerSo = 0x80000000U;
    constexpr std::uint32_t kXerOv = 0x40000000U;
    if (overflow) cpu.xer |= kXerSo | kXerOv;
    else cpu.xer &= ~kXerOv;
}

bool addOverflow(std::uint32_t a, std::uint32_t b, std::uint32_t result) noexcept {
    return ((~(a ^ b) & (a ^ result)) & 0x80000000U) != 0;
}

bool subOverflow(std::uint32_t minuend, std::uint32_t subtrahend, std::uint32_t result) noexcept {
    return (((minuend ^ subtrahend) & (minuend ^ result)) & 0x80000000U) != 0;
}

bool trapCondition(unsigned to, std::uint32_t a, std::uint32_t b) noexcept {
    const auto sa = static_cast<std::int32_t>(a);
    const auto sb = static_cast<std::int32_t>(b);
    return ((to & 0x10U) && sa < sb) ||
           ((to & 0x08U) && sa > sb) ||
           ((to & 0x04U) && a == b) ||
           ((to & 0x02U) && a < b) ||
           ((to & 0x01U) && a > b);
}

const SystemCallStubBinding* findSystemCallStub(const ExecutionConfig& config,
                                                 std::uint32_t number) noexcept {
    for (const auto& binding : config.systemCallStubs)
        if (binding.number == number) return &binding;
    return nullptr;
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

std::string symbolize(std::uint32_t pc, const std::vector<ImageSymbol>* symbols) {
    if (!symbols) return {};
    const ImageSymbol* best = nullptr;
    for (const auto& symbol : *symbols) {
        if (!symbol.defined || symbol.name.empty() || symbol.value > pc) continue;
        if (!best || symbol.value > best->value) best = &symbol;
    }
    if (!best) return {};
    const auto delta = pc - best->value;
    if (best->size != 0 && delta >= best->size) return {};
    std::ostringstream out;
    out << best->name;
    if (delta) out << "+0x" << std::hex << delta;
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
            const auto symbol = symbolize(currentPc, config.traceSymbols);
            std::cerr << hex32(currentPc) << "  " << hex32(insn) << "  "
                      << disassemble(currentPc, insn);
            if (!symbol.empty()) std::cerr << "  [" << symbol << "]";
            std::cerr << '\n';
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
        case 3: { // twi
            const unsigned to = rt;
            if (trapCondition(to, cpu.gpr[ra], static_cast<std::uint32_t>(simm)) &&
                !config.ignoreTraps) {
                return fault(count, currentPc, insn, StopReason::Trap,
                             "twi trap TO=" + std::to_string(to));
            }
            break;
        }
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
        case 17: { // sc
            const std::uint32_t number = cpu.gpr[0];
            if (const auto* binding = findSystemCallStub(config, number)) {
                cpu.gpr[3] = binding->returnValue;
                break;
            }
            if (config.defaultSystemCallReturn) {
                cpu.gpr[3] = *config.defaultSystemCallReturn;
                break;
            }
            return fault(count, currentPc, insn, StopReason::SystemCall,
                         "system call r0=" + std::to_string(number));
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
            } else if (xo == 0U) { // mcrf
                const unsigned bf = (insn >> 23U) & 7U;
                const unsigned bfa = (insn >> 18U) & 7U;
                const unsigned srcShift = 28U - bfa * 4U;
                const unsigned dstShift = 28U - bf * 4U;
                const std::uint32_t nibble = (cpu.cr >> srcShift) & 0xfU;
                cpu.cr = (cpu.cr & ~(0xfU << dstShift)) | (nibble << dstShift);
            } else if (xo == 33U || xo == 129U || xo == 193U || xo == 225U ||
                       xo == 257U || xo == 289U || xo == 417U || xo == 449U) {
                const bool a = cpu.crBit(ra);
                const bool b = cpu.crBit(rb);
                bool value = false;
                if (xo == 33U) value = !(a || b);          // crnor
                else if (xo == 129U) value = a && !b;     // crandc
                else if (xo == 193U) value = a != b;      // crxor
                else if (xo == 225U) value = !(a && b);   // crnand
                else if (xo == 257U) value = a && b;      // crand
                else if (xo == 289U) value = a == b;      // creqv
                else if (xo == 417U) value = a || !b;     // crorc
                else value = a || b;                      // cror
                setCrBit(cpu, rt, value);
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
        case 23: { // rlwnm
            const unsigned mb = (insn >> 6U) & 31U;
            const unsigned me = (insn >> 1U) & 31U;
            cpu.gpr[ra] = rotl32(cpu.gpr[rt], cpu.gpr[rb] & 31U) & ppcMask(mb, me);
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
            case 4: { // tw
                const unsigned to = rt;
                if (trapCondition(to, cpu.gpr[ra], cpu.gpr[rb]) && !config.ignoreTraps)
                    return fault(count, currentPc, insn, StopReason::Trap,
                                 "tw trap TO=" + std::to_string(to));
                break;
            }
            case 11: { // mulhwu
                const std::uint64_t product = static_cast<std::uint64_t>(cpu.gpr[ra]) * cpu.gpr[rb];
                cpu.gpr[rt] = static_cast<std::uint32_t>(product >> 32U);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 20: { // lwarx
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if ((ea & 3U) != 0)
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "lwarx alignment fault");
                if (!memory.read32(ea, cpu.gpr[rt]))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "lwarx failed");
                cpu.reservationAddress = ea;
                cpu.reservationValid = true;
                break;
            }
            case 8:   // subfc
            case 520: { // subfco
                const std::uint64_t wide = static_cast<std::uint64_t>(cpu.gpr[rb]) +
                                           static_cast<std::uint64_t>(~cpu.gpr[ra]) + 1ULL;
                cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
                setCarry(cpu, (wide >> 32U) != 0);
                if (xo == 520U) setOverflow(cpu, subOverflow(cpu.gpr[rb], cpu.gpr[ra], cpu.gpr[rt]));
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 40:  // subf
            case 552: { // subfo
                cpu.gpr[rt] = cpu.gpr[rb] - cpu.gpr[ra];
                if (xo == 552U) setOverflow(cpu, subOverflow(cpu.gpr[rb], cpu.gpr[ra], cpu.gpr[rt]));
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 10:  // addc
            case 522: { // addco
                const std::uint64_t wide = static_cast<std::uint64_t>(cpu.gpr[ra]) + cpu.gpr[rb];
                cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
                setCarry(cpu, (wide >> 32U) != 0);
                if (xo == 522U) setOverflow(cpu, addOverflow(cpu.gpr[ra], cpu.gpr[rb], cpu.gpr[rt]));
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 266:  // add
            case 778: { // addo
                cpu.gpr[rt] = cpu.gpr[ra] + cpu.gpr[rb];
                if (xo == 778U) setOverflow(cpu, addOverflow(cpu.gpr[ra], cpu.gpr[rb], cpu.gpr[rt]));
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
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
            case 55: { // lwzux
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if (!memory.read32(ea, cpu.gpr[rt]))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "lwzux failed");
                cpu.gpr[ra] = ea;
                break;
            }
            case 60: // andc
                cpu.gpr[ra] = cpu.gpr[rt] & ~cpu.gpr[rb];
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            case 75: { // mulhw
                const std::int64_t product =
                    static_cast<std::int64_t>(static_cast<std::int32_t>(cpu.gpr[ra])) *
                    static_cast<std::int64_t>(static_cast<std::int32_t>(cpu.gpr[rb]));
                cpu.gpr[rt] = static_cast<std::uint32_t>(static_cast<std::uint64_t>(product) >> 32U);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 54:  // dcbst
            case 86:  // dcbf
            case 246: // dcbtst
            case 278: // dcbt
                break; // cache hints are deterministic no-ops in user-space research mode
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
            case 119: { // lbzux
                const auto ea = effectiveAddressX(cpu, ra, rb);
                std::uint8_t value = 0;
                if (!memory.read8(ea, value))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "lbzux failed");
                cpu.gpr[rt] = value;
                cpu.gpr[ra] = ea;
                break;
            }
            case 124: // nor
                cpu.gpr[ra] = ~(cpu.gpr[rt] | cpu.gpr[rb]);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            case 150: { // stwcx.
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if ((ea & 3U) != 0)
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "stwcx. alignment fault");
                const bool success = cpu.reservationValid && cpu.reservationAddress == ea;
                if (success && !memory.write32(ea, cpu.gpr[rt]))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "stwcx. failed");
                cpu.reservationValid = false;
                cpu.setCrField(0, false, false, success, (cpu.xer & 0x80000000U) != 0);
                break;
            }
            case 183: { // stwux
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if (!memory.write32(ea, cpu.gpr[rt]))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "stwux failed");
                cpu.gpr[ra] = ea;
                break;
            }
            case 104:  // neg
            case 616: { // nego
                cpu.gpr[rt] = 0U - cpu.gpr[ra];
                if (xo == 616U) setOverflow(cpu, cpu.gpr[ra] == 0x80000000U);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 136:  // subfe
            case 648: { // subfeo
                const bool carryIn = carrySet(cpu);
                const std::uint64_t wide = static_cast<std::uint64_t>(cpu.gpr[rb]) +
                                           static_cast<std::uint64_t>(~cpu.gpr[ra]) +
                                           static_cast<std::uint64_t>(carryIn);
                cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
                setCarry(cpu, (wide >> 32U) != 0);
                if (xo == 648U) {
                    const std::int64_t math = static_cast<std::int64_t>(static_cast<std::int32_t>(cpu.gpr[rb])) -
                                              static_cast<std::int64_t>(static_cast<std::int32_t>(cpu.gpr[ra])) +
                                              (carryIn ? 0 : -1);
                    setOverflow(cpu, math < std::numeric_limits<std::int32_t>::min() ||
                                     math > std::numeric_limits<std::int32_t>::max());
                }
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 138:  // adde
            case 650: { // addeo
                const bool carryIn = carrySet(cpu);
                const std::uint64_t wide = static_cast<std::uint64_t>(cpu.gpr[ra]) +
                                           cpu.gpr[rb] + static_cast<std::uint64_t>(carryIn);
                cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
                setCarry(cpu, (wide >> 32U) != 0);
                if (xo == 650U) {
                    const std::int64_t math = static_cast<std::int64_t>(static_cast<std::int32_t>(cpu.gpr[ra])) +
                                              static_cast<std::int64_t>(static_cast<std::int32_t>(cpu.gpr[rb])) +
                                              (carryIn ? 1 : 0);
                    setOverflow(cpu, math < std::numeric_limits<std::int32_t>::min() ||
                                     math > std::numeric_limits<std::int32_t>::max());
                }
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
            case 232:  // subfme
            case 744: { // subfmeo
                const bool carryIn = carrySet(cpu);
                const std::uint64_t wide = static_cast<std::uint64_t>(~cpu.gpr[ra]) +
                                           static_cast<std::uint64_t>(carryIn) + 0xffffffffULL;
                cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
                setCarry(cpu, (wide >> 32U) != 0);
                if (xo == 744U) {
                    const std::int64_t math = -static_cast<std::int64_t>(static_cast<std::int32_t>(cpu.gpr[ra])) +
                                              (carryIn ? 1 : 0) - 2;
                    setOverflow(cpu, math < std::numeric_limits<std::int32_t>::min() ||
                                     math > std::numeric_limits<std::int32_t>::max());
                }
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 234:  // addme
            case 746: { // addmeo
                const bool carryIn = carrySet(cpu);
                const std::uint64_t wide = static_cast<std::uint64_t>(cpu.gpr[ra]) +
                                           static_cast<std::uint64_t>(carryIn) + 0xffffffffULL;
                cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
                setCarry(cpu, (wide >> 32U) != 0);
                if (xo == 746U) {
                    const std::int64_t math = static_cast<std::int64_t>(static_cast<std::int32_t>(cpu.gpr[ra])) +
                                              (carryIn ? 1 : 0) - 1;
                    setOverflow(cpu, math < std::numeric_limits<std::int32_t>::min() ||
                                     math > std::numeric_limits<std::int32_t>::max());
                }
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 200:  // subfze
            case 712: { // subfzeo
                const bool carryIn = carrySet(cpu);
                const std::uint64_t wide = static_cast<std::uint64_t>(~cpu.gpr[ra]) +
                                           static_cast<std::uint64_t>(carryIn);
                cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
                setCarry(cpu, (wide >> 32U) != 0);
                if (xo == 712U) {
                    const std::int64_t math = -static_cast<std::int64_t>(static_cast<std::int32_t>(cpu.gpr[ra])) +
                                              (carryIn ? 1 : 0) - 1;
                    setOverflow(cpu, math < std::numeric_limits<std::int32_t>::min() ||
                                     math > std::numeric_limits<std::int32_t>::max());
                }
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 202:  // addze
            case 714: { // addzeo
                const bool carryIn = carrySet(cpu);
                const std::uint64_t wide = static_cast<std::uint64_t>(cpu.gpr[ra]) +
                                           static_cast<std::uint64_t>(carryIn);
                cpu.gpr[rt] = static_cast<std::uint32_t>(wide);
                setCarry(cpu, (wide >> 32U) != 0);
                if (xo == 714U) {
                    const std::int64_t math = static_cast<std::int64_t>(static_cast<std::int32_t>(cpu.gpr[ra])) +
                                              (carryIn ? 1 : 0);
                    setOverflow(cpu, math < std::numeric_limits<std::int32_t>::min() ||
                                     math > std::numeric_limits<std::int32_t>::max());
                }
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 215: { // stbx
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if (!memory.write8(ea, static_cast<std::uint8_t>(cpu.gpr[rt])))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "stbx failed");
                break;
            }
            case 247: { // stbux
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if (!memory.write8(ea, static_cast<std::uint8_t>(cpu.gpr[rt])))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "stbux failed");
                cpu.gpr[ra] = ea;
                break;
            }
            case 235:  // mullw
            case 747: { // mullwo
                const std::int64_t product =
                    static_cast<std::int64_t>(static_cast<std::int32_t>(cpu.gpr[ra])) *
                    static_cast<std::int64_t>(static_cast<std::int32_t>(cpu.gpr[rb]));
                cpu.gpr[rt] = static_cast<std::uint32_t>(product);
                if (xo == 747U) setOverflow(cpu, product < std::numeric_limits<std::int32_t>::min() ||
                                                   product > std::numeric_limits<std::int32_t>::max());
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 279: { // lhzx
                std::uint16_t value = 0;
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if (!memory.read16(ea, value))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "lhzx failed");
                cpu.gpr[rt] = value;
                break;
            }
            case 284: // eqv
                cpu.gpr[ra] = ~(cpu.gpr[rt] ^ cpu.gpr[rb]);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            case 331: { // lhzux
                const auto ea = effectiveAddressX(cpu, ra, rb);
                std::uint16_t value = 0;
                if (!memory.read16(ea, value))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "lhzux failed");
                cpu.gpr[rt] = value;
                cpu.gpr[ra] = ea;
                break;
            }
            case 343:
            case 375: { // lhax / lhaux
                const auto ea = effectiveAddressX(cpu, ra, rb);
                std::uint16_t value = 0;
                if (!memory.read16(ea, value))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "lhax failed");
                cpu.gpr[rt] = static_cast<std::uint32_t>(static_cast<std::int32_t>(static_cast<std::int16_t>(value)));
                if (xo == 375U) cpu.gpr[ra] = ea;
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
            case 412: // orc
                cpu.gpr[ra] = cpu.gpr[rt] | ~cpu.gpr[rb];
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            case 439: { // sthux
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if (!memory.write16(ea, static_cast<std::uint16_t>(cpu.gpr[rt])))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "sthux failed");
                cpu.gpr[ra] = ea;
                break;
            }
            case 444: // or
                cpu.gpr[ra] = cpu.gpr[rt] | cpu.gpr[rb];
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            case 476: // nand
                cpu.gpr[ra] = ~(cpu.gpr[rt] & cpu.gpr[rb]);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            case 459:  // divwu
            case 971: { // divwuo
                const bool invalid = cpu.gpr[rb] == 0U;
                cpu.gpr[rt] = invalid ? 0U : cpu.gpr[ra] / cpu.gpr[rb];
                if (xo == 971U) setOverflow(cpu, invalid);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 491:  // divw
            case 1003: { // divwo
                const auto divisor = static_cast<std::int32_t>(cpu.gpr[rb]);
                const auto dividend = static_cast<std::int32_t>(cpu.gpr[ra]);
                const bool invalid = divisor == 0 ||
                    (dividend == std::numeric_limits<std::int32_t>::min() && divisor == -1);
                if (invalid) cpu.gpr[rt] = 0U;
                else cpu.gpr[rt] = static_cast<std::uint32_t>(dividend / divisor);
                if (xo == 1003U) setOverflow(cpu, invalid);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[rt]));
                break;
            }
            case 534: { // lwbrx
                const auto ea = effectiveAddressX(cpu, ra, rb);
                std::uint32_t value = 0;
                if (!memory.read32(ea, value))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "lwbrx failed");
                cpu.gpr[rt] = byteSwap32(value);
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
            case 662: { // stwbrx
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if (!memory.write32(ea, byteSwap32(cpu.gpr[rt])))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "stwbrx failed");
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
            case 512: { // mcrxr
                const unsigned bf = (insn >> 23U) & 7U;
                const bool so = (cpu.xer & 0x80000000U) != 0;
                const bool ov = (cpu.xer & 0x40000000U) != 0;
                const bool ca = (cpu.xer & 0x20000000U) != 0;
                const unsigned shift = 28U - bf * 4U;
                const std::uint32_t nibble = (so ? 8U : 0U) | (ov ? 4U : 0U) | (ca ? 2U : 0U);
                cpu.cr = (cpu.cr & ~(0xfU << shift)) | (nibble << shift);
                cpu.xer &= ~0xe0000000U;
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
            case 790: { // lhbrx
                const auto ea = effectiveAddressX(cpu, ra, rb);
                std::uint16_t value = 0;
                if (!memory.read16(ea, value))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "lhbrx failed");
                cpu.gpr[rt] = byteSwap16(value);
                break;
            }
            case 792: { // sraw
                const unsigned shift = cpu.gpr[rb] & 0x3fU;
                const auto source = static_cast<std::int32_t>(cpu.gpr[rt]);
                if (shift >= 32U) {
                    cpu.gpr[ra] = source < 0 ? 0xffffffffU : 0U;
                    setCarry(cpu, source < 0 && cpu.gpr[rt] != 0U);
                } else if (shift == 0U) {
                    cpu.gpr[ra] = cpu.gpr[rt];
                    setCarry(cpu, false);
                } else {
                    cpu.gpr[ra] = static_cast<std::uint32_t>(source >> shift);
                    const std::uint32_t lostMask = (1U << shift) - 1U;
                    setCarry(cpu, source < 0 && (cpu.gpr[rt] & lostMask) != 0U);
                }
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            }
            case 824: { // srawi
                const unsigned sh = rb;
                const auto source = static_cast<std::int32_t>(cpu.gpr[rt]);
                cpu.gpr[ra] = static_cast<std::uint32_t>(source >> sh);
                const std::uint32_t lostMask = sh == 0 ? 0U : ((1U << sh) - 1U);
                setCarry(cpu, source < 0 && (cpu.gpr[rt] & lostMask) != 0U);
                if (rc) updateCr0(cpu, static_cast<std::int32_t>(cpu.gpr[ra]));
                break;
            }
            case 854: // eieio
                break;
            case 918: { // sthbrx
                const auto ea = effectiveAddressX(cpu, ra, rb);
                if (!memory.write16(ea, byteSwap16(static_cast<std::uint16_t>(cpu.gpr[rt]))))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "sthbrx failed");
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
            case 982: // icbi
                break;
            case 983: { // stfiwx
                const auto ea = effectiveAddressX(cpu, ra, rb);
                const auto raw = std::bit_cast<std::uint64_t>(cpu.fpr[rt]);
                if (!memory.write32(ea, static_cast<std::uint32_t>(raw)))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "stfiwx failed");
                break;
            }
            case 1014: { // dcbz -- model the architectural zeroing effect with a 32-byte line
                const auto ea = effectiveAddressX(cpu, ra, rb) & ~31U;
                std::array<std::uint8_t, 32> zeros{};
                if (!memory.writeBytes(ea, zeros))
                    return fault(count, currentPc, insn, StopReason::MemoryFault, "dcbz failed");
                break;
            }
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
            case 22: result = singleResult(std::sqrt(cpu.fpr[frb])); break; // fsqrts
            case 24: result = singleResult(1.0 / cpu.fpr[frb]); break; // fres (deterministic full-precision estimate)
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
            if (rc) updateCr1FromFpscr(cpu);
            break;
        }
        case 63: {
            const unsigned frt = rt, fra = ra, frb = rb, frc = (insn >> 6U) & 31U;
            const unsigned xo5 = (insn >> 1U) & 31U;
            if (xo5 == 22U || xo5 == 23U || xo5 == 25U || xo5 == 26U ||
                (xo5 >= 28U && xo5 <= 31U)) {
                double result = 0.0;
                if (xo5 == 22U) result = std::sqrt(cpu.fpr[frb]);
                else if (xo5 == 23U) result = (!std::isnan(cpu.fpr[fra]) && cpu.fpr[fra] >= 0.0)
                                                ? cpu.fpr[frc] : cpu.fpr[frb];
                else if (xo5 == 25U) result = cpu.fpr[fra] * cpu.fpr[frc];
                else if (xo5 == 26U) result = 1.0 / std::sqrt(cpu.fpr[frb]);
                else if (xo5 == 28U) result = std::fma(cpu.fpr[fra], cpu.fpr[frc], -cpu.fpr[frb]);
                else if (xo5 == 29U) result = std::fma(cpu.fpr[fra], cpu.fpr[frc], cpu.fpr[frb]);
                else if (xo5 == 30U) result = -std::fma(cpu.fpr[fra], cpu.fpr[frc], -cpu.fpr[frb]);
                else result = -std::fma(cpu.fpr[fra], cpu.fpr[frc], cpu.fpr[frb]);
                cpu.fpr[frt] = result;
                if (rc) updateCr1FromFpscr(cpu);
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
            case 12:
                cpu.fpr[frt] = static_cast<double>(static_cast<float>(cpu.fpr[frb])); // frsp
                if (rc) updateCr1FromFpscr(cpu);
                break;
            case 14: // fctiw
            case 15: { // fctiwz
                double value = cpu.fpr[frb];
                double rounded = value;
                if (xo == 15U) rounded = std::trunc(value);
                else {
                    switch (cpu.fpscr & 3U) {
                    case 1: rounded = std::trunc(value); break;
                    case 2: rounded = std::ceil(value); break;
                    case 3: rounded = std::floor(value); break;
                    default: rounded = std::nearbyint(value); break;
                    }
                }
                std::int32_t integer = 0;
                if (std::isnan(rounded)) integer = std::numeric_limits<std::int32_t>::min();
                else if (rounded > static_cast<double>(std::numeric_limits<std::int32_t>::max()))
                    integer = std::numeric_limits<std::int32_t>::max();
                else if (rounded < static_cast<double>(std::numeric_limits<std::int32_t>::min()))
                    integer = std::numeric_limits<std::int32_t>::min();
                else integer = static_cast<std::int32_t>(rounded);
                const std::uint64_t raw = 0xffffffff00000000ULL | static_cast<std::uint32_t>(integer);
                cpu.fpr[frt] = std::bit_cast<double>(raw);
                if (rc) updateCr1FromFpscr(cpu);
                break;
            }
            case 18: cpu.fpr[frt] = cpu.fpr[fra] / cpu.fpr[frb]; if (rc) updateCr1FromFpscr(cpu); break; // fdiv
            case 20: cpu.fpr[frt] = cpu.fpr[fra] - cpu.fpr[frb]; if (rc) updateCr1FromFpscr(cpu); break; // fsub
            case 21: cpu.fpr[frt] = cpu.fpr[fra] + cpu.fpr[frb]; if (rc) updateCr1FromFpscr(cpu); break; // fadd
            case 40: cpu.fpr[frt] = -cpu.fpr[frb]; if (rc) updateCr1FromFpscr(cpu); break; // fneg
            case 72: cpu.fpr[frt] = cpu.fpr[frb]; if (rc) updateCr1FromFpscr(cpu); break; // fmr
            case 136: cpu.fpr[frt] = -std::fabs(cpu.fpr[frb]); if (rc) updateCr1FromFpscr(cpu); break; // fnabs
            case 264: cpu.fpr[frt] = std::fabs(cpu.fpr[frb]); if (rc) updateCr1FromFpscr(cpu); break; // fabs
            case 583: { // mffs
                const std::uint64_t raw = 0xffffffff00000000ULL | cpu.fpscr;
                cpu.fpr[frt] = std::bit_cast<double>(raw);
                if (rc) updateCr1FromFpscr(cpu);
                break;
            }
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

std::string BuiltinInterpreter::disassemble(std::uint32_t pc, std::uint32_t insn) {
    std::ostringstream out;
    const unsigned opcode = insn >> 26U;
    const unsigned rt = (insn >> 21U) & 31U;
    const unsigned ra = (insn >> 16U) & 31U;
    const unsigned rb = (insn >> 11U) & 31U;
    const auto simm = signExtend16(insn);
    const auto uimm = insn & 0xffffU;
    const bool rc = (insn & 1U) != 0;
    const auto record = [rc]() { return rc ? "." : ""; };
    const auto target26 = [&]() {
        const auto disp = signExtend26(insn);
        return (insn & 2U) != 0 ? static_cast<std::uint32_t>(disp)
                                : pc + static_cast<std::uint32_t>(disp);
    };
    const auto target14 = [&]() {
        const auto disp = signExtend14Shift2(insn);
        return (insn & 2U) != 0 ? static_cast<std::uint32_t>(disp)
                                : pc + static_cast<std::uint32_t>(disp);
    };
    const auto hexTarget = [](std::uint32_t value) {
        std::ostringstream text;
        text << "0x" << std::hex << std::setw(8) << std::setfill('0') << value;
        return text.str();
    };

    switch (opcode) {
    case 3:
        out << "twi " << rt << ",r" << ra << ',' << simm;
        break;
    case 7: out << "mulli r" << rt << ",r" << ra << ',' << simm; break;
    case 8: out << "subfic r" << rt << ",r" << ra << ',' << simm; break;
    case 10: out << "cmplwi cr" << ((insn >> 23U) & 7U) << ",r" << ra << ',' << uimm; break;
    case 11: out << "cmpwi cr" << ((insn >> 23U) & 7U) << ",r" << ra << ',' << simm; break;
    case 12: out << "addic r" << rt << ",r" << ra << ',' << simm; break;
    case 13: out << "addic. r" << rt << ",r" << ra << ',' << simm; break;
    case 14:
        if (ra == 0) out << "li r" << rt << ',' << simm;
        else out << "addi r" << rt << ",r" << ra << ',' << simm;
        break;
    case 15:
        if (ra == 0) out << "lis r" << rt << ',' << simm;
        else out << "addis r" << rt << ",r" << ra << ',' << simm;
        break;
    case 16:
        out << (((insn & 1U) != 0) ? "bcl " : "bc ")
            << ((insn >> 21U) & 31U) << ',' << ((insn >> 16U) & 31U)
            << ',' << hexTarget(target14());
        break;
    case 17:
        out << "sc";
        break;
    case 18:
        out << (((insn & 1U) != 0) ? "bl " : "b ") << hexTarget(target26());
        break;
    case 19: {
        const unsigned xo = (insn >> 1U) & 0x3ffU;
        const unsigned bo = (insn >> 21U) & 31U;
        const unsigned bi = (insn >> 16U) & 31U;
        const bool lk = (insn & 1U) != 0;
        if (xo == 16U && bo == 20U && bi == 0U && !lk) out << "blr";
        else if (xo == 528U && bo == 20U && bi == 0U && !lk) out << "bctr";
        else if (xo == 16U) out << (lk ? "bclrl " : "bclr ") << bo << ',' << bi;
        else if (xo == 528U) out << (lk ? "bcctrl " : "bcctr ") << bo << ',' << bi;
        else if (xo == 0U) out << "mcrf cr" << ((insn >> 23U) & 7U) << ",cr" << ((insn >> 18U) & 7U);
        else if (xo == 33U) out << "crnor " << rt << ',' << ra << ',' << rb;
        else if (xo == 129U) out << "crandc " << rt << ',' << ra << ',' << rb;
        else if (xo == 193U) out << "crxor " << rt << ',' << ra << ',' << rb;
        else if (xo == 225U) out << "crnand " << rt << ',' << ra << ',' << rb;
        else if (xo == 257U) out << "crand " << rt << ',' << ra << ',' << rb;
        else if (xo == 289U) out << "creqv " << rt << ',' << ra << ',' << rb;
        else if (xo == 417U) out << "crorc " << rt << ',' << ra << ',' << rb;
        else if (xo == 449U) out << "cror " << rt << ',' << ra << ',' << rb;
        else if (xo == 150U) out << "isync";
        else out << ".long " << hexTarget(insn) << "  # opcode19 xo=" << xo;
        break;
    }
    case 20:
        out << "rlwimi" << record() << " r" << ra << ",r" << rt << ','
            << ((insn >> 11U) & 31U) << ',' << ((insn >> 6U) & 31U) << ','
            << ((insn >> 1U) & 31U);
        break;
    case 21:
        out << "rlwinm" << record() << " r" << ra << ",r" << rt << ','
            << ((insn >> 11U) & 31U) << ',' << ((insn >> 6U) & 31U) << ','
            << ((insn >> 1U) & 31U);
        break;
    case 23:
        out << "rlwnm" << record() << " r" << ra << ",r" << rt << ",r" << rb << ','
            << ((insn >> 6U) & 31U) << ',' << ((insn >> 1U) & 31U);
        break;
    case 24:
        if (rt == 0 && ra == 0 && uimm == 0) out << "nop";
        else out << "ori r" << ra << ",r" << rt << ",0x" << std::hex << uimm;
        break;
    case 25: out << "oris r" << ra << ",r" << rt << ",0x" << std::hex << uimm; break;
    case 26: out << "xori r" << ra << ",r" << rt << ",0x" << std::hex << uimm; break;
    case 27: out << "xoris r" << ra << ",r" << rt << ",0x" << std::hex << uimm; break;
    case 28: out << "andi. r" << ra << ",r" << rt << ",0x" << std::hex << uimm; break;
    case 29: out << "andis. r" << ra << ",r" << rt << ",0x" << std::hex << uimm; break;
    case 31: {
        const unsigned xo = (insn >> 1U) & 0x3ffU;
        switch (xo) {
        case 0: out << "cmpw cr" << ((insn >> 23U) & 7U) << ",r" << ra << ",r" << rb; break;
        case 4: out << "tw " << rt << ",r" << ra << ",r" << rb; break;
        case 8: out << "subfc" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 520: out << "subfco" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 11: out << "mulhwu" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 20: out << "lwarx r" << rt << ",r" << ra << ",r" << rb; break;
        case 10: out << "addc" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 522: out << "addco" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 19: out << "mfcr r" << rt; break;
        case 23: out << "lwzx r" << rt << ",r" << ra << ",r" << rb; break;
        case 55: out << "lwzux r" << rt << ",r" << ra << ",r" << rb; break;
        case 54: out << "dcbst r" << ra << ",r" << rb; break;
        case 60: out << "andc" << record() << " r" << ra << ",r" << rt << ",r" << rb; break;
        case 75: out << "mulhw" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 86: out << "dcbf r" << ra << ",r" << rb; break;
        case 24: out << "slw" << record() << " r" << ra << ",r" << rt << ",r" << rb; break;
        case 26: out << "cntlzw" << record() << " r" << ra << ",r" << rt; break;
        case 28: out << "and" << record() << " r" << ra << ",r" << rt << ",r" << rb; break;
        case 32: out << "cmplw cr" << ((insn >> 23U) & 7U) << ",r" << ra << ",r" << rb; break;
        case 40: out << "subf" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 87: out << "lbzx r" << rt << ",r" << ra << ",r" << rb; break;
        case 119: out << "lbzux r" << rt << ",r" << ra << ",r" << rb; break;
        case 124: out << "nor" << record() << " r" << ra << ",r" << rt << ",r" << rb; break;
        case 150: out << "stwcx. r" << rt << ",r" << ra << ",r" << rb; break;
        case 104: out << "neg" << record() << " r" << rt << ",r" << ra; break;
        case 616: out << "nego" << record() << " r" << rt << ",r" << ra; break;
        case 136: out << "subfe" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 648: out << "subfeo" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 138: out << "adde" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 650: out << "addeo" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 144: out << "mtcrf 0x" << std::hex << ((insn >> 12U) & 0xffU) << ",r" << rt; break;
        case 151: out << "stwx r" << rt << ",r" << ra << ",r" << rb; break;
        case 183: out << "stwux r" << rt << ",r" << ra << ",r" << rb; break;
        case 200: out << "subfze" << record() << " r" << rt << ",r" << ra; break;
        case 712: out << "subfzeo" << record() << " r" << rt << ",r" << ra; break;
        case 232: out << "subfme" << record() << " r" << rt << ",r" << ra; break;
        case 744: out << "subfmeo" << record() << " r" << rt << ",r" << ra; break;
        case 202: out << "addze" << record() << " r" << rt << ",r" << ra; break;
        case 714: out << "addzeo" << record() << " r" << rt << ",r" << ra; break;
        case 234: out << "addme" << record() << " r" << rt << ",r" << ra; break;
        case 746: out << "addmeo" << record() << " r" << rt << ",r" << ra; break;
        case 215: out << "stbx r" << rt << ",r" << ra << ",r" << rb; break;
        case 247: out << "stbux r" << rt << ",r" << ra << ",r" << rb; break;
        case 246: out << "dcbtst r" << ra << ",r" << rb; break;
        case 235: out << "mullw" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 747: out << "mullwo" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 278: out << "dcbt r" << ra << ",r" << rb; break;
        case 266: out << "add" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 778: out << "addo" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 284: out << "eqv" << record() << " r" << ra << ",r" << rt << ",r" << rb; break;
        case 279: out << "lhzx r" << rt << ",r" << ra << ",r" << rb; break;
        case 331: out << "lhzux r" << rt << ",r" << ra << ",r" << rb; break;
        case 343: out << "lhax r" << rt << ",r" << ra << ",r" << rb; break;
        case 375: out << "lhaux r" << rt << ",r" << ra << ",r" << rb; break;
        case 316: out << "xor" << record() << " r" << ra << ",r" << rt << ",r" << rb; break;
        case 339: out << "mfspr r" << rt << ',' << sprNumber(insn); break;
        case 407: out << "sthx r" << rt << ",r" << ra << ",r" << rb; break;
        case 412: out << "orc" << record() << " r" << ra << ",r" << rt << ",r" << rb; break;
        case 439: out << "sthux r" << rt << ",r" << ra << ",r" << rb; break;
        case 444:
            if (rt == rb) out << "mr r" << ra << ",r" << rt;
            else out << "or" << record() << " r" << ra << ",r" << rt << ",r" << rb;
            break;
        case 459: out << "divwu" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 971: out << "divwuo" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 476: out << "nand" << record() << " r" << ra << ",r" << rt << ",r" << rb; break;
        case 467: out << "mtspr " << sprNumber(insn) << ",r" << rt; break;
        case 491: out << "divw" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 1003: out << "divwo" << record() << " r" << rt << ",r" << ra << ",r" << rb; break;
        case 512: out << "mcrxr cr" << ((insn >> 23U) & 7U); break;
        case 534: out << "lwbrx r" << rt << ",r" << ra << ",r" << rb; break;
        case 535: out << "lfsx f" << rt << ",r" << ra << ",r" << rb; break;
        case 536: out << "srw" << record() << " r" << ra << ",r" << rt << ",r" << rb; break;
        case 662: out << "stwbrx r" << rt << ",r" << ra << ",r" << rb; break;
        case 567: out << "lfsux f" << rt << ",r" << ra << ",r" << rb; break;
        case 598: out << "sync"; break;
        case 790: out << "lhbrx r" << rt << ",r" << ra << ",r" << rb; break;
        case 792: out << "sraw" << record() << " r" << ra << ",r" << rt << ",r" << rb; break;
        case 854: out << "eieio"; break;
        case 918: out << "sthbrx r" << rt << ",r" << ra << ",r" << rb; break;
        case 599: out << "lfdx f" << rt << ",r" << ra << ",r" << rb; break;
        case 631: out << "lfdux f" << rt << ",r" << ra << ",r" << rb; break;
        case 663: out << "stfsx f" << rt << ",r" << ra << ",r" << rb; break;
        case 695: out << "stfsux f" << rt << ",r" << ra << ",r" << rb; break;
        case 727: out << "stfdx f" << rt << ",r" << ra << ",r" << rb; break;
        case 759: out << "stfdux f" << rt << ",r" << ra << ",r" << rb; break;
        case 824: out << "srawi" << record() << " r" << ra << ",r" << rt << ',' << rb; break;
        case 922: out << "extsh" << record() << " r" << ra << ",r" << rt; break;
        case 954: out << "extsb" << record() << " r" << ra << ",r" << rt; break;
        case 982: out << "icbi r" << ra << ",r" << rb; break;
        case 983: out << "stfiwx f" << rt << ",r" << ra << ",r" << rb; break;
        case 1014: out << "dcbz r" << ra << ",r" << rb; break;
        default: out << ".long " << hexTarget(insn) << "  # opcode31 xo=" << xo; break;
        }
        break;
    }
    case 32: out << "lwz r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 33: out << "lwzu r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 34: out << "lbz r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 35: out << "lbzu r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 36: out << "stw r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 37: out << "stwu r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 38: out << "stb r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 39: out << "stbu r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 40: out << "lhz r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 41: out << "lhzu r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 42: out << "lha r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 43: out << "lhau r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 44: out << "sth r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 45: out << "sthu r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 46: out << "lmw r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 47: out << "stmw r" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 48: out << "lfs f" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 49: out << "lfsu f" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 50: out << "lfd f" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 51: out << "lfdu f" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 52: out << "stfs f" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 53: out << "stfsu f" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 54: out << "stfd f" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 55: out << "stfdu f" << rt << ',' << simm << "(r" << ra << ')'; break;
    case 59: {
        const unsigned xo5 = (insn >> 1U) & 31U;
        if (xo5 == 18U) out << "fdivs" << record() << " f" << rt << ",f" << ra << ",f" << rb;
        else if (xo5 == 20U) out << "fsubs" << record() << " f" << rt << ",f" << ra << ",f" << rb;
        else if (xo5 == 21U) out << "fadds" << record() << " f" << rt << ",f" << ra << ",f" << rb;
        else if (xo5 == 22U) out << "fsqrts" << record() << " f" << rt << ",f" << rb;
        else if (xo5 == 24U) out << "fres" << record() << " f" << rt << ",f" << rb;
        else if (xo5 == 25U) out << "fmuls" << record() << " f" << rt << ",f" << ((insn >> 6U) & 31U);
        else out << "fp59 xo=" << xo5 << " f" << rt << ",f" << ra << ",f" << rb;
        break;
    }
    case 63: {
        const unsigned xo = (insn >> 1U) & 0x3ffU;
        switch (xo) {
        case 0: out << "fcmpu cr" << ((insn >> 23U) & 7U) << ",f" << ra << ",f" << rb; break;
        case 12: out << "frsp" << record() << " f" << rt << ",f" << rb; break;
        case 14: out << "fctiw" << record() << " f" << rt << ",f" << rb; break;
        case 15: out << "fctiwz" << record() << " f" << rt << ",f" << rb; break;
        case 18: out << "fdiv f" << rt << ",f" << ra << ",f" << rb; break;
        case 20: out << "fsub f" << rt << ",f" << ra << ",f" << rb; break;
        case 21: out << "fadd" << record() << " f" << rt << ",f" << ra << ",f" << rb; break;
        case 22: out << "fsqrt" << record() << " f" << rt << ",f" << rb; break;
        case 23: out << "fsel" << record() << " f" << rt << ",f" << ra << ",f" << ((insn >> 6U) & 31U) << ",f" << rb; break;
        case 26: out << "frsqrte" << record() << " f" << rt << ",f" << rb; break;
        case 32: out << "fcmpo cr" << ((insn >> 23U) & 7U) << ",f" << ra << ",f" << rb; break;
        case 40: out << "fneg" << record() << " f" << rt << ",f" << rb; break;
        case 72: out << "fmr" << record() << " f" << rt << ",f" << rb; break;
        case 136: out << "fnabs" << record() << " f" << rt << ",f" << rb; break;
        case 264: out << "fabs" << record() << " f" << rt << ",f" << rb; break;
        case 583: out << "mffs" << record() << " f" << rt; break;
        default: out << "fp63 xo=" << xo << " f" << rt << ",f" << ra << ",f" << rb; break;
        }
        break;
    }
    default: out << ".long " << hexTarget(insn) << "  # opcode=" << opcode; break;
    }
    return out.str();
}

} // namespace ppclab::ppc
