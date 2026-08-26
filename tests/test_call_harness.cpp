// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/BuiltinInterpreter.hpp"
#include "ppclab/ppc/CallHarness.hpp"

#include <cassert>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <vector>

namespace {

constexpr std::uint32_t dForm(unsigned op, unsigned rt, unsigned ra, std::uint16_t imm) {
    return (op << 26U) | (rt << 21U) | (ra << 16U) | imm;
}
constexpr std::uint32_t xForm(unsigned op,
                              unsigned rt,
                              unsigned ra,
                              unsigned rb,
                              unsigned xo) {
    return (op << 26U) | (rt << 21U) | (ra << 16U) | (rb << 11U) | (xo << 1U);
}
constexpr std::uint32_t sprForm(unsigned rt, unsigned spr, unsigned xo) {
    const unsigned encoded = ((spr & 0x1fU) << 5U) | ((spr >> 5U) & 0x1fU);
    return (31U << 26U) | (rt << 21U) | (encoded << 11U) | (xo << 1U);
}

void writeWords(const std::filesystem::path& path, std::initializer_list<std::uint32_t> words) {
    std::ofstream out(path, std::ios::binary);
    for (auto word : words) {
        const char b[4]{static_cast<char>(word >> 24U), static_cast<char>(word >> 16U),
                        static_cast<char>(word >> 8U), static_cast<char>(word)};
        out.write(b, 4);
    }
}

} // namespace

int main() {
    namespace fs = std::filesystem;
    const auto dir = fs::temp_directory_path() / "ppc_lab_call_test";
    fs::remove_all(dir);
    fs::create_directories(dir);
    const auto code = dir / "code.bin";
    const auto data = dir / "data.bin";

    writeWords(code, {
        dForm(14, 3, 3, 7),
        xForm(31, 3, 3, 4, 235),
        0x4e800020U,
    });
    // Transition vector: code entry 0x10000000, TOC 0x20008000.
    writeWords(data, {0x10000000U, 0x20008000U});

    ppclab::ppc::CallConfig config{};
    config.image.codePath = code.string();
    config.image.dataPath = data.string();
    config.image.dataMapSize = 0x1000;
    config.transitionVector = 0x20000000U;
    config.registers.push_back({3, 5});
    config.registers.push_back({4, 6});

    ppclab::ppc::BuiltinInterpreter backend;
    auto result = ppclab::ppc::CallHarness::run(config, backend);
    assert(result.execution.reason == ppclab::ppc::StopReason::Returned);
    assert(result.cpu.gpr[3] == 72U);
    assert(result.cpu.gpr[2] == 0x20008000U);
    assert(result.cpu.gpr[12] == 0x20000000U);

    // A tiny indirect call into the reserved import range must stop as an
    // ImportTrap. This is the generic discovery path for unresolved runtime calls.
    writeWords(code, {
        dForm(15, 12, 0, 0x3000),          // lis r12,0x3000 -> 0x30000000
        sprForm(12, 9, 467),               // mtctr r12
        0x4e800420U,                        // bctr
    });
    config.transitionVector = 0;
    config.entry = 0x10000000U;
    config.registers.clear();
    result = ppclab::ppc::CallHarness::run(config, backend);
    assert(result.execution.reason == ppclab::ppc::StopReason::ImportTrap);
    assert(result.execution.pc == 0x30000000U);

    // Match a common CFM glue shape: r12 is a synthetic import identity,
    // the placeholder descriptor words read as zero,
    // and bctr must still classify the boundary using r12 instead of falling to PC 0.
    writeWords(code, {
        dForm(15, 12, 0, 0x3000),          // lis r12,0x3000
        dForm(14, 12, 12, 0x01c8),         // addi r12,r12,0x1c8
        dForm(32, 0, 12, 0),               // lwz r0,0(r12)
        dForm(32, 2, 12, 4),               // lwz r2,4(r12)
        sprForm(0, 9, 467),                 // mtctr r0
        0x4e800420U,                        // bctr
    });
    config.entry = 0x10000000U;
    result = ppclab::ppc::CallHarness::run(config, backend);
    assert(result.execution.reason == ppclab::ppc::StopReason::ImportTrap);
    assert(result.execution.pc == 0x300001c8U);

    // Opt-in known-import stubbing should execute the same synthetic CFM call
    // and return through LR instead of hiding unknown imports globally.
    config.execution.importStubs = {{0x300001c8U, ppclab::ppc::ImportStubKind::BlockMoveData, "BlockMoveData"}};
    config.writes32.clear();
    // Source bytes at 0x40000000 and destination at 0x40000010.
    config.writes32.push_back({0x40000000U, 0x11223344U});
    config.registers = {{3, 0x40000000U}, {4, 0x40000010U}, {5, 4U}};
    result = ppclab::ppc::CallHarness::run(config, backend);
    assert(result.execution.reason == ppclab::ppc::StopReason::Returned);
    std::uint32_t copied = 0;
    assert(result.memory.read32(0x40000010U, copied));
    assert(copied == 0x11223344U);

    // A synthetic CFM call through the MathLib sin identity should resume via
    // LR when known stubs are enabled. Host libm is execution-enabling only;
    // exact Classic MathLib rounding is intentionally not asserted here.
    writeWords(code, {
        dForm(15, 12, 0, 0x3000),          // lis r12,0x3000
        dForm(14, 12, 12, 0x0014),         // addi r12,r12,0x14 (sin)
        dForm(32, 0, 12, 0),
        dForm(32, 2, 12, 4),
        sprForm(0, 9, 467),
        0x4e800420U,
    });
    config.registers.clear();
    config.writes32.clear();
    config.execution.importStubs.push_back({0x30000014U, ppclab::ppc::ImportStubKind::Sin, "sin"});
    config.floatRegisters = {{1, 0.5}};
    result = ppclab::ppc::CallHarness::run(config, backend);
    assert(result.execution.reason == ppclab::ppc::StopReason::Returned);
    assert(std::abs(result.cpu.fpr[1] - std::sin(0.5)) < 1.0e-15);

    fs::remove_all(dir);
    return 0;
}
