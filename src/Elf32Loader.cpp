// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/Elf32Loader.hpp"

#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iterator>
#include <limits>
#include <map>
#include <span>
#include <sstream>
#include <unordered_map>
#include <utility>

namespace ppclab::ppc {
namespace {

constexpr std::size_t kElf32HeaderSize = 52;
constexpr std::size_t kProgramHeaderSize = 32;
constexpr std::size_t kSectionHeaderSize = 40;
constexpr std::size_t kSymbolSize = 16;
constexpr std::size_t kRelSize = 8;
constexpr std::size_t kRelaSize = 12;
constexpr std::uint16_t kEtRel = 1;
constexpr std::uint16_t kEtExec = 2;
constexpr std::uint16_t kEtDyn = 3;
constexpr std::uint16_t kEmPpc = 20;
constexpr std::uint32_t kPtLoad = 1;
constexpr std::uint32_t kPfX = 1;
constexpr std::uint32_t kPfW = 2;
constexpr std::uint32_t kPfR = 4;
constexpr std::uint32_t kShtSymtab = 2;
constexpr std::uint32_t kShtStrtab = 3;
constexpr std::uint32_t kShtRela = 4;
constexpr std::uint32_t kShtNobits = 8;
constexpr std::uint32_t kShtRel = 9;
constexpr std::uint32_t kShtDynsym = 11;
constexpr std::uint32_t kShfWrite = 0x1;
constexpr std::uint32_t kShfAlloc = 0x2;
constexpr std::uint32_t kShfExecinstr = 0x4;
constexpr std::uint16_t kShnUndef = 0;
constexpr std::uint16_t kShnAbs = 0xfff1;
constexpr std::uint16_t kShnCommon = 0xfff2;
constexpr std::uint8_t kStbWeak = 2;

// System V PowerPC ABI relocation numbers used by the generic loader.
constexpr std::uint32_t R_PPC_NONE = 0;
constexpr std::uint32_t R_PPC_ADDR32 = 1;
constexpr std::uint32_t R_PPC_ADDR24 = 2;
constexpr std::uint32_t R_PPC_ADDR16 = 3;
constexpr std::uint32_t R_PPC_ADDR16_LO = 4;
constexpr std::uint32_t R_PPC_ADDR16_HI = 5;
constexpr std::uint32_t R_PPC_ADDR16_HA = 6;
constexpr std::uint32_t R_PPC_ADDR14 = 7;
constexpr std::uint32_t R_PPC_ADDR14_BRTAKEN = 8;
constexpr std::uint32_t R_PPC_ADDR14_BRNTAKEN = 9;
constexpr std::uint32_t R_PPC_REL24 = 10;
constexpr std::uint32_t R_PPC_REL14 = 11;
constexpr std::uint32_t R_PPC_REL14_BRTAKEN = 12;
constexpr std::uint32_t R_PPC_REL14_BRNTAKEN = 13;
constexpr std::uint32_t R_PPC_PLTREL24 = 18;
constexpr std::uint32_t R_PPC_COPY = 19;
constexpr std::uint32_t R_PPC_GLOB_DAT = 20;
constexpr std::uint32_t R_PPC_JMP_SLOT = 21;
constexpr std::uint32_t R_PPC_RELATIVE = 22;
constexpr std::uint32_t R_PPC_LOCAL24PC = 23;
constexpr std::uint32_t R_PPC_UADDR32 = 24;
constexpr std::uint32_t R_PPC_UADDR16 = 25;
constexpr std::uint32_t R_PPC_REL32 = 26;
constexpr std::uint32_t R_PPC_PLT32 = 27;
constexpr std::uint32_t R_PPC_PLTREL32 = 28;
constexpr std::uint32_t R_PPC_SECTOFF = 33;
constexpr std::uint32_t R_PPC_SECTOFF_LO = 34;
constexpr std::uint32_t R_PPC_SECTOFF_HI = 35;
constexpr std::uint32_t R_PPC_SECTOFF_HA = 36;

struct RawSection {
    Elf32SectionInfo info{};
    std::uint32_t nameOffset = 0;
};

struct RawSymbol {
    ImageSymbol publicSymbol{};
    std::uint32_t nameOffset = 0;
    std::uint16_t shndx = 0;
};

struct ParsedElf {
    Elf32ImageInfo publicInfo{};
    std::vector<std::uint8_t> bytes{};
    std::vector<RawSection> sections{};
    std::unordered_map<std::uint32_t, std::vector<RawSymbol>> symbolTables{};
};

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

std::uint16_t be16(std::span<const std::uint8_t> b, std::size_t off) noexcept {
    return static_cast<std::uint16_t>((static_cast<std::uint16_t>(b[off]) << 8U) |
                                      static_cast<std::uint16_t>(b[off + 1]));
}

std::uint32_t be32(std::span<const std::uint8_t> b, std::size_t off) noexcept {
    return (static_cast<std::uint32_t>(b[off]) << 24U) |
           (static_cast<std::uint32_t>(b[off + 1]) << 16U) |
           (static_cast<std::uint32_t>(b[off + 2]) << 8U) |
           static_cast<std::uint32_t>(b[off + 3]);
}

std::int32_t beS32(std::span<const std::uint8_t> b, std::size_t off) noexcept {
    return static_cast<std::int32_t>(be32(b, off));
}

std::uint32_t alignUp(std::uint32_t value, std::uint32_t alignment) noexcept {
    if (alignment <= 1) return value;
    const std::uint64_t a = alignment;
    const std::uint64_t v = value;
    return static_cast<std::uint32_t>((v + a - 1U) & ~(a - 1U));
}

std::string cstringAt(std::span<const std::uint8_t> bytes,
                      std::size_t base,
                      std::size_t size,
                      std::uint32_t offset) {
    if (offset >= size || base + offset >= bytes.size()) return {};
    const std::size_t start = base + offset;
    const std::size_t limit = std::min(bytes.size(), base + size);
    std::size_t end = start;
    while (end < limit && bytes[end] != 0) ++end;
    return std::string(reinterpret_cast<const char*>(bytes.data() + start), end - start);
}

MemoryPerm segmentPerms(std::uint32_t flags) noexcept {
    MemoryPerm perms = MemoryPerm::None;
    if ((flags & (kPfR | kPfX)) != 0) perms = perms | MemoryPerm::Read;
    if ((flags & kPfW) != 0) perms = perms | MemoryPerm::Write;
    if ((flags & kPfX) != 0) perms = perms | MemoryPerm::Execute;
    return perms;
}

MemoryPerm sectionPerms(std::uint32_t flags) noexcept {
    MemoryPerm perms = MemoryPerm::Read;
    if ((flags & kShfWrite) != 0) perms = perms | MemoryPerm::Write;
    if ((flags & kShfExecinstr) != 0) perms = perms | MemoryPerm::Execute;
    return perms;
}

bool parse(const std::vector<std::uint8_t>& bytes, ParsedElf& parsed, std::string& error) {
    parsed = {};
    parsed.bytes = bytes;
    auto& info = parsed.publicInfo;
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
    info.originalEntry = be32(bytes, 24);
    info.entry = info.originalEntry;
    const auto phoff = be32(bytes, 28);
    const auto shoff = be32(bytes, 32);
    info.flags = be32(bytes, 36);
    const auto ehsize = be16(bytes, 40);
    const auto phentsize = be16(bytes, 42);
    const auto phnum = be16(bytes, 44);
    const auto shentsize = be16(bytes, 46);
    const auto shnum = be16(bytes, 48);
    const auto shstrndx = be16(bytes, 50);

    if (info.machine != kEmPpc) {
        error = "unsupported ELF machine: expected EM_PPC (20)";
        return false;
    }
    if (info.type != kEtExec && info.type != kEtDyn && info.type != kEtRel) {
        std::ostringstream out;
        out << "unsupported ELF type " << info.type << ": expected ET_EXEC, ET_DYN or ET_REL";
        error = out.str();
        return false;
    }
    if (ehsize < kElf32HeaderSize) {
        error = "invalid ELF header size";
        return false;
    }

    if (phnum != 0) {
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
            if (be32(bytes, off) != kPtLoad) continue;
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
            info.loadSegments.push_back(segment);
        }
    }

