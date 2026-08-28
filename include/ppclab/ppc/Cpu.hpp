// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include <array>
#include <cstdint>

namespace ppclab::ppc {

struct CpuState {
    std::array<std::uint32_t, 32> gpr{};
    std::array<double, 32> fpr{};
    std::uint32_t pc = 0;
    std::uint32_t lr = 0;
    std::uint32_t ctr = 0;
    std::uint32_t cr = 0;
    std::uint32_t xer = 0;
    std::uint32_t fpscr = 0;
    std::uint32_t reservationAddress = 0;
    bool reservationValid = false;

    [[nodiscard]] bool crBit(unsigned bi) const noexcept {
        if (bi >= 32) return false;
        return ((cr >> (31U - bi)) & 1U) != 0;
    }

    void setCrField(unsigned field,
                    bool less,
                    bool greater,
                    bool equal,
                    bool summaryOverflow = false) noexcept {
        if (field >= 8) return;
        const unsigned shift = 28U - field * 4U;
        const std::uint32_t nibble = (less ? 8U : 0U) |
                                     (greater ? 4U : 0U) |
                                     (equal ? 2U : 0U) |
                                     (summaryOverflow ? 1U : 0U);
        cr = (cr & ~(0xFU << shift)) | (nibble << shift);
    }
};

} // namespace ppclab::ppc
