// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include "ppclab/ppc/Execution.hpp"
#include "ppclab/ppc/ImageSymbol.hpp"

#include <cstddef>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace ppclab::ppc {

struct ImageConfig {
    std::string codePath{};
    std::string elfPath{};
    std::string machoPath{};
    std::string pefPath{};
    std::string dataPath{};
    std::uint32_t imageBase = 0x10000000U;
    std::vector<SymbolBinding> symbolBindings{};
    std::uint32_t codeBase = 0x10000000U;
    std::uint32_t dataBase = 0x20000000U;
    std::size_t dataMapSize = 0x00200000U;
    std::uint32_t heapBase = 0x40000000U;
    std::size_t heapSize = 0x00200000U;
    std::uint32_t stackBase = 0x70000000U;
    std::size_t stackSize = 0x00100000U;
};

struct RegisterAssignment {
    unsigned index = 0;
    std::uint32_t value = 0;
};

struct FloatRegisterAssignment {
    unsigned index = 0;
    double value = 0.0;
};

struct MemoryWrite32 {
    std::uint32_t address = 0;
    std::uint32_t value = 0;
};

struct MemoryWriteFloat {
    std::uint32_t address = 0;
    float value = 0.0f;
};

struct CallConfig {
    ImageConfig image{};
    std::uint32_t entry = 0;
    std::string entrySymbol{};
    std::uint32_t toc = 0;
    std::uint32_t transitionVector = 0;
    std::vector<RegisterAssignment> registers{};
    std::vector<FloatRegisterAssignment> floatRegisters{};
    std::vector<MemoryWrite32> writes32{};
    std::vector<MemoryWriteFloat> writesFloat{};
    ExecutionConfig execution{};
};

struct CallResult {
    ExecutionResult execution{};
    CpuState cpu{};
    Memory memory{};
    std::vector<ImageSymbol> symbols{};
};

class CallHarness {
public:
    static bool prepare(const CallConfig& config,
                        Memory& memory,
                        CpuState& cpu,
                        std::string& error,
                        std::vector<ImageSymbol>* symbols = nullptr);

    static CallResult run(const CallConfig& config, ExecutionBackend& backend);
};

} // namespace ppclab::ppc