    if (shnum != 0) {
        if (shentsize < kSectionHeaderSize) {
            error = "ELF section-header entries are too small";
            return false;
        }
        const std::uint64_t shBytes = static_cast<std::uint64_t>(shentsize) * shnum;
        if (shBytes > std::numeric_limits<std::size_t>::max() ||
            !rangeWithin(shoff, static_cast<std::size_t>(shBytes), bytes.size())) {
            error = "ELF section-header table lies outside the file";
            return false;
        }
        parsed.sections.reserve(shnum);
        for (std::uint32_t i = 0; i < shnum; ++i) {
            const std::size_t off = static_cast<std::size_t>(shoff) +
                                    static_cast<std::size_t>(i) * shentsize;
            RawSection raw{};
            raw.info.index = i;
            raw.nameOffset = be32(bytes, off + 0);
            raw.info.type = be32(bytes, off + 4);
            raw.info.flags = be32(bytes, off + 8);
            raw.info.address = be32(bytes, off + 12);
            raw.info.fileOffset = be32(bytes, off + 16);
            raw.info.size = be32(bytes, off + 20);
            raw.info.link = be32(bytes, off + 24);
            raw.info.info = be32(bytes, off + 28);
            raw.info.alignment = be32(bytes, off + 32);
            raw.info.entrySize = be32(bytes, off + 36);
            if (raw.info.type != kShtNobits && raw.info.size != 0 &&
                !rangeWithin(raw.info.fileOffset, raw.info.size, bytes.size())) {
                error = "ELF section file range lies outside the file";
                return false;
            }
            parsed.sections.push_back(raw);
        }

        if (shstrndx < parsed.sections.size()) {
            const auto& strings = parsed.sections[shstrndx].info;
            if (strings.type == kShtStrtab &&
                rangeWithin(strings.fileOffset, strings.size, bytes.size())) {
                for (auto& section : parsed.sections) {
                    section.info.name = cstringAt(bytes, strings.fileOffset, strings.size,
                                                  section.nameOffset);
                }
            }
        }

        for (const auto& section : parsed.sections) info.sections.push_back(section.info);

        for (const auto& section : parsed.sections) {
            if (section.info.type != kShtSymtab && section.info.type != kShtDynsym) continue;
            const std::uint32_t entsize = section.info.entrySize != 0 ? section.info.entrySize : kSymbolSize;
            if (entsize < kSymbolSize || section.info.size % entsize != 0 ||
                section.info.link >= parsed.sections.size()) {
                error = "invalid ELF symbol table";
                return false;
            }
            const auto& stringSection = parsed.sections[section.info.link].info;
            if (stringSection.type != kShtStrtab) {
                error = "ELF symbol table links to a non-string section";
                return false;
            }
            std::vector<RawSymbol> table;
            const auto count = section.info.size / entsize;
            table.reserve(count);
            for (std::uint32_t i = 0; i < count; ++i) {
                const std::size_t off = static_cast<std::size_t>(section.info.fileOffset) +
                                        static_cast<std::size_t>(i) * entsize;
                RawSymbol raw{};
                raw.nameOffset = be32(bytes, off + 0);
                raw.publicSymbol.name = cstringAt(bytes, stringSection.fileOffset,
                                                   stringSection.size, raw.nameOffset);
                raw.publicSymbol.value = be32(bytes, off + 4);
                raw.publicSymbol.size = be32(bytes, off + 8);
                const auto stInfo = bytes[off + 12];
                raw.publicSymbol.binding = stInfo >> 4U;
                raw.publicSymbol.type = stInfo & 0x0fU;
                raw.shndx = be16(bytes, off + 14);
                raw.publicSymbol.sectionIndex = raw.shndx;
                raw.publicSymbol.defined = raw.shndx != kShnUndef;
                raw.publicSymbol.imported = raw.shndx == kShnUndef && !raw.publicSymbol.name.empty();
                table.push_back(raw);
                if (!raw.publicSymbol.name.empty()) info.symbols.push_back(raw.publicSymbol);
            }
            parsed.symbolTables[section.info.index] = std::move(table);
        }

        for (const auto& section : parsed.sections) {
            if (section.info.type != kShtRel && section.info.type != kShtRela) continue;
            const std::uint32_t defaultSize = section.info.type == kShtRela ? kRelaSize : kRelSize;
            const std::uint32_t entsize = section.info.entrySize != 0 ? section.info.entrySize : defaultSize;
            if (entsize < defaultSize || section.info.size % entsize != 0) {
                error = "invalid ELF relocation section";
                return false;
            }
            info.relocationCount += section.info.size / entsize;
        }
    }

