// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/UnicornBackend.hpp"
#include "ppclab/ppc/ImportStubs.hpp"

#ifdef PPC_LAB_HAVE_UNICORN
#include <unicorn/unicorn.h>
#include <unicorn/ppc.h>

#include <bit>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <vector>
#endif

namespace ppclab::ppc {

#ifndef PPC_LAB_HAVE_UNICORN
bool UnicornBackend::available() noexcept { return false; }
ExecutionResult UnicornBackend::run(Memory&, CpuState& cpu, const ExecutionConfig&) {
    return {StopReason::BackendError, 0, cpu.pc, 0,
            "Unicorn backend was not compiled; install Unicorn 2.x development files and reconfigure"};
}
#else
namespace {

struct HookContext {
    uc_engine* uc = nullptr;
    const ExecutionConfig* config = nullptr;
    StopReason reason = StopReason::BackendError;
    std::uint64_t instructions = 0;
    std::uint32_t stopPc = 0;
    bool stoppedByHook = false;
};

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
    std::ostringstream out; out << best->name;
    if (delta) out << "+0x" << std::hex << delta;
    return out.str();
}

void codeHook(uc_engine* uc, std::uint64_t address, std::uint32_t size, void* userData) {
    auto& ctx = *static_cast<HookContext*>(userData);
    ++ctx.instructions;
    const auto pc = static_cast<std::uint32_t>(address);
    ctx.stopPc = pc;
    if (pc == ctx.config->returnAddress) {
        ctx.reason = StopReason::Returned;
        ctx.stoppedByHook = true;
        uc_emu_stop(uc);
        return;
    }
    if (pc >= ctx.config->importBase &&
        static_cast<std::uint64_t>(pc) <
            static_cast<std::uint64_t>(ctx.config->importBase) + ctx.config->importSize) {
        ctx.reason = StopReason::ImportTrap;
        ctx.stoppedByHook = true;
        uc_emu_stop(uc);
        return;
    }
    // The clean relocation model represents imported symbols as synthetic
    // 4-byte identities. Classic CFM glue reaches them through r12 then bctr;
    // intercept that boundary before Unicorn follows the zero placeholder CTR.
    std::uint8_t wordBytes[4]{};
    if (size >= 4 && uc_mem_read(uc, address, wordBytes, 4) == UC_ERR_OK) {
        const std::uint32_t word = (static_cast<std::uint32_t>(wordBytes[0]) << 24U) |
                                   (static_cast<std::uint32_t>(wordBytes[1]) << 16U) |
                                   (static_cast<std::uint32_t>(wordBytes[2]) << 8U) |
                                   wordBytes[3];
        const unsigned opcode = word >> 26U;
        const unsigned xo = (word >> 1U) & 0x3ffU;
        if (opcode == 19U && xo == 528U) { // bcctr/bctr
            std::uint32_t r12 = 0;
            std::uint32_t ctr = 0;
            (void)uc_reg_read(uc, UC_PPC_REG_12, &r12);
            (void)uc_reg_read(uc, UC_PPC_REG_CTR, &ctr);
            if (ctr == 0U && r12 >= ctx.config->importBase &&
                static_cast<std::uint64_t>(r12) <
                    static_cast<std::uint64_t>(ctx.config->importBase) + ctx.config->importSize) {
                bool handled = false;
                bool success = true;
                if (const auto* binding = findImportStub(ctx.config->importStubs, r12)) {
                    handled = true;
                    auto readGpr = [&](int reg, std::uint32_t& value) {
                        return uc_reg_read(uc, reg, &value) == UC_ERR_OK;
                    };
                    auto copyBytes = [&](std::uint32_t source, std::uint32_t destination, std::uint32_t count) {
                        if (count > 0x01000000U) return false;
                        if (count == 0) return true;
                        std::vector<std::uint8_t> bytes(count);
                        return uc_mem_read(uc, source, bytes.data(), bytes.size()) == UC_ERR_OK &&
                               uc_mem_write(uc, destination, bytes.data(), bytes.size()) == UC_ERR_OK;
                    };
                    switch (binding->kind) {
                    case ImportStubKind::BlockMoveData: {
                        std::uint32_t source=0,destination=0,count=0;
                        success = readGpr(UC_PPC_REG_3, source) && readGpr(UC_PPC_REG_4, destination) &&
                                  readGpr(UC_PPC_REG_5, count) && copyBytes(source,destination,count);
                        break;
                    }
                    case ImportStubKind::Memcpy:
                    case ImportStubKind::Memmove: {
                        std::uint32_t destination=0,source=0,count=0;
                        success = readGpr(UC_PPC_REG_3, destination) && readGpr(UC_PPC_REG_4, source) &&
                                  readGpr(UC_PPC_REG_5, count) && copyBytes(source,destination,count);
                        if (success) (void)uc_reg_write(uc, UC_PPC_REG_3, &destination);
                        break;
                    }
                    case ImportStubKind::Memset: {
                        std::uint32_t destination=0,value=0,count=0;
                        success = readGpr(UC_PPC_REG_3,destination) && readGpr(UC_PPC_REG_4,value) &&
                                  readGpr(UC_PPC_REG_5,count) && count <= 0x01000000U;
                        if (success && count) {
                            std::vector<std::uint8_t> bytes(count, static_cast<std::uint8_t>(value));
                            success = uc_mem_write(uc,destination,bytes.data(),bytes.size()) == UC_ERR_OK;
                        }
                        if (success) (void)uc_reg_write(uc, UC_PPC_REG_3, &destination);
                        break;
                    }
                    case ImportStubKind::Bzero: {
                        std::uint32_t destination=0,count=0;
                        success = readGpr(UC_PPC_REG_3,destination) && readGpr(UC_PPC_REG_4,count) &&
                                  count <= 0x01000000U;
                        if (success && count) {
                            std::vector<std::uint8_t> bytes(count,0);
                            success = uc_mem_write(uc,destination,bytes.data(),bytes.size()) == UC_ERR_OK;
                        }
                        break;
                    }
                    default: {
                        std::uint64_t raw1=0,raw2=0;
                        (void)uc_reg_read(uc,UC_PPC_REG_FPR1,&raw1);
                        (void)uc_reg_read(uc,UC_PPC_REG_FPR2,&raw2);
                        double a=std::bit_cast<double>(raw1); const double b=std::bit_cast<double>(raw2);
                        switch(binding->kind) {
                        case ImportStubKind::Pow: a=std::pow(a,b); break;
                        case ImportStubKind::Cos: a=std::cos(a); break;
                        case ImportStubKind::Sqrt: a=std::sqrt(a); break;
                        case ImportStubKind::Sin: a=std::sin(a); break;
                        case ImportStubKind::Exp: a=std::exp(a); break;
                        case ImportStubKind::Fabs: a=std::fabs(a); break;
                        case ImportStubKind::Floor: a=std::floor(a); break;
                        case ImportStubKind::Ceil: a=std::ceil(a); break;
                        case ImportStubKind::BlockMoveData:
                        case ImportStubKind::Memcpy:
                        case ImportStubKind::Memmove:
                        case ImportStubKind::Memset:
                        case ImportStubKind::Bzero: break;
                        }
                        raw1=std::bit_cast<std::uint64_t>(a);
                        (void)uc_reg_write(uc,UC_PPC_REG_FPR1,&raw1);
                        break;
                    }
                    }
                }
                if (handled && success) {
                    std::uint32_t lr = 0;
                    (void)uc_reg_read(uc, UC_PPC_REG_LR, &lr);
                    // Let the currently hooked bctr execute, but redirect CTR to
                    // the caller return. This mirrors the builtin tail-call stub.
                    (void)uc_reg_write(uc, UC_PPC_REG_CTR, &lr);
                } else {
                    ctx.reason = success ? StopReason::ImportTrap : StopReason::MemoryFault;
                    ctx.stopPc = r12;
                    ctx.stoppedByHook = true;
                    uc_emu_stop(uc);
                    return;
                }
            }
        }
    }
    if (ctx.config->trace &&
        (!ctx.config->traceRange || ctx.config->traceRange->contains(pc))) {
        std::uint32_t word = 0;
        std::uint8_t b[4]{};
        if (size >= 4 && uc_mem_read(uc, address, b, 4) == UC_ERR_OK) {
            word = (static_cast<std::uint32_t>(b[0]) << 24U) |
                   (static_cast<std::uint32_t>(b[1]) << 16U) |
                   (static_cast<std::uint32_t>(b[2]) << 8U) |
                   b[3];
        }
        const auto symbol = symbolize(pc, ctx.config->traceSymbols);
        std::cerr << hex32(pc) << "  " << hex32(word);
        if (!symbol.empty()) std::cerr << "  [" << symbol << "]";
        std::cerr << '\n';
    }
}

unsigned pageRound(std::size_t size) {
    constexpr unsigned page = 4096;
    return static_cast<unsigned>((size + page - 1U) & ~(page - 1U));
}

std::uint32_t unicornPerms(MemoryPerm perms) {
    std::uint32_t result = 0;
    if (hasPerm(perms, MemoryPerm::Read)) result |= UC_PROT_READ;
    if (hasPerm(perms, MemoryPerm::Write)) result |= UC_PROT_WRITE;
    if (hasPerm(perms, MemoryPerm::Execute)) result |= UC_PROT_EXEC;
    return result;
}

} // namespace

