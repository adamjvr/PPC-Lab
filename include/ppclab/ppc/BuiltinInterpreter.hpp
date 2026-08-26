// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include "ppclab/ppc/Execution.hpp"

#include <string>

namespace ppclab::ppc {

class BuiltinInterpreter final : public ExecutionBackend {
public:
    [[nodiscard]] const char* name() const noexcept override { return "builtin-ppc32be"; }
    ExecutionResult run(Memory& memory,
                        CpuState& cpu,
                        const ExecutionConfig& config) override;

    [[nodiscard]] static std::string disassemble(std::uint32_t pc, std::uint32_t instruction);

private:
    static bool evaluateBranchCondition(CpuState& cpu, unsigned bo, unsigned bi) noexcept;
};

} // namespace ppclab::ppc