    if ((info.type == kEtExec || info.type == kEtDyn) && info.loadSegments.empty()) {
        error = "ELF executable/shared image contains no non-empty PT_LOAD segments";
        return false;
    }
    if (info.type == kEtRel) {
        bool hasAlloc = false;
        for (const auto& section : parsed.sections) {
            if ((section.info.flags & kShfAlloc) != 0 && section.info.size != 0) hasAlloc = true;
        }
        if (!hasAlloc) {
            error = "ELF ET_REL contains no allocatable sections";
            return false;
        }
    }
    return true;
}

bool directRead32(const Memory& memory, std::uint32_t address, std::uint32_t& value) {
    const auto* region = memory.find(address, 4);
    if (!region) return false;
    const auto off = static_cast<std::size_t>(address - region->base);
    value = (static_cast<std::uint32_t>(region->bytes[off]) << 24U) |
            (static_cast<std::uint32_t>(region->bytes[off + 1]) << 16U) |
            (static_cast<std::uint32_t>(region->bytes[off + 2]) << 8U) |
            static_cast<std::uint32_t>(region->bytes[off + 3]);
    return true;
}

bool directRead16(const Memory& memory, std::uint32_t address, std::uint16_t& value) {
    const auto* region = memory.find(address, 2);
    if (!region) return false;
    const auto off = static_cast<std::size_t>(address - region->base);
    value = static_cast<std::uint16_t>((static_cast<std::uint16_t>(region->bytes[off]) << 8U) |
                                       region->bytes[off + 1]);
    return true;
}

bool directWrite32(Memory& memory, std::uint32_t address, std::uint32_t value) {
    auto* region = memory.find(address, 4);
    if (!region) return false;
    const auto off = static_cast<std::size_t>(address - region->base);
    region->bytes[off + 0] = static_cast<std::uint8_t>(value >> 24U);
    region->bytes[off + 1] = static_cast<std::uint8_t>(value >> 16U);
    region->bytes[off + 2] = static_cast<std::uint8_t>(value >> 8U);
    region->bytes[off + 3] = static_cast<std::uint8_t>(value);
    return true;
}

bool directWrite16(Memory& memory, std::uint32_t address, std::uint16_t value) {
    auto* region = memory.find(address, 2);
    if (!region) return false;
    const auto off = static_cast<std::size_t>(address - region->base);
    region->bytes[off + 0] = static_cast<std::uint8_t>(value >> 8U);
    region->bytes[off + 1] = static_cast<std::uint8_t>(value);
    return true;
}

std::int32_t signExtend(std::uint32_t value, unsigned bits) noexcept {
    const std::uint32_t sign = 1U << (bits - 1U);
    return static_cast<std::int32_t>((value ^ sign) - sign);
}

struct RuntimeSymbolTable {
    std::vector<std::uint32_t> addresses{};
    std::vector<bool> resolved{};
    std::vector<std::uint16_t> shndx{};
    std::vector<ImageSymbol> symbols{};
};

bool buildRuntimeSymbols(const ParsedElf& parsed,
                         std::uint32_t bias,
                         const std::vector<SymbolBinding>& bindings,
                         std::unordered_map<std::uint32_t, RuntimeSymbolTable>& runtime,
                         Elf32ImageInfo& info,
                         std::string& error) {
    std::size_t publicCursor = 0;
    for (const auto& [tableIndex, table] : parsed.symbolTables) {
        RuntimeSymbolTable rt{};
        rt.addresses.resize(table.size());
        rt.resolved.resize(table.size());
        rt.shndx.resize(table.size());
        rt.symbols.resize(table.size());
        for (std::size_t i = 0; i < table.size(); ++i) {
            const auto& raw = table[i];
            auto symbol = raw.publicSymbol;
            rt.shndx[i] = raw.shndx;
            bool resolved = false;
            std::uint32_t address = 0;
            if (raw.shndx == kShnUndef) {
                if (symbol.name.empty()) {
                    resolved = true;
                } else if (findSymbolBinding(bindings, symbol.name, address)) {
                    resolved = true;
                } else if (symbol.binding == kStbWeak) {
                    resolved = true;
                    address = 0;
                }
            } else if (raw.shndx == kShnAbs) {
                address = symbol.value;
                resolved = true;
            } else if (raw.shndx == kShnCommon) {
                // COMMON allocation is deliberately deferred until a concrete target needs it.
            } else if (raw.shndx < info.sections.size()) {
                if (parsed.publicInfo.type == kEtRel) {
                    address = info.sections[raw.shndx].mappedAddress + symbol.value;
                } else {
                    address = bias + symbol.value;
                }
                resolved = true;
            }
            if (resolved) symbol.value = address;
            symbol.defined = raw.shndx != kShnUndef || resolved;
            symbol.imported = raw.shndx == kShnUndef;
            rt.addresses[i] = address;
            rt.resolved[i] = resolved;
            rt.symbols[i] = symbol;
        }
        runtime[tableIndex] = std::move(rt);
    }

    // Replace inspection-time raw symbol values with runtime values in stable table order.
    info.symbols.clear();
    std::vector<std::uint32_t> tableKeys;
    tableKeys.reserve(runtime.size());
    for (const auto& [key, _] : runtime) tableKeys.push_back(key);
    std::sort(tableKeys.begin(), tableKeys.end());
    for (const auto key : tableKeys) {
        for (const auto& symbol : runtime[key].symbols) {
            if (!symbol.name.empty()) info.symbols.push_back(symbol);
        }
    }
    (void)publicCursor;
    (void)error;
    return true;
}

bool relocationSymbol(const RuntimeSymbolTable& table,
                      std::uint32_t index,
                      std::uint32_t& address,
                      const ImageSymbol*& symbol,
                      std::string& error) {
    if (index >= table.addresses.size()) {
        error = "ELF relocation references symbol index outside its symbol table";
        return false;
    }
    symbol = &table.symbols[index];
    if (!table.resolved[index]) {
        error = "unresolved ELF relocation symbol: " +
                (symbol->name.empty() ? std::string("<anonymous>") : symbol->name) +
                " (supply --bind NAME=ADDRESS)";
        return false;
    }
    address = table.addresses[index];
    return true;
}

bool fitsSigned(std::int64_t value, unsigned bits) noexcept {
    const std::int64_t lo = -(std::int64_t{1} << (bits - 1));
    const std::int64_t hi = (std::int64_t{1} << (bits - 1)) - 1;
    return value >= lo && value <= hi;
}

bool applyOneRelocation(Memory& memory,
                        std::uint32_t place,
                        std::uint32_t type,
                        std::uint32_t symbolAddress,
                        const ImageSymbol* symbol,
                        std::int32_t explicitAddend,
                        bool hasExplicitAddend,
                        std::uint32_t bias,
                        const Elf32ImageInfo& info,
                        std::string& error) {
    std::uint32_t word = 0;
    std::uint16_t half = 0;
    std::int64_t addend = explicitAddend;

    auto needWordAddend = [&]() -> bool {
        if (hasExplicitAddend) return true;
        if (!directRead32(memory, place, word)) {
            error = "ELF relocation target is not mapped";
            return false;
        }
        addend = static_cast<std::int32_t>(word);
        return true;
    };
    auto needHalfAddend = [&]() -> bool {
        if (hasExplicitAddend) return true;
        if (!directRead16(memory, place, half)) {
            error = "ELF relocation target is not mapped";
            return false;
        }
        addend = static_cast<std::int16_t>(half);
        return true;
    };

    const std::int64_t S = symbolAddress;
    const std::int64_t P = place;
    const std::int64_t B = bias;
    auto writeBranch24 = [&](std::int64_t value) -> bool {
        if ((value & 3) != 0 || !fitsSigned(value, 26)) {
            error = "ELF PPC 24-bit branch relocation is out of range/alignment";
            return false;
        }
        if (!directRead32(memory, place, word)) {
            error = "ELF branch relocation target is not mapped";
            return false;
        }
        return directWrite32(memory, place,
                             (word & ~0x03fffffcU) |
                             (static_cast<std::uint32_t>(value) & 0x03fffffcU));
    };
    auto writeBranch14 = [&](std::int64_t value) -> bool {
        if ((value & 3) != 0 || !fitsSigned(value, 16)) {
            error = "ELF PPC 14-bit branch relocation is out of range/alignment";
            return false;
        }
        if (!directRead32(memory, place, word)) {
            error = "ELF branch relocation target is not mapped";
            return false;
        }
        return directWrite32(memory, place,
                             (word & ~0x0000fffcU) |
                             (static_cast<std::uint32_t>(value) & 0x0000fffcU));
    };

    switch (type) {
    case R_PPC_NONE:
        return true;
    case R_PPC_ADDR32:
    case R_PPC_UADDR32:
    case R_PPC_GLOB_DAT:
    case R_PPC_JMP_SLOT:
    case R_PPC_PLT32:
        if (!needWordAddend()) return false;
        return directWrite32(memory, place, static_cast<std::uint32_t>(S + addend));
    case R_PPC_ADDR16:
    case R_PPC_UADDR16:
        if (!needHalfAddend()) return false;
        return directWrite16(memory, place, static_cast<std::uint16_t>(S + addend));
    case R_PPC_ADDR16_LO:
        if (!needHalfAddend()) return false;
        return directWrite16(memory, place, static_cast<std::uint16_t>(S + addend));
    case R_PPC_ADDR16_HI:
        if (!needHalfAddend()) return false;
        return directWrite16(memory, place, static_cast<std::uint16_t>((S + addend) >> 16U));
    case R_PPC_ADDR16_HA:
        if (!needHalfAddend()) return false;
        return directWrite16(memory, place,
                             static_cast<std::uint16_t>((S + addend + 0x8000) >> 16U));
    case R_PPC_ADDR24:
        if (!hasExplicitAddend) {
            if (!directRead32(memory, place, word)) {
                error = "ELF branch relocation target is not mapped";
                return false;
            }
            addend = signExtend(word & 0x03fffffcU, 26);
        }
        return writeBranch24(S + addend);
    case R_PPC_REL24:
    case R_PPC_PLTREL24:
    case R_PPC_LOCAL24PC:
        if (!hasExplicitAddend) {
            if (!directRead32(memory, place, word)) {
                error = "ELF branch relocation target is not mapped";
                return false;
            }
            addend = signExtend(word & 0x03fffffcU, 26);
        }
        return writeBranch24(S + addend - P);
    case R_PPC_ADDR14:
    case R_PPC_ADDR14_BRTAKEN:
    case R_PPC_ADDR14_BRNTAKEN:
        if (!hasExplicitAddend) {
            if (!directRead32(memory, place, word)) {
                error = "ELF branch relocation target is not mapped";
                return false;
            }
            addend = signExtend(word & 0x0000fffcU, 16);
        }
        return writeBranch14(S + addend);
    case R_PPC_REL14:
    case R_PPC_REL14_BRTAKEN:
    case R_PPC_REL14_BRNTAKEN:
        if (!hasExplicitAddend) {
            if (!directRead32(memory, place, word)) {
                error = "ELF branch relocation target is not mapped";
                return false;
            }
            addend = signExtend(word & 0x0000fffcU, 16);
        }
        return writeBranch14(S + addend - P);
    case R_PPC_RELATIVE:
        if (!needWordAddend()) return false;
        return directWrite32(memory, place, static_cast<std::uint32_t>(B + addend));
    case R_PPC_REL32:
    case R_PPC_PLTREL32:
        if (!needWordAddend()) return false;
        return directWrite32(memory, place, static_cast<std::uint32_t>(S + addend - P));
    case R_PPC_SECTOFF:
    case R_PPC_SECTOFF_LO:
    case R_PPC_SECTOFF_HI:
    case R_PPC_SECTOFF_HA: {
        if (!symbol || symbol->sectionIndex >= info.sections.size()) {
            error = "ELF section-offset relocation has no concrete symbol section";
            return false;
        }
        const std::int64_t sectionBase = info.sections[symbol->sectionIndex].mappedAddress;
        if (type == R_PPC_SECTOFF) {
            if (!needWordAddend()) return false;
            return directWrite32(memory, place, static_cast<std::uint32_t>(S + addend - sectionBase));
        }
        if (!needHalfAddend()) return false;
        const std::int64_t value = S + addend - sectionBase;
        if (type == R_PPC_SECTOFF_LO)
            return directWrite16(memory, place, static_cast<std::uint16_t>(value));
        if (type == R_PPC_SECTOFF_HI)
            return directWrite16(memory, place, static_cast<std::uint16_t>(value >> 16U));
        return directWrite16(memory, place, static_cast<std::uint16_t>((value + 0x8000) >> 16U));
    }
    case R_PPC_COPY:
        error = "R_PPC_COPY requires dynamic-linker object-copy semantics and is not supported";
        return false;
    default: {
        std::ostringstream out;
        out << "unsupported ELF PowerPC relocation type " << type;
        error = out.str();
        return false;
    }
    }
}

bool applyRelocations(const ParsedElf& parsed,
                      Memory& memory,
                      Elf32ImageInfo& info,
                      const std::unordered_map<std::uint32_t, RuntimeSymbolTable>& runtime,
                      std::string& error) {
    for (const auto& rawSection : parsed.sections) {
        const auto& relocSection = rawSection.info;
        if (relocSection.type != kShtRel && relocSection.type != kShtRela) continue;
        const auto tableIt = runtime.find(relocSection.link);
        if (tableIt == runtime.end()) {
            error = "ELF relocation section does not link to a parsed symbol table";
            return false;
        }
        if (relocSection.info >= info.sections.size()) {
            error = "ELF relocation section has invalid target section index";
            return false;
        }
        const std::uint32_t defaultSize = relocSection.type == kShtRela ? kRelaSize : kRelSize;
        const std::uint32_t entsize = relocSection.entrySize != 0 ? relocSection.entrySize : defaultSize;
        const std::uint32_t count = relocSection.size / entsize;
        for (std::uint32_t i = 0; i < count; ++i) {
            const std::size_t off = static_cast<std::size_t>(relocSection.fileOffset) +
                                    static_cast<std::size_t>(i) * entsize;
            const std::uint32_t rOffset = be32(parsed.bytes, off + 0);
            const std::uint32_t rInfo = be32(parsed.bytes, off + 4);
            const std::uint32_t symbolIndex = rInfo >> 8U;
            const std::uint32_t type = rInfo & 0xffU;
            const bool rela = relocSection.type == kShtRela;
            const std::int32_t addend = rela ? beS32(parsed.bytes, off + 8) : 0;
            std::uint32_t place = 0;
            if (info.type == kEtRel) {
                place = info.sections[relocSection.info].mappedAddress + rOffset;
            } else {
                place = info.loadBias + rOffset;
            }
            std::uint32_t symbolAddress = 0;
            const ImageSymbol* symbol = nullptr;
            if (type != R_PPC_RELATIVE && type != R_PPC_NONE) {
                if (!relocationSymbol(tableIt->second, symbolIndex, symbolAddress, symbol, error)) return false;
            }
            if (!applyOneRelocation(memory, place, type, symbolAddress, symbol, addend, rela,
                                    info.loadBias, info, error)) {
                std::ostringstream context;
                context << error << " (relocation section " << relocSection.index
                        << ", entry " << i << ", place 0x" << std::hex << place << ')';
                error = context.str();
                return false;
            }
        }
    }
    return true;
}

bool mapLoadSegment(const ParsedElf& parsed,
                    Memory& memory,
                    Elf32SegmentInfo& segment,
                    std::uint32_t bias,
                    std::string& error) {
    const std::uint64_t mapped64 = static_cast<std::uint64_t>(bias) + segment.virtualAddress;
    const std::uint64_t end64 = mapped64 + segment.memorySize;
    if (end64 > 0x1'0000'0000ULL) {
        error = "ELF PT_LOAD rebased range exceeds 32-bit address space";
        return false;
    }
    segment.mappedAddress = static_cast<std::uint32_t>(mapped64);
    std::ostringstream name;
    name << "elf:PT_LOAD[" << segment.index << ']';
    if (!memory.map(segment.mappedAddress, segment.memorySize, segmentPerms(segment.flags), name.str())) {
        std::ostringstream out;
        out << "failed to map ELF PT_LOAD[" << segment.index << "] at 0x"
            << std::hex << segment.mappedAddress << " size 0x" << segment.memorySize
            << " (overlap or invalid range)";
        error = out.str();
        return false;
    }
    if (segment.fileSize != 0) {
        auto* region = memory.find(segment.mappedAddress, segment.memorySize);
        if (!region) {
            error = "internal error locating newly mapped ELF segment";
            return false;
        }
        std::copy_n(parsed.bytes.begin() + static_cast<std::ptrdiff_t>(segment.fileOffset),
                    segment.fileSize, region->bytes.begin());
    }
    return true;
}

bool mapRelSections(const ParsedElf& parsed,
                    Memory& memory,
                    Elf32ImageInfo& info,
                    std::uint32_t imageBase,
                    std::string& error) {
    std::uint32_t cursor = imageBase;
    for (std::size_t i = 0; i < info.sections.size(); ++i) {
        auto& section = info.sections[i];
        if ((section.flags & kShfAlloc) == 0 || section.size == 0) continue;
        const std::uint32_t alignment = std::max<std::uint32_t>(section.alignment, 1U);
        if ((alignment & (alignment - 1U)) != 0) {
            error = "ELF ET_REL section alignment is not a power of two";
            return false;
        }
        cursor = alignUp(cursor, alignment);
        const std::uint64_t end = static_cast<std::uint64_t>(cursor) + section.size;
        if (end > 0x1'0000'0000ULL) {
            error = "ELF ET_REL allocation exceeds 32-bit address space";
            return false;
        }
        section.mappedAddress = cursor;
        std::ostringstream name;
        name << "elf:" << (section.name.empty() ? "section" : section.name)
             << '[' << section.index << ']';
        if (!memory.map(cursor, section.size, sectionPerms(section.flags), name.str())) {
            error = "failed to map ELF ET_REL section " + std::to_string(section.index);
            return false;
        }
        if (section.type != kShtNobits && section.size != 0) {
            auto* region = memory.find(cursor, section.size);
            if (!region || !rangeWithin(section.fileOffset, section.size, parsed.bytes.size())) {
                error = "invalid ELF ET_REL section data";
                return false;
            }
            std::copy_n(parsed.bytes.begin() + static_cast<std::ptrdiff_t>(section.fileOffset),
                        section.size, region->bytes.begin());
        }
        cursor = static_cast<std::uint32_t>(end);
    }
    info.loadBias = imageBase;
    return true;
}

} // namespace

