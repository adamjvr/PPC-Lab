// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/MachOLoader.hpp"

#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iterator>
#include <limits>
#include <optional>
#include <span>
#include <sstream>
#include <unordered_map>
#include <vector>

namespace ppclab::ppc {
namespace {

constexpr std::uint32_t MH_MAGIC = 0xfeedfaceU;
constexpr std::uint32_t FAT_MAGIC = 0xcafebabeU;
constexpr std::uint32_t CPU_TYPE_POWERPC = 18U;
constexpr std::uint32_t MH_OBJECT = 1U;
constexpr std::uint32_t MH_EXECUTE = 2U;
constexpr std::uint32_t MH_DYLIB = 6U;
constexpr std::uint32_t MH_BUNDLE = 8U;
constexpr std::uint32_t LC_SEGMENT = 0x1U;
constexpr std::uint32_t LC_SYMTAB = 0x2U;
constexpr std::uint32_t LC_THREAD = 0x4U;
constexpr std::uint32_t LC_UNIXTHREAD = 0x5U;
constexpr std::uint32_t LC_MAIN = 0x80000028U;
constexpr std::uint32_t PPC_THREAD_STATE = 1U;
constexpr std::uint32_t VM_PROT_READ = 1U;
constexpr std::uint32_t VM_PROT_WRITE = 2U;
constexpr std::uint32_t VM_PROT_EXECUTE = 4U;
constexpr std::uint32_t S_ZEROFILL = 1U;
constexpr std::uint8_t N_STAB = 0xe0U;
constexpr std::uint8_t N_TYPE = 0x0eU;
constexpr std::uint8_t N_UNDF = 0x00U;
constexpr std::uint8_t N_ABS = 0x02U;
constexpr std::uint8_t N_SECT = 0x0eU;
constexpr std::uint8_t N_EXT = 0x01U;
constexpr std::uint16_t N_WEAK_REF = 0x0040U;

constexpr std::uint32_t PPC_RELOC_VANILLA = 0U;
constexpr std::uint32_t PPC_RELOC_PAIR = 1U;
constexpr std::uint32_t PPC_RELOC_BR14 = 2U;
constexpr std::uint32_t PPC_RELOC_BR24 = 3U;
constexpr std::uint32_t PPC_RELOC_HI16 = 4U;
constexpr std::uint32_t PPC_RELOC_LO16 = 5U;
constexpr std::uint32_t PPC_RELOC_HA16 = 6U;
constexpr std::uint32_t PPC_RELOC_LO14 = 7U;

struct SymtabCommand {
    bool present = false;
    std::uint32_t symoff = 0;
    std::uint32_t nsyms = 0;
    std::uint32_t stroff = 0;
    std::uint32_t strsize = 0;
};

struct RawSymbol {
    ImageSymbol symbol{};
    std::uint8_t nType = 0;
    std::uint8_t nSect = 0;
    std::uint16_t nDesc = 0;
};

struct ParsedMachO {
    std::vector<std::uint8_t> fileBytes{};
    std::span<const std::uint8_t> bytes{};
    MachOImageInfo info{};
    SymtabCommand symtab{};
    std::vector<RawSymbol> rawSymbols{};
    std::optional<std::uint64_t> entryFileOffset{};
    std::optional<std::uint32_t> threadPc{};
};

bool readFile(const std::string& path, std::vector<std::uint8_t>& bytes, std::string& error) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        error = "cannot open Mach-O file: " + path;
        return false;
    }
    bytes.assign(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
    if (bytes.empty()) {
        error = "Mach-O file is empty: " + path;
        return false;
    }
    return true;
}

bool rangeWithin(std::size_t offset, std::size_t size, std::size_t total) noexcept {
    return offset <= total && size <= total - offset;
}

std::uint16_t be16(std::span<const std::uint8_t> b, std::size_t off) noexcept {
    return static_cast<std::uint16_t>((static_cast<std::uint16_t>(b[off]) << 8U) | b[off + 1]);
}

std::uint32_t be32(std::span<const std::uint8_t> b, std::size_t off) noexcept {
    return (static_cast<std::uint32_t>(b[off]) << 24U) |
           (static_cast<std::uint32_t>(b[off + 1]) << 16U) |
           (static_cast<std::uint32_t>(b[off + 2]) << 8U) |
           static_cast<std::uint32_t>(b[off + 3]);
}

std::uint64_t be64(std::span<const std::uint8_t> b, std::size_t off) noexcept {
    return (static_cast<std::uint64_t>(be32(b, off)) << 32U) | be32(b, off + 4);
}

std::string fixedString(std::span<const std::uint8_t> b, std::size_t off, std::size_t count) {
    std::size_t len = 0;
    while (len < count && b[off + len] != 0) ++len;
    return std::string(reinterpret_cast<const char*>(b.data() + off), len);
}

std::string cstringAt(std::span<const std::uint8_t> b,
                      std::size_t base,
                      std::size_t size,
                      std::uint32_t offset) {
    if (offset >= size || base + offset >= b.size()) return {};
    std::size_t end = base + offset;
    const std::size_t limit = std::min(b.size(), base + size);
    while (end < limit && b[end] != 0) ++end;
    return std::string(reinterpret_cast<const char*>(b.data() + base + offset),
                       end - (base + offset));
}

std::uint32_t alignUp(std::uint32_t value, std::uint32_t alignment) noexcept {
    if (alignment <= 1) return value;
    return static_cast<std::uint32_t>((static_cast<std::uint64_t>(value) + alignment - 1U) &
                                      ~(static_cast<std::uint64_t>(alignment) - 1U));
}

MemoryPerm permsFromVm(std::uint32_t prot) noexcept {
    MemoryPerm perms = MemoryPerm::None;
    if ((prot & (VM_PROT_READ | VM_PROT_EXECUTE)) != 0) perms = perms | MemoryPerm::Read;
    if ((prot & VM_PROT_WRITE) != 0) perms = perms | MemoryPerm::Write;
    if ((prot & VM_PROT_EXECUTE) != 0) perms = perms | MemoryPerm::Execute;
    return perms;
}

bool chooseSlice(std::vector<std::uint8_t>& file,
                 std::span<const std::uint8_t>& slice,
                 MachOImageInfo& info,
                 std::string& error) {
    if (file.size() < 4) {
        error = "file is too small for Mach-O magic";
        return false;
    }
    const auto magic = be32(file, 0);
    if (magic == MH_MAGIC) {
        slice = file;
        info.sliceOffset = 0;
        info.sliceSize = static_cast<std::uint32_t>(file.size());
        return true;
    }
    if (magic != FAT_MAGIC) {
        error = "not a big-endian 32-bit PowerPC Mach-O/fat file";
        return false;
    }
    if (file.size() < 8) {
        error = "truncated Mach-O fat header";
        return false;
    }
    info.fatContainer = true;
    const auto nfat = be32(file, 4);
    const std::uint64_t tableEnd = 8ULL + static_cast<std::uint64_t>(nfat) * 20ULL;
    if (tableEnd > file.size()) {
        error = "Mach-O fat architecture table lies outside the file";
        return false;
    }
    for (std::uint32_t i = 0; i < nfat; ++i) {
        const std::size_t off = 8 + static_cast<std::size_t>(i) * 20;
        if (be32(file, off) != CPU_TYPE_POWERPC) continue;
        const auto sliceOffset = be32(file, off + 8);
        const auto sliceSize = be32(file, off + 12);
        if (!rangeWithin(sliceOffset, sliceSize, file.size())) {
            error = "PowerPC Mach-O fat slice lies outside the file";
            return false;
        }
        slice = std::span<const std::uint8_t>(file).subspan(sliceOffset, sliceSize);
        info.sliceOffset = sliceOffset;
        info.sliceSize = sliceSize;
        return true;
    }
    error = "Mach-O fat file contains no 32-bit PowerPC slice";
    return false;
}

bool parse(const std::vector<std::uint8_t>& file, ParsedMachO& parsed, std::string& error) {
    parsed = {};
    parsed.fileBytes = file;
    if (!chooseSlice(parsed.fileBytes, parsed.bytes, parsed.info, error)) return false;
    const auto b = parsed.bytes;
    if (b.size() < 28 || be32(b, 0) != MH_MAGIC) {
        error = "selected Mach-O slice is not MH_MAGIC (32-bit big-endian)";
        return false;
    }
    if (be32(b, 4) != CPU_TYPE_POWERPC) {
        error = "Mach-O CPU type is not CPU_TYPE_POWERPC";
        return false;
    }
    parsed.info.fileType = be32(b, 12);
    const auto ncmds = be32(b, 16);
    const auto sizeofcmds = be32(b, 20);
    parsed.info.flags = be32(b, 24);
    if (parsed.info.fileType != MH_OBJECT && parsed.info.fileType != MH_EXECUTE &&
        parsed.info.fileType != MH_DYLIB && parsed.info.fileType != MH_BUNDLE) {
        error = "unsupported Mach-O file type " + std::to_string(parsed.info.fileType);
        return false;
    }
    if (!rangeWithin(28, sizeofcmds, b.size())) {
        error = "Mach-O load-command area lies outside the file";
        return false;
    }

    std::size_t commandOffset = 28;
    std::uint32_t sectionOrdinal = 1;
    for (std::uint32_t ci = 0; ci < ncmds; ++ci) {
        if (!rangeWithin(commandOffset, 8, b.size())) {
            error = "truncated Mach-O load command";
            return false;
        }
        const auto cmd = be32(b, commandOffset);
        const auto cmdsize = be32(b, commandOffset + 4);
        if (cmdsize < 8 || !rangeWithin(commandOffset, cmdsize, b.size())) {
            error = "invalid Mach-O load command size";
            return false;
        }
        if (cmd == LC_SEGMENT) {
            if (cmdsize < 56) {
                error = "truncated LC_SEGMENT";
                return false;
            }
            MachOSegmentInfo segment{};
            segment.name = fixedString(b, commandOffset + 8, 16);
            segment.vmAddress = be32(b, commandOffset + 24);
            segment.vmSize = be32(b, commandOffset + 28);
            segment.fileOffset = be32(b, commandOffset + 32);
            segment.fileSize = be32(b, commandOffset + 36);
            segment.maxProt = be32(b, commandOffset + 40);
            segment.initProt = be32(b, commandOffset + 44);
            const auto nsects = be32(b, commandOffset + 48);
            if (segment.fileSize > segment.vmSize ||
                !rangeWithin(segment.fileOffset, segment.fileSize, b.size())) {
                error = "invalid Mach-O segment file/memory range";
                return false;
            }
            if (56ULL + static_cast<std::uint64_t>(nsects) * 68ULL > cmdsize) {
                error = "LC_SEGMENT section table exceeds command size";
                return false;
            }
            parsed.info.segments.push_back(segment);
            for (std::uint32_t si = 0; si < nsects; ++si, ++sectionOrdinal) {
                const std::size_t off = commandOffset + 56 + static_cast<std::size_t>(si) * 68;
                MachOSectionInfo section{};
                section.ordinal = sectionOrdinal;
                section.sectionName = fixedString(b, off, 16);
                section.segmentName = fixedString(b, off + 16, 16);
                section.address = be32(b, off + 32);
                section.size = be32(b, off + 36);
                section.fileOffset = be32(b, off + 40);
                section.alignmentPower = be32(b, off + 44);
                section.relocationOffset = be32(b, off + 48);
                section.relocationCount = be32(b, off + 52);
                section.flags = be32(b, off + 56);
                if ((section.flags & 0xffU) != S_ZEROFILL && section.size != 0 &&
                    !rangeWithin(section.fileOffset, section.size, b.size())) {
                    error = "Mach-O section contents lie outside the file";
                    return false;
                }
                if (section.relocationCount != 0 &&
                    !rangeWithin(section.relocationOffset,
                                 static_cast<std::size_t>(section.relocationCount) * 8U,
                                 b.size())) {
                    error = "Mach-O relocation table lies outside the file";
                    return false;
                }
                parsed.info.sections.push_back(section);
            }
        } else if (cmd == LC_SYMTAB) {
            if (cmdsize < 24) {
                error = "truncated LC_SYMTAB";
                return false;
            }
            parsed.symtab.present = true;
            parsed.symtab.symoff = be32(b, commandOffset + 8);
            parsed.symtab.nsyms = be32(b, commandOffset + 12);
            parsed.symtab.stroff = be32(b, commandOffset + 16);
            parsed.symtab.strsize = be32(b, commandOffset + 20);
        } else if (cmd == LC_THREAD || cmd == LC_UNIXTHREAD) {
            std::size_t off = commandOffset + 8;
            const std::size_t end = commandOffset + cmdsize;
            while (off + 8 <= end) {
                const auto flavor = be32(b, off);
                const auto count = be32(b, off + 4);
                off += 8;
                const std::uint64_t stateBytes = static_cast<std::uint64_t>(count) * 4U;
                if (off + stateBytes > end) break;
                if (flavor == PPC_THREAD_STATE && count >= 1) {
                    parsed.threadPc = be32(b, off); // srr0 / program counter
                    break;
                }
                off += static_cast<std::size_t>(stateBytes);
            }
        } else if (cmd == LC_MAIN) {
            if (cmdsize >= 24) parsed.entryFileOffset = be64(b, commandOffset + 8);
        }
        commandOffset += cmdsize;
    }

    if (parsed.threadPc) parsed.info.entry = *parsed.threadPc;

    if (parsed.symtab.present) {
        if (!rangeWithin(parsed.symtab.symoff,
                         static_cast<std::size_t>(parsed.symtab.nsyms) * 12U, b.size()) ||
            !rangeWithin(parsed.symtab.stroff, parsed.symtab.strsize, b.size())) {
            error = "Mach-O symbol/string table lies outside the file";
            return false;
        }
        parsed.rawSymbols.reserve(parsed.symtab.nsyms);
        for (std::uint32_t i = 0; i < parsed.symtab.nsyms; ++i) {
            const std::size_t off = parsed.symtab.symoff + static_cast<std::size_t>(i) * 12U;
            RawSymbol raw{};
            const auto strx = be32(b, off);
            raw.nType = b[off + 4];
            raw.nSect = b[off + 5];
            raw.nDesc = be16(b, off + 6);
            raw.symbol.name = cstringAt(b, parsed.symtab.stroff, parsed.symtab.strsize, strx);
            raw.symbol.value = be32(b, off + 8);
            raw.symbol.sectionIndex = raw.nSect;
            raw.symbol.binding = (raw.nType & N_EXT) != 0 ? 1 : 0;
            raw.symbol.defined = (raw.nType & N_TYPE) != N_UNDF;
            raw.symbol.imported = (raw.nType & N_TYPE) == N_UNDF && !raw.symbol.name.empty();
            parsed.rawSymbols.push_back(raw);
            if (!raw.symbol.name.empty() && (raw.nType & N_STAB) == 0)
                parsed.info.symbols.push_back(raw.symbol);
        }
    }
    return true;
}

bool directRead32(const Memory& memory, std::uint32_t address, std::uint32_t& value) {
    const auto* region = memory.find(address, 4);
    if (!region) return false;
    const auto o = static_cast<std::size_t>(address - region->base);
    value = (static_cast<std::uint32_t>(region->bytes[o]) << 24U) |
            (static_cast<std::uint32_t>(region->bytes[o + 1]) << 16U) |
            (static_cast<std::uint32_t>(region->bytes[o + 2]) << 8U) |
            static_cast<std::uint32_t>(region->bytes[o + 3]);
    return true;
}

bool directWrite32(Memory& memory, std::uint32_t address, std::uint32_t value) {
    auto* region = memory.find(address, 4);
    if (!region) return false;
    const auto o = static_cast<std::size_t>(address - region->base);
    region->bytes[o] = static_cast<std::uint8_t>(value >> 24U);
    region->bytes[o + 1] = static_cast<std::uint8_t>(value >> 16U);
    region->bytes[o + 2] = static_cast<std::uint8_t>(value >> 8U);
    region->bytes[o + 3] = static_cast<std::uint8_t>(value);
    return true;
}

std::int32_t signExtend(std::uint32_t value, unsigned bits) noexcept {
    const std::uint32_t sign = 1U << (bits - 1U);
    return static_cast<std::int32_t>((value ^ sign) - sign);
}

bool fitsSigned(std::int64_t value, unsigned bits) noexcept {
    const auto lo = -(std::int64_t{1} << (bits - 1));
    const auto hi = (std::int64_t{1} << (bits - 1)) - 1;
    return value >= lo && value <= hi;
}

struct RuntimeSymbols {
    std::vector<std::uint32_t> addresses{};
    std::vector<bool> resolved{};
    std::vector<ImageSymbol> symbols{};
};

bool mapImage(const ParsedMachO& parsed,
              Memory& memory,
              MachOImageInfo& info,
              std::uint32_t imageBase,
              std::string& error) {
    if (info.fileType == MH_OBJECT) {
        std::uint32_t cursor = imageBase;
        for (auto& section : info.sections) {
            if (section.size == 0) continue;
            if (section.alignmentPower >= 31) {
                error = "Mach-O section alignment is too large";
                return false;
            }
            const std::uint32_t align = 1U << section.alignmentPower;
            cursor = alignUp(cursor, align);
            section.mappedAddress = cursor;
            MemoryPerm perms = MemoryPerm::Read | MemoryPerm::Write;
            if (section.segmentName == "__TEXT" || section.sectionName == "__text")
                perms = perms | MemoryPerm::Execute;
            if (!memory.map(cursor, section.size, perms,
                            "macho:" + section.segmentName + "," + section.sectionName)) {
                error = "failed to map Mach-O object section";
                return false;
            }
            if ((section.flags & 0xffU) != S_ZEROFILL && section.size != 0) {
                auto* region = memory.find(cursor, section.size);
                std::copy_n(parsed.bytes.begin() + static_cast<std::ptrdiff_t>(section.fileOffset),
                            section.size, region->bytes.begin());
            }
            cursor += section.size;
        }
        info.loadBias = imageBase;
        return true;
    }

    std::uint32_t bias = 0;
    if (info.fileType == MH_DYLIB) {
        std::uint32_t minVm = std::numeric_limits<std::uint32_t>::max();
        for (const auto& segment : info.segments) {
            if (segment.vmSize != 0) minVm = std::min(minVm, segment.vmAddress);
        }
        if (minVm == std::numeric_limits<std::uint32_t>::max() || imageBase < minVm) {
            error = "cannot derive Mach-O dylib load bias";
            return false;
        }
        bias = imageBase - minVm;
    }
    info.loadBias = bias;
    for (auto& segment : info.segments) {
        if (segment.vmSize == 0) continue;
        const std::uint64_t mapped64 = static_cast<std::uint64_t>(bias) + segment.vmAddress;
        if (mapped64 + segment.vmSize > 0x1'0000'0000ULL) {
            error = "Mach-O segment exceeds 32-bit address space after rebasing";
            return false;
        }
        segment.mappedAddress = static_cast<std::uint32_t>(mapped64);
        if (!memory.map(segment.mappedAddress, segment.vmSize, permsFromVm(segment.initProt),
                        "macho:" + segment.name)) {
            error = "failed to map Mach-O segment " + segment.name;
            return false;
        }
        if (segment.fileSize != 0) {
            auto* region = memory.find(segment.mappedAddress, segment.vmSize);
            std::copy_n(parsed.bytes.begin() + static_cast<std::ptrdiff_t>(segment.fileOffset),
                        segment.fileSize, region->bytes.begin());
        }
    }
    for (auto& section : info.sections) section.mappedAddress = bias + section.address;
    return true;
}

bool buildSymbols(const ParsedMachO& parsed,
                  MachOImageInfo& info,
                  const std::vector<SymbolBinding>& bindings,
                  RuntimeSymbols& runtime,
                  std::string& error) {
    runtime.addresses.resize(parsed.rawSymbols.size());
    runtime.resolved.resize(parsed.rawSymbols.size());
    runtime.symbols.resize(parsed.rawSymbols.size());
    info.symbols.clear();
    for (std::size_t i = 0; i < parsed.rawSymbols.size(); ++i) {
        const auto& raw = parsed.rawSymbols[i];
        auto symbol = raw.symbol;
        bool resolved = false;
        std::uint32_t address = 0;
        const auto kind = raw.nType & N_TYPE;
        if ((raw.nType & N_STAB) != 0) {
            resolved = true;
        } else if (kind == N_UNDF) {
            if (symbol.name.empty()) resolved = true;
            else if (findSymbolBinding(bindings, symbol.name, address)) resolved = true;
            else if ((raw.nDesc & N_WEAK_REF) != 0) resolved = true;
        } else if (kind == N_ABS) {
            address = symbol.value;
            resolved = true;
        } else if (kind == N_SECT && raw.nSect != 0 && raw.nSect <= info.sections.size()) {
            const auto& section = info.sections[raw.nSect - 1U];
            if (info.fileType == MH_OBJECT)
                address = section.mappedAddress + (symbol.value - section.address);
            else
                address = info.loadBias + symbol.value;
            resolved = true;
        }
        runtime.addresses[i] = address;
        runtime.resolved[i] = resolved;
        if (resolved) symbol.value = address;
        symbol.defined = kind != N_UNDF || resolved;
        symbol.imported = kind == N_UNDF;
        runtime.symbols[i] = symbol;
        if (!symbol.name.empty() && (raw.nType & N_STAB) == 0) info.symbols.push_back(symbol);
    }
    (void)error;
    return true;
}

bool resolveRelocTarget(const RuntimeSymbols& runtime,
                        const MachOImageInfo& info,
                        std::uint32_t symbolNum,
                        bool external,
                        std::uint32_t& target,
                        std::string& error) {
    if (external) {
        if (symbolNum >= runtime.addresses.size()) {
            error = "Mach-O relocation symbol index is outside LC_SYMTAB";
            return false;
        }
        if (!runtime.resolved[symbolNum]) {
            const auto& name = runtime.symbols[symbolNum].name;
            error = "unresolved Mach-O symbol: " +
                    (name.empty() ? std::string("<anonymous>") : name) +
                    " (supply --bind NAME=ADDRESS)";
            return false;
        }
        target = runtime.addresses[symbolNum];
        return true;
    }
    if (symbolNum == 0) {
        target = 0; // R_ABS
        return true;
    }
    if (symbolNum > info.sections.size()) {
        error = "Mach-O local relocation section ordinal is invalid";
        return false;
    }
    target = info.sections[symbolNum - 1U].mappedAddress;
    return true;
}

bool applyRelocations(const ParsedMachO& parsed,
                      Memory& memory,
                      const MachOImageInfo& info,
                      const RuntimeSymbols& runtime,
                      std::string& error) {
    for (const auto& section : info.sections) {
        for (std::uint32_t ri = 0; ri < section.relocationCount; ++ri) {
            const std::size_t off = section.relocationOffset + static_cast<std::size_t>(ri) * 8U;
            const std::uint32_t word0 = be32(parsed.bytes, off);
            const std::uint32_t word1 = be32(parsed.bytes, off + 4);
            if ((word0 & 0x80000000U) != 0) {
                error = "scattered PowerPC Mach-O relocations are not supported in v0.3";
                return false;
            }
            const std::int32_t rAddress = static_cast<std::int32_t>(word0);
            if (rAddress < 0) {
                error = "negative Mach-O relocation address is invalid for this loader";
                return false;
            }
            const std::uint32_t symbolNum = word1 >> 8U;
            const bool pcrel = ((word1 >> 7U) & 1U) != 0;
            const std::uint32_t length = (word1 >> 5U) & 3U;
            const bool external = ((word1 >> 4U) & 1U) != 0;
            const std::uint32_t type = word1 & 0x0fU;
            if (type == PPC_RELOC_PAIR) {
                error = "orphan PPC_RELOC_PAIR in Mach-O relocation table";
                return false;
            }
            const std::uint32_t place = section.mappedAddress + static_cast<std::uint32_t>(rAddress);
            std::uint32_t target = 0;
            if (!resolveRelocTarget(runtime, info, symbolNum, external, target, error)) return false;
            std::uint32_t instruction = 0;
            if (!directRead32(memory, place, instruction)) {
                error = "Mach-O relocation target is not mapped";
                return false;
            }

            if (type == PPC_RELOC_VANILLA) {
                if (length == 2) {
                    const std::int64_t addend = static_cast<std::int32_t>(instruction);
                    const std::int64_t value = static_cast<std::int64_t>(target) + addend -
                                               (pcrel ? static_cast<std::int64_t>(place) : 0);
                    if (!directWrite32(memory, place, static_cast<std::uint32_t>(value))) return false;
                } else {
                    error = "Mach-O PPC_RELOC_VANILLA currently requires 32-bit length";
                    return false;
                }
            } else if (type == PPC_RELOC_BR24) {
                const auto addend = signExtend(instruction & 0x03fffffcU, 26);
                const std::int64_t value = static_cast<std::int64_t>(target) + addend -
                                           (pcrel ? static_cast<std::int64_t>(place) : 0);
                if ((value & 3) != 0 || !fitsSigned(value, 26)) {
                    error = "Mach-O PPC_RELOC_BR24 is out of range";
                    return false;
                }
                if (!directWrite32(memory, place,
                                   (instruction & ~0x03fffffcU) |
                                   (static_cast<std::uint32_t>(value) & 0x03fffffcU))) return false;
            } else if (type == PPC_RELOC_BR14) {
                const auto addend = signExtend(instruction & 0x0000fffcU, 16);
                const std::int64_t value = static_cast<std::int64_t>(target) + addend -
                                           (pcrel ? static_cast<std::int64_t>(place) : 0);
                if ((value & 3) != 0 || !fitsSigned(value, 16)) {
                    error = "Mach-O PPC_RELOC_BR14 is out of range";
                    return false;
                }
                if (!directWrite32(memory, place,
                                   (instruction & ~0x0000fffcU) |
                                   (static_cast<std::uint32_t>(value) & 0x0000fffcU))) return false;
            } else if (type == PPC_RELOC_HI16 || type == PPC_RELOC_LO16 ||
                       type == PPC_RELOC_HA16 || type == PPC_RELOC_LO14) {
                if (ri + 1 >= section.relocationCount) {
                    error = "paired PowerPC Mach-O relocation is missing PPC_RELOC_PAIR";
                    return false;
                }
                const std::size_t poff = section.relocationOffset + static_cast<std::size_t>(ri + 1U) * 8U;
                const std::uint32_t pair0 = be32(parsed.bytes, poff);
                const std::uint32_t pair1 = be32(parsed.bytes, poff + 4);
                if ((pair0 & 0x80000000U) != 0 || (pair1 & 0x0fU) != PPC_RELOC_PAIR) {
                    error = "paired PowerPC Mach-O relocation is followed by a non-pair entry";
                    return false;
                }
                ++ri;
                const std::uint16_t currentHalf = static_cast<std::uint16_t>(instruction & 0xffffU);
                const std::uint16_t otherHalf = static_cast<std::uint16_t>(pair0 & 0xffffU);
                std::int64_t addend = 0;
                if (type == PPC_RELOC_HI16 || type == PPC_RELOC_HA16)
                    addend = (static_cast<std::uint32_t>(currentHalf) << 16U) | otherHalf;
                else
                    addend = (static_cast<std::uint32_t>(otherHalf) << 16U) | currentHalf;
                const std::int64_t value = static_cast<std::int64_t>(target) +
                                           static_cast<std::int32_t>(addend) -
                                           (pcrel ? static_cast<std::int64_t>(place) : 0);
                std::uint16_t patched = 0;
                if (type == PPC_RELOC_HI16) patched = static_cast<std::uint16_t>(value >> 16U);
                else if (type == PPC_RELOC_HA16) patched = static_cast<std::uint16_t>((value + 0x8000) >> 16U);
                else if (type == PPC_RELOC_LO14) patched = static_cast<std::uint16_t>(value) & 0xfffcU;
                else patched = static_cast<std::uint16_t>(value);
                if (!directWrite32(memory, place, (instruction & 0xffff0000U) | patched)) return false;
            } else {
                std::ostringstream out;
                out << "unsupported PowerPC Mach-O relocation type " << type;
                error = out.str();
                return false;
            }
        }
    }
    return true;
}

std::uint32_t discoverEntry(const ParsedMachO& parsed, const MachOImageInfo& info) {
    if (parsed.threadPc) return info.loadBias + *parsed.threadPc;
    if (parsed.entryFileOffset) {
        for (const auto& segment : info.segments) {
            const std::uint64_t start = segment.fileOffset;
            const std::uint64_t end = start + segment.fileSize;
            if (*parsed.entryFileOffset >= start && *parsed.entryFileOffset < end) {
                return segment.mappedAddress +
                       static_cast<std::uint32_t>(*parsed.entryFileOffset - start);
            }
        }
    }
    for (const char* candidate : {"_main", "_start", "main", "start"}) {
        if (const auto* symbol = findImageSymbol(info.symbols, candidate); symbol && symbol->defined)
            return symbol->value;
    }
    if (info.fileType == MH_OBJECT) {
        for (const auto& section : info.sections) {
            if (section.sectionName == "__text" && section.size != 0) return section.mappedAddress;
        }
    }
    return 0;
}

} // namespace