bool UnicornBackend::available() noexcept { return true; }

ExecutionResult UnicornBackend::run(Memory& memory,
                                    CpuState& cpu,
                                    const ExecutionConfig& config) {
    uc_engine* uc = nullptr;
    auto err = uc_open(UC_ARCH_PPC,
                       static_cast<uc_mode>(UC_MODE_PPC32 | UC_MODE_BIG_ENDIAN), &uc);
    if (err != UC_ERR_OK) {
        return {StopReason::BackendError, 0, cpu.pc, 0,
                std::string("uc_open failed: ") + uc_strerror(err)};
    }
    struct Closer { uc_engine* p; ~Closer() { if (p) uc_close(p); } } closer{uc};

    // PowerPC 750/G3 is the initial PPC32-BE compatibility baseline.
    (void)uc_ctl_set_cpu_model(uc, UC_CPU_PPC32_750_V3_0);

    for (const auto& region : memory.regions()) {
        const std::uint64_t mapBase = region.base & ~0xfffULL;
        const std::size_t prefix = region.base - static_cast<std::uint32_t>(mapBase);
        const auto mapSize = pageRound(prefix + region.bytes.size());
        err = uc_mem_map(uc, mapBase, mapSize, unicornPerms(region.perms));
        if (err != UC_ERR_OK) {
            return {StopReason::BackendError, 0, cpu.pc, 0,
                    "uc_mem_map failed for " + region.name + ": " + uc_strerror(err)};
        }
        if (!region.bytes.empty()) {
            err = uc_mem_write(uc, region.base, region.bytes.data(), region.bytes.size());
            if (err != UC_ERR_OK) {
                return {StopReason::BackendError, 0, cpu.pc, 0,
                        "uc_mem_write failed for " + region.name + ": " + uc_strerror(err)};
            }
        }
    }

    for (unsigned i = 0; i < 32; ++i) {
        const int reg = UC_PPC_REG_0 + static_cast<int>(i);
        std::uint32_t value = cpu.gpr[i];
        uc_reg_write(uc, reg, &value);
    }
    for (unsigned i = 0; i < 32; ++i) {
        const int reg = UC_PPC_REG_FPR0 + static_cast<int>(i);
        std::uint64_t value = std::bit_cast<std::uint64_t>(cpu.fpr[i]);
        uc_reg_write(uc, reg, &value);
    }
    uc_reg_write(uc, UC_PPC_REG_PC, &cpu.pc);
    uc_reg_write(uc, UC_PPC_REG_LR, &cpu.lr);
    uc_reg_write(uc, UC_PPC_REG_CTR, &cpu.ctr);
    uc_reg_write(uc, UC_PPC_REG_CR, &cpu.cr);
    uc_reg_write(uc, UC_PPC_REG_XER, &cpu.xer);
    uc_reg_write(uc, UC_PPC_REG_FPSCR, &cpu.fpscr);

    HookContext hookContext{uc, &config};
    uc_hook hook = 0;
    err = uc_hook_add(uc, &hook, UC_HOOK_CODE, reinterpret_cast<void*>(codeHook),
                      &hookContext, 1, 0);
    if (err != UC_ERR_OK) {
        return {StopReason::BackendError, 0, cpu.pc, 0,
                std::string("uc_hook_add failed: ") + uc_strerror(err)};
    }

    err = uc_emu_start(uc, cpu.pc, 0xffffffffULL, 0,
                       static_cast<std::size_t>(config.instructionLimit));

    for (unsigned i = 0; i < 32; ++i) {
        const int reg = UC_PPC_REG_0 + static_cast<int>(i);
        uc_reg_read(uc, reg, &cpu.gpr[i]);
    }
    for (unsigned i = 0; i < 32; ++i) {
        const int reg = UC_PPC_REG_FPR0 + static_cast<int>(i);
        std::uint64_t value = 0;
        uc_reg_read(uc, reg, &value);
        cpu.fpr[i] = std::bit_cast<double>(value);
    }
    uc_reg_read(uc, UC_PPC_REG_PC, &cpu.pc);
    uc_reg_read(uc, UC_PPC_REG_LR, &cpu.lr);
    uc_reg_read(uc, UC_PPC_REG_CTR, &cpu.ctr);
    uc_reg_read(uc, UC_PPC_REG_CR, &cpu.cr);
    uc_reg_read(uc, UC_PPC_REG_XER, &cpu.xer);
    uc_reg_read(uc, UC_PPC_REG_FPSCR, &cpu.fpscr);

    for (auto& region : memory.regions()) {
        if (hasPerm(region.perms, MemoryPerm::Write) && !region.bytes.empty()) {
            (void)uc_mem_read(uc, region.base, region.bytes.data(), region.bytes.size());
        }
    }

    if (hookContext.stoppedByHook) {
        return {hookContext.reason, hookContext.instructions, hookContext.stopPc, 0,
                hookContext.reason == StopReason::Returned
                    ? "returned through harness trampoline"
                    : "entered import trap range at " + hex32(hookContext.stopPc)};
    }
    if (err == UC_ERR_OK && hookContext.instructions >= config.instructionLimit) {
        return {StopReason::InstructionLimit, hookContext.instructions, cpu.pc, 0,
                "instruction limit reached"};
    }
    if (err != UC_ERR_OK) {
        StopReason reason = StopReason::BackendError;
        if (err == UC_ERR_READ_UNMAPPED || err == UC_ERR_WRITE_UNMAPPED ||
            err == UC_ERR_FETCH_UNMAPPED || err == UC_ERR_READ_PROT ||
            err == UC_ERR_WRITE_PROT || err == UC_ERR_FETCH_PROT) {
            reason = StopReason::MemoryFault;
        } else if (err == UC_ERR_INSN_INVALID) {
            reason = StopReason::UnsupportedInstruction;
        }
        return {reason, hookContext.instructions, cpu.pc, 0,
                std::string("Unicorn: ") + uc_strerror(err)};
    }
    return {StopReason::BackendError, hookContext.instructions, cpu.pc, 0,
            "Unicorn stopped without a classified exit"};
}
#endif

} // namespace ppclab::ppc
