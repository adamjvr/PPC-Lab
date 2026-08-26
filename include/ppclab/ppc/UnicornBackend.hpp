// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include "ppclab/ppc/Execution.hpp"

namespace ppclab::ppc {

class UnicornBackend final : public ExecutionBackend {
public:
    [[nodiscard]] const char* name() const noexcept override { return "unicorn-ppc32be"; }
    [[nodiscard]] static bool available() noexcept;
    ExecutionResult run(Memory& memory,
                        CpuState& cpu,
                        const ExecutionConfig& config) override;
};

} // namespace ppclab::ppc