bool Elf32Loader::inspectFile(const std::string& path,
                              Elf32ImageInfo& info,
                              std::string& error) {
    std::vector<std::uint8_t> bytes;
    if (!readFile(path, bytes, error)) return false;
    ParsedElf parsed{};
    if (!parse(bytes, parsed, error)) return false;
    info = std::move(parsed.publicInfo);
    return true;
}

bool Elf32Loader::loadFile(const std::string& path,
                           Memory& memory,
                           Elf32ImageInfo& info,
                           std::string& error,
                           std::uint32_t imageBase,
                           const std::vector<SymbolBinding>& bindings) {
    std::vector<std::uint8_t> bytes;
    if (!readFile(path, bytes, error)) return false;
    ParsedElf parsed{};
    if (!parse(bytes, parsed, error)) return false;
    info = parsed.publicInfo;

    if (info.type == kEtRel) {
        if (!mapRelSections(parsed, memory, info, imageBase, error)) return false;
        info.entry = 0;
    } else {
        const std::uint32_t bias = info.type == kEtDyn ? imageBase : 0U;
        info.loadBias = bias;
        for (auto& segment : info.loadSegments) {
            if (!mapLoadSegment(parsed, memory, segment, bias, error)) return false;
        }
        info.entry = bias + info.originalEntry;
        // Publish runtime addresses for ordinary sections too, useful to symbol/SECTOFF logic.
        for (auto& section : info.sections) {
            if ((section.flags & kShfAlloc) != 0) section.mappedAddress = bias + section.address;
        }
    }

    std::unordered_map<std::uint32_t, RuntimeSymbolTable> runtime{};
    if (!buildRuntimeSymbols(parsed, info.loadBias, bindings, runtime, info, error)) return false;
    if (!applyRelocations(parsed, memory, info, runtime, error)) return false;
    return true;
}

std::string elf32SegmentFlags(std::uint32_t flags) {
    std::string out;
    out += (flags & kPfR) != 0 ? 'R' : '-';
    out += (flags & kPfW) != 0 ? 'W' : '-';
    out += (flags & kPfX) != 0 ? 'X' : '-';
    return out;
}

std::string elf32TypeName(std::uint16_t type) {
    switch (type) {
    case kEtRel: return "ET_REL";
    case kEtExec: return "ET_EXEC";
    case kEtDyn: return "ET_DYN";
    default: return "UNKNOWN";
    }
}

} // namespace ppclab::ppc
