// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/BuiltinInterpreter.hpp"
#include "ppclab/ppc/Memory.hpp"
#include "ppclab/ppc/Microtests.hpp"
#include "ppclab/ppc/UnicornBackend.hpp"

#include <cassert>
#include <cstdint>
#include <iostream>

int main() {
    ppclab::ppc::Memory memory;
    assert(memory.map(0x1000, 0x100, ppclab::ppc::MemoryPerm::Read | ppclab::ppc::MemoryPerm::Write,
                      "be-memory"));
    assert(memory.write32(0x1010, 0x12345678U));
    std::uint32_t value = 0;
    assert(memory.read32(0x1010, value));
    assert(value == 0x12345678U);
    const auto* region = memory.find(0x1010, 4);
    assert(region != nullptr);
    assert(region->bytes[0x10] == 0x12);
    assert(region->bytes[0x11] == 0x34);
    assert(region->bytes[0x12] == 0x56);
    assert(region->bytes[0x13] == 0x78);

    ppclab::ppc::BuiltinInterpreter builtin;
    const auto result = ppclab::ppc::runMicrotests(builtin);
    std::cout << result.report;
    assert(result.passed);

    std::cout << "unicorn_available=" << (ppclab::ppc::UnicornBackend::available() ? "yes" : "no") << '\n';
    return 0;
}
