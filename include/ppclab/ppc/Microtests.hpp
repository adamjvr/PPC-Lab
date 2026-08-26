// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include "ppclab/ppc/Execution.hpp"

#include <string>

namespace ppclab::ppc {

struct MicrotestResult {
    bool passed = false;
    std::string report{};
};

MicrotestResult runMicrotests(ExecutionBackend& backend);

} // namespace ppclab::ppc
