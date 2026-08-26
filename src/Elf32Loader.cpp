// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/Elf32Loader.hpp"

#include <algorithm>
#include <fstream>
#include <iterator>
#include <limits>
#include <span>
#include <sstream>

namespace ppclab::ppc {
namespace {

constexpr std::size_t kElf32HeaderSize = 52;
constexpr std::size_t kProgramHeaderSize = 32;
constexpr std::uint16_t kEtExec = 2;
constexpr std::uint16_t kEmPpc = 20;
constexpr std::uint32_t kPtLoad = 1;
constexpr std::uint32_t kPfX = 1;
constexpr std::uint32_t kPfW = 2;
constexpr std::uint32_t kPfR = 4;

bool readFile(const std::string& path, std::vector<std::uint8_t>& bytes, std::string& error) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        error = "cannot open ELF file: " + path;
        return false;
    }
    bytes.assign(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
    if (bytes.empty()) {
        error = "ELF file is empty: " + path;
        return false;
    }
    return true;
}

bool rangeWithin(std::size_t offset, std::size_t size, std::size_t total) noexcept {
    return offset <= total && size <= total - offset;
}

std::uint16_t be16(const std::vector<std::uint8_t>& b, std::size_t off) noexcept {
    return static_cast<std::uint16_t>((static_cast<std::uint16_t>(b[off]) << 8U) |
                                      static_cast<std::uint16_t>(b[off + 1]));
}

std::uint32_t be32(const std::vector<std::uint8_t>& b, std::size_t off) noexcept {
    return (static_cast<std::uint32_t>(b[off]) << 24U) |
           (static_cast<std::uint32_t>(b[off + 1]) << 16U) |
           (static_cast<std::uint32_t>(b[off + 2]) << 8U) |
           static_cast<std::uint32_t>(b[off + 3]);
}

bool parse(const std::vector<std::uint8_t>& bytes,
           Elf32ImageInfo& info,
           std::string& error) {
    info = {};
    if (bytes.size() < kElf32HeaderSize) {
        error = "file is smaller than an ELF32 header";
        return false;
    }
    if (bytes[0] != 0x7f || bytes[1] != 'E' || bytes[2] != 'L' || bytes[3] != 'F') {
        error = "not an ELF file";
        return false;
    }
    if (bytes[4] != 1) {
        error = "unsupported ELF class: expected ELFCLASS32";
        return false;
    }
    if (bytes[5] != 2) {
        error = "unsupported ELF byte order: expected big-endian ELFDATA2MSB";
        return false;
    }
    if (bytes[6] != 1 || be32(bytes, 20) != 1) {
        error = "unsupported ELF version";
        return false;
    }

    info.type = be16(bytes, 16);
    info.machine = be16(bytes, 18);
    info.entry = be32(bytes, 24);
    const auto phoff = be32(bytes, 28);
    info.flags = be32(bytes, 36);
    const auto ehsize = be16(bytes, 40);
    const auto phentsize = be16(bytes, 42);
    const auto phnum = be16(bytes, 44);

    if (info.machine != kEmPpc) {
        error = "unsupported ELF machine: expected EM_PPC (20)";
        return false;
    }
    if (info.type != kEtExec) {
        std::ostringstream out;
        out << "unsupported ELF type " << info.type
            << ": PPC Lab v0.2 loads fixed-address ET_EXEC images only; relocations are not implemented";
        error = out.str();
        return false;
    }
    if (ehsize < kElf32HeaderSize) {
        error = "invalid ELF header size";
        return false;
    }
    if (phnum == 0) {
        error = "ELF has no program headers";
        return false;
    }
    if (phentsize < kProgramHeaderSize) {
        error = "ELF program-header entries are too small";
        return false;
    }
    const std::uint64_t phBytes = static_cast<std::uint64_t>(phentsize) * phnum;
    if (phBytes > std::numeric_limits<std::size_t>::max() ||
        !rangeWithin(phoff, static_cast<std::size_t>(phBytes), bytes.size())) {
        error = "ELF program-header table lies outside the file";
        return false;
    }

    for (std::uint32_t i = 0; i < phnum; ++i) {
        const std::size_t off = static_cast<std::size_t>(phoff) +
                                static_cast<std::size_t>(i) * phentsize;
        const auto type = be32(bytes, off + 0);
        if (type != kPtLoad) continue;

        Elf32SegmentInfo segment{};
        segment.index = i;
        segment.fileOffset = be32(bytes, off + 4);
        segment.virtualAddress = be32(bytes, off + 8);
        segment.physicalAddress = be32(bytes, off + 12);
        segment.fileSize = be32(bytes, off + 16);
        segment.memorySize = be32(bytes, off + 20);
        segment.flags = be32(bytes, off + 24);
        segment.alignment = be32(bytes, off + 28);

        if (segment.memorySize == 0) continue;
        if (segment.fileSize > segment.memorySize) {
            error = "ELF PT_LOAD has p_filesz larger than p_memsz";
            return false;
        }
        if (!rangeWithin(segment.fileOffset, segment.fileSize, bytes.size())) {
            error = "ELF PT_LOAD file range lies outside the file";
            return false;
        }
        const std::uint64_t vend = static_cast<std::uint64_t>(segment.virtualAddress) +
                                   segment.memorySize;
        if (vend > 0x1'0000'0000ULL) {
            error = "ELF PT_LOAD virtual range exceeds 32-bit address space";
            return false;
        }
        info.loadSegments.push_back(segment);
    }

    if (info.loadSegments.empty()) {
        error = "ELF contains no non-empty PT_LOAD segments";
        return false;
    }
    return true;
}

MemoryPerm memoryPerms(std::uint32_t flags) noexcept {
    MemoryPerm perms = MemoryPerm::None;
    // Instruction fetches in PPC Lab use the same byte storage/read helpers as
    // data reads, so executable ELF mappings are readable internally even if a
    // rare input omits PF_R.
    if ((flags & (kPfR | kPfX)) != 0) perms = perms | MemoryPerm::Read;
    if ((flags & kPfW) != 0) perms = perms | MemoryPerm::Write;
    if ((flags & kPfX) != 0) perms = perms | MemoryPerm::Execute;
    return perms;
}

} // namespace

