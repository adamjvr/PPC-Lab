// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/Memory.hpp"

#include <algorithm>
#include <fstream>
#include <iterator>

namespace ppclab::ppc {

bool Memory::map(std::uint32_t base,
                 std::size_t size,
                 MemoryPerm perms,
                 std::string name) {
    if (size == 0) return false;
    const std::uint64_t end = static_cast<std::uint64_t>(base) + size;
    if (end > 0x1'0000'0000ULL) return false;
    for (const auto& region : regions_) {
        if (!(end <= region.base || base >= region.endExclusive())) return false;
    }
    MemoryRegion region{};
    region.base = base;
    region.bytes.assign(size, 0);
    region.perms = perms;
    region.name = std::move(name);
    regions_.push_back(std::move(region));
    std::sort(regions_.begin(), regions_.end(), [](const auto& a, const auto& b) {
        return a.base < b.base;
    });
    return true;
}

bool Memory::load(std::uint32_t base,
                  std::span<const std::uint8_t> bytes,
                  MemoryPerm perms,
                  std::string name) {
    if (!map(base, bytes.size(), perms, std::move(name))) return false;
    auto* region = find(base, bytes.size());
    if (!region) return false;
    std::copy(bytes.begin(), bytes.end(), region->bytes.begin());
    return true;
}

bool Memory::loadFile(std::uint32_t base,
                      const std::string& path,
                      std::size_t mappedSize,
                      MemoryPerm perms,
                      std::string name) {
    std::ifstream input(path, std::ios::binary);
    if (!input) return false;
    std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(input)),
                                    std::istreambuf_iterator<char>());
    if (mappedSize == 0) mappedSize = bytes.size();
    if (bytes.size() > mappedSize || mappedSize == 0) return false;
    if (!map(base, mappedSize, perms, std::move(name))) return false;
    auto* region = find(base, mappedSize);
    if (!region) return false;
    std::copy(bytes.begin(), bytes.end(), region->bytes.begin());
    return true;
}

const MemoryRegion* Memory::find(std::uint32_t address, std::size_t size) const noexcept {
    const std::uint64_t end = static_cast<std::uint64_t>(address) + size;
    for (const auto& region : regions_) {
        if (address >= region.base && end <= region.endExclusive()) return &region;
    }
    return nullptr;
}

MemoryRegion* Memory::find(std::uint32_t address, std::size_t size) noexcept {
    const std::uint64_t end = static_cast<std::uint64_t>(address) + size;
    for (auto& region : regions_) {
        if (address >= region.base && end <= region.endExclusive()) return &region;
    }
    return nullptr;
}

bool Memory::readable(std::uint32_t address, std::size_t size) const noexcept {
    const auto* r = find(address, size);
    return r && hasPerm(r->perms, MemoryPerm::Read);
}
bool Memory::writable(std::uint32_t address, std::size_t size) const noexcept {
    const auto* r = find(address, size);
    return r && hasPerm(r->perms, MemoryPerm::Write);
}
bool Memory::executable(std::uint32_t address, std::size_t size) const noexcept {
    const auto* r = find(address, size);
    return r && hasPerm(r->perms, MemoryPerm::Execute);
}

bool Memory::read8(std::uint32_t address, std::uint8_t& value) const noexcept {
    const auto* r = find(address, 1);
    if (!r || !hasPerm(r->perms, MemoryPerm::Read)) return false;
    value = r->bytes[address - r->base];
    return true;
}

bool Memory::read16(std::uint32_t address, std::uint16_t& value) const noexcept {
    std::uint8_t b[2]{};
    if (!readBytes(address, b)) return false;
    value = static_cast<std::uint16_t>((static_cast<std::uint16_t>(b[0]) << 8U) | b[1]);
    return true;
}

bool Memory::read32(std::uint32_t address, std::uint32_t& value) const noexcept {
    std::uint8_t b[4]{};
    if (!readBytes(address, b)) return false;
    value = (static_cast<std::uint32_t>(b[0]) << 24U) |
            (static_cast<std::uint32_t>(b[1]) << 16U) |
            (static_cast<std::uint32_t>(b[2]) << 8U) |
            static_cast<std::uint32_t>(b[3]);
    return true;
}

bool Memory::read64(std::uint32_t address, std::uint64_t& value) const noexcept {
    std::uint8_t b[8]{};
    if (!readBytes(address, b)) return false;
    value = 0;
    for (auto byte : b) value = (value << 8U) | byte;
    return true;
}

bool Memory::write8(std::uint32_t address, std::uint8_t value) noexcept {
    auto* r = find(address, 1);
    if (!r || !hasPerm(r->perms, MemoryPerm::Write)) return false;
    r->bytes[address - r->base] = value;
    return true;
}

bool Memory::write16(std::uint32_t address, std::uint16_t value) noexcept {
    const std::uint8_t b[2]{static_cast<std::uint8_t>(value >> 8U),
                            static_cast<std::uint8_t>(value)};
    return writeBytes(address, b);
}

bool Memory::write32(std::uint32_t address, std::uint32_t value) noexcept {
    const std::uint8_t b[4]{static_cast<std::uint8_t>(value >> 24U),
                            static_cast<std::uint8_t>(value >> 16U),
                            static_cast<std::uint8_t>(value >> 8U),
                            static_cast<std::uint8_t>(value)};
    return writeBytes(address, b);
}

bool Memory::write64(std::uint32_t address, std::uint64_t value) noexcept {
    std::uint8_t b[8]{};
    for (int i = 7; i >= 0; --i) {
        b[i] = static_cast<std::uint8_t>(value & 0xffU);
        value >>= 8U;
    }
    return writeBytes(address, b);
}

bool Memory::writeBytes(std::uint32_t address, std::span<const std::uint8_t> bytes) noexcept {
    auto* r = find(address, bytes.size());
    if (!r || !hasPerm(r->perms, MemoryPerm::Write)) return false;
    std::copy(bytes.begin(), bytes.end(),
              r->bytes.begin() + static_cast<std::ptrdiff_t>(address - r->base));
    return true;
}

bool Memory::readBytes(std::uint32_t address, std::span<std::uint8_t> out) const noexcept {
    const auto* r = find(address, out.size());
    if (!r || !hasPerm(r->perms, MemoryPerm::Read)) return false;
    std::copy_n(r->bytes.begin() + static_cast<std::ptrdiff_t>(address - r->base),
                out.size(), out.begin());
    return true;
}

} // namespace ppclab::ppc
