// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/Microtests.hpp"

#include "ppclab/ppc/BuiltinInterpreter.hpp"
#include "ppclab/ppc/Cpu.hpp"
#include "ppclab/ppc/Memory.hpp"

#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <sstream>
#include <vector>

namespace ppclab::ppc {
namespace {

constexpr std::uint32_t dForm(unsigned op, unsigned rt, unsigned ra, std::uint16_t imm) {
    return (op << 26U) | (rt << 21U) | (ra << 16U) | imm;
}
constexpr std::uint32_t xForm(unsigned op,
                              unsigned rt,
                              unsigned ra,
                              unsigned rb,
                              unsigned xo,
                              bool rc = false) {
    return (op << 26U) | (rt << 21U) | (ra << 16U) | (rb << 11U) |
           (xo << 1U) | (rc ? 1U : 0U);
}
constexpr std::uint32_t aForm(unsigned op,
                              unsigned frt,
                              unsigned fra,
                              unsigned frb,
                              unsigned frc,
                              unsigned xo,
                              bool rc = false) {
    return (op << 26U) | (frt << 21U) | (fra << 16U) | (frb << 11U) |
           (frc << 6U) | (xo << 1U) | (rc ? 1U : 0U);
}
constexpr std::uint32_t sprForm(unsigned rt, unsigned spr, unsigned xo) {
    const unsigned encoded = ((spr & 0x1fU) << 5U) | ((spr >> 5U) & 0x1fU);
    return (31U << 26U) | (rt << 21U) | (encoded << 11U) | (xo << 1U);
}
constexpr std::uint32_t blr() { return 0x4e800020U; }

std::vector<std::uint8_t> words(std::initializer_list<std::uint32_t> values) {
    std::vector<std::uint8_t> bytes;
    bytes.reserve(values.size() * 4);
    for (auto word : values) {
        bytes.push_back(static_cast<std::uint8_t>(word >> 24U));
        bytes.push_back(static_cast<std::uint8_t>(word >> 16U));
        bytes.push_back(static_cast<std::uint8_t>(word >> 8U));
        bytes.push_back(static_cast<std::uint8_t>(word));
    }
    return bytes;
}

bool runProgram(ExecutionBackend& backend,
                std::span<const std::uint8_t> code,
                Memory& memory,
                CpuState& cpu,
                std::string& error) {
    constexpr std::uint32_t codeBase = 0x10000000U;
    if (!memory.load(codeBase, code, MemoryPerm::Read | MemoryPerm::Execute, "microtest-code")) {
        error = "code mapping failed";
        return false;
    }
    if (!memory.map(0x70000000U, 0x10000U, MemoryPerm::Read | MemoryPerm::Write, "microtest-stack")) {
        error = "stack mapping failed";
        return false;
    }
    cpu.pc = codeBase;
    cpu.lr = 0x7fff0000U;
    cpu.gpr[1] = 0x7000fff0U;
    ExecutionConfig config{};
    config.instructionLimit = 1000;
    const auto result = backend.run(memory, cpu, config);
    if (!result.ok()) {
        error = std::string(stopReasonName(result.reason)) + ": " + result.message;
        return false;
    }
    return true;
}

} // namespace

MicrotestResult runMicrotests(ExecutionBackend& backend) {
    std::ostringstream report;
    bool all = true;
    auto check = [&](bool condition, const char* name, const std::string& detail = {}) {
        report << (condition ? "PASS" : "FAIL") << "  " << name;
        if (!detail.empty()) report << "  " << detail;
        report << '\n';
        all = all && condition;
    };

    // Integer arithmetic and classic leaf return.
    {
        const auto code = words({
            dForm(14, 3, 3, 7),           // addi r3,r3,7
            xForm(31, 3, 3, 4, 235),      // mullw r3,r3,r4
            blr(),
        });
        Memory memory;
        CpuState cpu{};
        cpu.gpr[3] = 5;
        cpu.gpr[4] = 6;
        std::string error;
        const bool ran = runProgram(backend, code, memory, cpu, error);
        check(ran && cpu.gpr[3] == 72U, "integer leaf call",
              ran ? "r3=" + std::to_string(cpu.gpr[3]) : error);
    }

    // Stack frame and LR save/restore: common Code Fragment Manager-era prologue.
    {
        const auto code = words({
            dForm(37, 1, 1, static_cast<std::uint16_t>(-16)), // stwu r1,-16(r1)
            sprForm(0, 8, 339),                               // mflr r0
            dForm(36, 0, 1, 20),                              // stw r0,20(r1)
            dForm(14, 3, 3, 1),                               // addi r3,r3,1
            dForm(32, 0, 1, 20),                              // lwz r0,20(r1)
            sprForm(0, 8, 467),                               // mtlr r0
            dForm(14, 1, 1, 16),                              // addi r1,r1,16
            blr(),
        });
        Memory memory;
        CpuState cpu{};
        cpu.gpr[3] = 41;
        const std::uint32_t initialSp = 0x7000fff0U;
        std::string error;
        const bool ran = runProgram(backend, code, memory, cpu, error);
        check(ran && cpu.gpr[3] == 42U && cpu.gpr[1] == initialSp,
              "stack/LR prologue",
              ran ? "r3=" + std::to_string(cpu.gpr[3]) : error);
    }

    // Big-endian floating-point load/add/store.
    {
        const auto code = words({
            dForm(48, 1, 3, 0),             // lfs f1,0(r3)
            dForm(48, 2, 3, 4),             // lfs f2,4(r3)
            aForm(59, 3, 1, 2, 0, 21),      // fadds f3,f1,f2
            dForm(52, 3, 3, 8),             // stfs f3,8(r3)
            blr(),
        });
        Memory memory;
        constexpr std::uint32_t dataBase = 0x40000000U;
        memory.map(dataBase, 0x1000, MemoryPerm::Read | MemoryPerm::Write, "microtest-data");
        memory.write32(dataBase + 0, std::bit_cast<std::uint32_t>(1.25f));
        memory.write32(dataBase + 4, std::bit_cast<std::uint32_t>(2.5f));
        CpuState cpu{};
        cpu.gpr[3] = dataBase;
        std::string error;
        const bool ran = runProgram(backend, code, memory, cpu, error);
        std::uint32_t resultBits = 0;
        const bool read = memory.read32(dataBase + 8, resultBits);
        const float result = read ? std::bit_cast<float>(resultBits) : 0.0f;
        check(ran && read && result == 3.75f, "single-precision FP + big-endian memory",
              ran ? "result=" + std::to_string(result) : error);
    }

    // Integer divide/subtract-immediate and indexed FP forms demanded by the
    // first large external CFM constructor run used to qualify the original harness.
    {
        const auto code = words({
            dForm(14, 0, 0, 9),                 // li r0,9
            dForm(14, 25, 0, 5),                // li r25,5
            xForm(31, 3, 0, 25, 459),           // divwu r3,r0,r25 -> 1
            dForm(8, 4, 3, 0x0100),             // subfic r4,r3,256 -> 255
            xForm(31, 1, 5, 6, 663),            // stfsx f1,r5,r6
            xForm(31, 2, 5, 6, 535),            // lfsx f2,r5,r6
            blr(),
        });
        Memory memory;
        constexpr std::uint32_t dataBase = 0x40000000U;
        memory.map(dataBase, 0x1000, MemoryPerm::Read | MemoryPerm::Write, "microtest-indexed-fp");
        CpuState cpu{};
        cpu.gpr[5] = dataBase;
        cpu.gpr[6] = 4;
        cpu.fpr[1] = 3.25;
        std::string error;
        const bool ran = runProgram(backend, code, memory, cpu, error);
        std::uint32_t storedBits = 0;
        const bool read = memory.read32(dataBase + 4, storedBits);
        const float stored = read ? std::bit_cast<float>(storedBits) : 0.0f;
        check(ran && cpu.gpr[3] == 1U && cpu.gpr[4] == 255U &&
                  stored == 3.25f && cpu.fpr[2] == 3.25,
              "constructor-demanded PPC forms",
              ran ? "divwu=1 subfic=255 stfsx/lfsx=3.25" : error);
    }

    // Conditional branch and CR compare semantics.
    {
        // cmpwi cr0,r3,10 ; beq +8 ; li r3,0 ; li r3,1 ; blr
        const std::uint32_t cmpwi = (11U << 26U) | (0U << 23U) | (3U << 16U) | 10U;
        const std::uint32_t beq = (16U << 26U) | (12U << 21U) | (2U << 16U) | 8U;
        const auto code = words({cmpwi, beq, dForm(14, 3, 0, 0), dForm(14, 3, 0, 1), blr()});
        Memory memory;
        CpuState cpu{};
        cpu.gpr[3] = 10;
        std::string error;
        const bool ran = runProgram(backend, code, memory, cpu, error);
        check(ran && cpu.gpr[3] == 1U, "CR/conditional branch",
              ran ? "r3=" + std::to_string(cpu.gpr[3]) : error);
    }

    report << "backend=" << backend.name() << '\n';
    return {all, report.str()};
}

} // namespace ppclab::ppc