bool Elf32Loader::inspectFile(const std::string& path,
                              Elf32ImageInfo& info,
                              std::string& error) {
    std::vector<std::uint8_t> bytes;
    if (!readFile(path, bytes, error)) return false;
    return parse(bytes, info, error);
}

bool Elf32Loader::loadFile(const std::string& path,
                           Memory& memory,
                           Elf32ImageInfo& info,
                           std::string& error) {
    std::vector<std::uint8_t> bytes;
    if (!readFile(path, bytes, error)) return false;
    if (!parse(bytes, info, error)) return false;

    for (const auto& segment : info.loadSegments) {
        const auto perms = memoryPerms(segment.flags);
        std::ostringstream name;
        name << "elf:PT_LOAD[" << segment.index << ']';
        if (!memory.map(segment.virtualAddress, segment.memorySize, perms, name.str())) {
            std::ostringstream out;
            out << "failed to map ELF PT_LOAD[" << segment.index << "] at 0x"
                << std::hex << segment.virtualAddress << " size 0x" << segment.memorySize
                << " (overlap or invalid range)";
            error = out.str();
            return false;
        }
        if (segment.fileSize != 0) {
            auto* region = memory.find(segment.virtualAddress, segment.memorySize);
            if (!region) {
                error = "internal error locating newly mapped ELF segment";
                return false;
            }
            std::copy_n(bytes.begin() + static_cast<std::ptrdiff_t>(segment.fileOffset),
                        segment.fileSize, region->bytes.begin());
        }
    }
    return true;
}

std::string elf32SegmentFlags(std::uint32_t flags) {
    std::string out;
    out += (flags & kPfR) != 0 ? 'R' : '-';
    out += (flags & kPfW) != 0 ? 'W' : '-';
    out += (flags & kPfX) != 0 ? 'X' : '-';
    return out;
}

} // namespace ppclab::ppc
