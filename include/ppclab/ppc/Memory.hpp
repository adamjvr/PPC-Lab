// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include <cstddef>
#include <cstdint>
#include <span>
#include <string>
#include <vector>

namespace ppclab::ppc {

enum class MemoryPerm : std::uint8_t {
    None = 0,
    Read = 1,
    Write = 2,
    Execute = 4,
};

constexpr MemoryPerm operator|(MemoryPerm a, MemoryPerm b) noexcept {
    return static_cast<MemoryPerm>(static_cast<unsigned>(a) | static_cast<unsigned>(b));
}
constexpr bool hasPerm(MemoryPerm value, MemoryPerm flag) noexcept {
    return (static_cast<unsigned>(value) & static_cast<unsigned>(flag)) != 0;
}

struct MemoryRegion {
    std::uint32_t base = 0;
    std::vector<std::uint8_t> bytes{};
    MemoryPerm perms = MemoryPerm::None;
    std::string name{};

    [[nodiscard]] std::uint64_t endExclusive() const noexcept {
        return static_cast<std::uint64_t>(base) + bytes.size();
    }
};

class Memory {
public:
    bool map(std::uint32_t base,
             std::size_t size,
             MemoryPerm perms,
             std::string name = {});

    bool load(std::uint32_t base,
              std::span<const std::uint8_t> bytes,
              MemoryPerm perms,
              std::string name = {});

    bool loadFile(std::uint32_t base,
                  const std::string& path,
                  std::size_t mappedSize,
                  MemoryPerm perms,
                  std::string name = {});

    [[nodiscard]] const std::vector<MemoryRegion>& regions() const noexcept { return regions_; }
    [[nodiscard]] std::vector<MemoryRegion>& regions() noexcept { return regions_; }

    [[nodiscard]] bool readable(std::uint32_t address, std::size_t size = 1) const noexcept;
    [[nodiscard]] bool writable(std::uint32_t address, std::size_t size = 1) const noexcept;
    [[nodiscard]] bool executable(std::uint32_t address, std::size_t size = 1) const noexcept;

    [[nodiscard]] bool read8(std::uint32_t address, std::uint8_t& value) const noexcept;
    [[nodiscard]] bool read16(std::uint32_t address, std::uint16_t& value) const noexcept;
    [[nodiscard]] bool read32(std::uint32_t address, std::uint32_t& value) const noexcept;
    [[nodiscard]] bool read64(std::uint32_t address, std::uint64_t& value) const noexcept;

    bool write8(std::uint32_t address, std::uint8_t value) noexcept;
    bool write16(std::uint32_t address, std::uint16_t value) noexcept;
    bool write32(std::uint32_t address, std::uint32_t value) noexcept;
    bool write64(std::uint32_t address, std::uint64_t value) noexcept;
    bool writeBytes(std::uint32_t address, std::span<const std::uint8_t> bytes) noexcept;
    [[nodiscard]] bool readBytes(std::uint32_t address, std::span<std::uint8_t> out) const noexcept;

    [[nodiscard]] const MemoryRegion* find(std::uint32_t address, std::size_t size = 1) const noexcept;
    [[nodiscard]] MemoryRegion* find(std::uint32_t address, std::size_t size = 1) noexcept;

private:
    std::vector<MemoryRegion> regions_{};
};

} // namespace ppclab::ppc