bool MachOLoader::inspectFile(const std::string& path,
                              MachOImageInfo& info,
                              std::string& error) {
    std::vector<std::uint8_t> bytes;
    if (!readFile(path, bytes, error)) return false;
    ParsedMachO parsed{};
    if (!parse(bytes, parsed, error)) return false;
    info = std::move(parsed.info);
    return true;
}

bool MachOLoader::loadFile(const std::string& path,
                           Memory& memory,
                           MachOImageInfo& info,
                           std::string& error,
                           std::uint32_t imageBase,
                           const std::vector<SymbolBinding>& bindings) {
    std::vector<std::uint8_t> bytes;
    if (!readFile(path, bytes, error)) return false;
    ParsedMachO parsed{};
    if (!parse(bytes, parsed, error)) return false;
    info = parsed.info;
    if (!mapImage(parsed, memory, info, imageBase, error)) return false;
    RuntimeSymbols runtime{};
    if (!buildSymbols(parsed, info, bindings, runtime, error)) return false;
    if (!applyRelocations(parsed, memory, info, runtime, error)) return false;
    info.entry = discoverEntry(parsed, info);
    return true;
}

std::string machoFileTypeName(std::uint32_t type) {
    switch (type) {
    case MH_OBJECT: return "MH_OBJECT";
    case MH_EXECUTE: return "MH_EXECUTE";
    case MH_DYLIB: return "MH_DYLIB";
    case MH_BUNDLE: return "MH_BUNDLE";
    default: return "UNKNOWN";
    }
}

std::string machoVmProtection(std::uint32_t protection) {
    std::string out;
    out += (protection & VM_PROT_READ) != 0 ? 'R' : '-';
    out += (protection & VM_PROT_WRITE) != 0 ? 'W' : '-';
    out += (protection & VM_PROT_EXECUTE) != 0 ? 'X' : '-';
    return out;
}

} // namespace ppclab::ppc
