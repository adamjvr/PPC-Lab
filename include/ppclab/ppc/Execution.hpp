// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include "ppclab/ppc/Cpu.hpp"
#include "ppclab/ppc/Memory.hpp"
#include "ppclab/ppc/ImportStubs.hpp"
#include "ppclab/ppc/ImageSymbol.hpp"

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace ppclab::ppc {

enum class StopReason : std::uint8_t {
    Returned = 0,
    InstructionLimit,
    UnsupportedInstruction,
    MemoryFault,
    ImportTrap,
    InvalidConfiguration,
    BackendError,
};

struct TraceRange {
    std::uint32_t begin = 0;
    std::uint32_t end = 0xffffffffU;

    [[nodiscard]] bool contains(std::uint32_t pc) const noexcept {
        return pc >= begin && pc <= end;
    }
};

struct ExecutionConfig {
    std::uint64_t instructionLimit = 1'000'000;
    std::uint32_t returnAddress = 0x7fff0000U;
    std::uint32_t importBase = 0x30000000U;
    std::uint32_t importSize = 0x00010000U;
    bool trace = false;
    std::vector<ImportStubBinding> importStubs{};
    std::optional<TraceRange> traceRange{};
    const std::vector<ImageSymbol>* traceSymbols = nullptr;
};

struct ExecutionResult {
    StopReason reason = StopReason::BackendError;
    std::uint64_t instructions = 0;
    std::uint32_t pc = 0;
    std::uint32_t instruction = 0;
    std::string message{};

    [[nodiscard]] bool ok() const noexcept { return reason == StopReason::Returned; }
};

[[nodiscard]] const char* stopReasonName(StopReason reason) noexcept;

class ExecutionBackend {
public:
    virtual ~ExecutionBackend() = default;
    [[nodiscard]] virtual const char* name() const noexcept = 0;
    virtual ExecutionResult run(Memory& memory,
                                CpuState& cpu,
                                const ExecutionConfig& config) = 0;
};

} // namespace ppclab::ppc
