// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/Execution.hpp"

namespace ppclab::ppc {

const char* stopReasonName(StopReason reason) noexcept {
    switch (reason) {
    case StopReason::Returned: return "returned";
    case StopReason::InstructionLimit: return "instruction_limit";
    case StopReason::UnsupportedInstruction: return "unsupported_instruction";
    case StopReason::MemoryFault: return "memory_fault";
    case StopReason::ImportTrap: return "import_trap";
    case StopReason::Trap: return "trap";
    case StopReason::SystemCall: return "system_call";
    case StopReason::InvalidConfiguration: return "invalid_configuration";
    case StopReason::BackendError: return "backend_error";
    }
    return "unknown";
}

} // namespace ppclab::ppc
