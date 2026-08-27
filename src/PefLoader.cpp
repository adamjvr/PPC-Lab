// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/PefLoader.hpp"

#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iterator>
#include <limits>
#include <optional>
#include <span>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace ppclab::ppc {
namespace {

constexpr std::uint32_t kTagJoy = 0x4a6f7921U; // Joy!
constexpr std::uint32_t kTagPeff = 0x70656666U; // peff
constexpr std::uint32_t kArchPpc = 0x70777063U; // pwpc
constexpr std::size_t kContainerHeaderSize = 40;
constexpr std::size_t kSectionHeaderSize = 28;
constexpr std::size_t kLoaderHeaderSize = 56;
constexpr std::size_t kImportedLibrarySize = 24;
constexpr std::size_t kImportedSymbolSize = 4;
constexpr std::size_t kRelocHeaderSize = 12;
constexpr std::uint8_t kWeakImportMask = 0x80U;

constexpr std::uint8_t kCode = 0;
constexpr std::uint8_t kUnpackedData = 1;
constexpr std::uint8_t kPatternData = 2;
constexpr std::uint8_t kConstant = 3;
constexpr std::uint8_t kLoader = 4;
constexpr std::uint8_t kExecutableData = 6;

struct LoaderHeader {
    std::int32_t mainSection = -1;
    std::uint32_t mainOffset = 0;
    std::int32_t initSection = -1;
    std::uint32_t initOffset = 0;
    std::int32_t termSection = -1;
    std::uint32_t termOffset = 0;
    std::uint32_t libraryCount = 0;
    std::uint32_t importCount = 0;
    std::uint32_t relocSectionCount = 0;
    std::uint32_t relocInstrOffset = 0;
    std::uint32_t stringsOffset = 0;
    std::uint32_t exportHashOffset = 0;
    std::uint32_t exportHashPower = 0;
    std::uint32_t exportCount = 0;
};

struct ImportInfo {
    std::string name{};
    std::uint8_t symbolClass = 0;
    bool weak = false;
    std::uint32_t address = 0;
    bool resolved = false;
};

struct RelocHeader {
    std::uint16_t sectionIndex = 0;
    std::uint32_t chunkCount = 0;
    std::uint32_t firstOffset = 0;
};

struct ParsedPef {
    std::vector<std::uint8_t> bytes{};
    PefImageInfo info{};
    std::optional<std::uint32_t> loaderSectionIndex{};
    LoaderHeader loader{};
    std::vector<ImportInfo> imports{};
    std::vector<RelocHeader> relocHeaders{};
};

bool readFile(const std::string& path, std::vector<std::uint8_t>& bytes, std::string& error) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        error = "cannot open PEF file: " + path;
        return false;
    }
    bytes.assign(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
    if (bytes.empty()) {
        error = "PEF file is empty: " + path;
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

std::int16_t beS16(std::span<const std::uint8_t> b, std::size_t off) noexcept {
    return static_cast<std::int16_t>(be16(b, off));
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
    return static_cast<std::uint32_t>((static_cast<std::uint64_t>(value) + alignment - 1U) &
                                      ~(static_cast<std::uint64_t>(alignment) - 1U));
}

std::string cstringAt(std::span<const std::uint8_t> bytes,
                      std::size_t base,
                      std::size_t maxSize,
                      std::uint32_t offset) {
    if (offset >= maxSize || base + offset >= bytes.size()) return {};
    const std::size_t start = base + offset;
    const std::size_t limit = std::min(bytes.size(), base + maxSize);
    std::size_t end = start;
    while (end < limit && bytes[end] != 0) ++end;
    return std::string(reinterpret_cast<const char*>(bytes.data() + start), end - start);
}

bool isInstantiated(std::uint8_t kind) noexcept {
    return kind == kCode || kind == kUnpackedData || kind == kPatternData ||
           kind == kConstant || kind == kExecutableData;
}

MemoryPerm sectionPerms(std::uint8_t kind) noexcept {
    switch (kind) {
    case kCode: return MemoryPerm::Read | MemoryPerm::Execute;
    case kUnpackedData:
    case kPatternData: return MemoryPerm::Read | MemoryPerm::Write;
    case kConstant: return MemoryPerm::Read;
    case kExecutableData: return MemoryPerm::Read | MemoryPerm::Write | MemoryPerm::Execute;
    default: return MemoryPerm::Read;
    }
}

bool parseHeader(const std::vector<std::uint8_t>& bytes, ParsedPef& parsed, std::string& error) {
    parsed = {};
    parsed.bytes = bytes;
    if (bytes.size() < kContainerHeaderSize) {
        error = "file is smaller than a PEF container header";
        return false;
    }
    if (be32(bytes, 0) != kTagJoy || be32(bytes, 4) != kTagPeff) {
        error = "not a PEF container ('Joy!'/'peff' signature missing)";
        return false;
    }
    auto& info = parsed.info;
    info.architecture = be32(bytes, 8);
    info.formatVersion = be32(bytes, 12);
    info.sectionCount = be16(bytes, 32);
    info.instantiatedSectionCount = be16(bytes, 34);
    if (info.architecture != kArchPpc) {
        error = "PEF architecture is not 'pwpc' PowerPC";
        return false;
    }
    if (info.formatVersion != 1) {
        error = "unsupported PEF format version " + std::to_string(info.formatVersion);
        return false;
    }
    const std::uint64_t headersEnd = kContainerHeaderSize +
                                     static_cast<std::uint64_t>(info.sectionCount) * kSectionHeaderSize;
    if (headersEnd > bytes.size()) {
        error = "PEF section-header table lies outside the file";
        return false;
    }
    info.sections.reserve(info.sectionCount);
    for (std::uint32_t i = 0; i < info.sectionCount; ++i) {
        const std::size_t off = kContainerHeaderSize + static_cast<std::size_t>(i) * kSectionHeaderSize;
        PefSectionInfo section{};
        section.index = i;
        section.defaultAddress = be32(bytes, off + 4);
        section.totalLength = be32(bytes, off + 8);
        section.unpackedLength = be32(bytes, off + 12);
        section.containerLength = be32(bytes, off + 16);
        section.containerOffset = be32(bytes, off + 20);
        section.kind = bytes[off + 24];
        section.shareKind = bytes[off + 25];
        section.alignmentPower = bytes[off + 26];
        if (section.containerLength != 0 &&
            !rangeWithin(section.containerOffset, section.containerLength, bytes.size())) {
            error = "PEF section contents lie outside the file";
            return false;
        }
        if (section.unpackedLength > section.totalLength) {
            error = "PEF section unpackedLength exceeds totalLength";
            return false;
        }
        if (section.kind == kLoader) {
            if (parsed.loaderSectionIndex) {
                error = "PEF contains more than one loader section";
                return false;
            }
            parsed.loaderSectionIndex = i;
        }
        info.sections.push_back(section);
    }
    return true;
}

bool parseLoader(ParsedPef& parsed, std::string& error) {
    if (!parsed.loaderSectionIndex) return true;
    const auto& section = parsed.info.sections[*parsed.loaderSectionIndex];
    if (section.containerLength < kLoaderHeaderSize) {
        error = "PEF loader section is smaller than its header";
        return false;
    }
    const auto base = static_cast<std::size_t>(section.containerOffset);
    const auto size = static_cast<std::size_t>(section.containerLength);
    const auto b = std::span<const std::uint8_t>(parsed.bytes);
    auto& l = parsed.loader;
    l.mainSection = beS32(b, base + 0);
    l.mainOffset = be32(b, base + 4);
    l.initSection = beS32(b, base + 8);
    l.initOffset = be32(b, base + 12);
    l.termSection = beS32(b, base + 16);
    l.termOffset = be32(b, base + 20);
    l.libraryCount = be32(b, base + 24);
    l.importCount = be32(b, base + 28);
    l.relocSectionCount = be32(b, base + 32);
    l.relocInstrOffset = be32(b, base + 36);
    l.stringsOffset = be32(b, base + 40);
    l.exportHashOffset = be32(b, base + 44);
    l.exportHashPower = be32(b, base + 48);
    l.exportCount = be32(b, base + 52);

    const std::uint64_t fixedTables = kLoaderHeaderSize +
                                      static_cast<std::uint64_t>(l.libraryCount) * kImportedLibrarySize +
                                      static_cast<std::uint64_t>(l.importCount) * kImportedSymbolSize +
                                      static_cast<std::uint64_t>(l.relocSectionCount) * kRelocHeaderSize;
    if (fixedTables > size || l.stringsOffset > size || l.relocInstrOffset > size ||
        l.exportHashOffset > size) {
        error = "PEF loader table offsets are outside the loader section";
        return false;
    }
    if (l.exportHashPower > 30) {
        error = "PEF export hash table power is unreasonable";
        return false;
    }

    const std::size_t libraryBase = base + kLoaderHeaderSize;
    const std::size_t symbolBase = libraryBase + static_cast<std::size_t>(l.libraryCount) * kImportedLibrarySize;
    const std::size_t relocHeaderBase = symbolBase + static_cast<std::size_t>(l.importCount) * kImportedSymbolSize;
    const std::size_t stringBase = base + l.stringsOffset;
    const std::size_t stringSize = size - l.stringsOffset;

    // Imported symbols are one flat table. Library ownership is useful metadata,
    // but relocations address the flat symbol index directly.
    parsed.imports.reserve(l.importCount);
    for (std::uint32_t i = 0; i < l.importCount; ++i) {
        const auto raw = be32(b, symbolBase + static_cast<std::size_t>(i) * 4U);
        ImportInfo imp{};
        imp.symbolClass = static_cast<std::uint8_t>(raw >> 24U);
        imp.weak = (imp.symbolClass & kWeakImportMask) != 0;
        imp.name = cstringAt(b, stringBase, stringSize, raw & 0x00ffffffU);
        parsed.imports.push_back(imp);
        ImageSymbol symbol{};
        symbol.name = imp.name;
        symbol.type = imp.symbolClass & 0x0fU;
        symbol.imported = true;
        symbol.defined = false;
        parsed.info.symbols.push_back(std::move(symbol));
    }

    parsed.relocHeaders.reserve(l.relocSectionCount);
    for (std::uint32_t i = 0; i < l.relocSectionCount; ++i) {
        const std::size_t off = relocHeaderBase + static_cast<std::size_t>(i) * kRelocHeaderSize;
        RelocHeader rh{};
        rh.sectionIndex = be16(b, off);
        rh.chunkCount = be32(b, off + 4);
        rh.firstOffset = be32(b, off + 8);
        if (rh.sectionIndex >= parsed.info.sections.size()) {
            error = "PEF relocation header references an invalid section";
            return false;
        }
        const std::uint64_t relocEnd = static_cast<std::uint64_t>(l.relocInstrOffset) + rh.firstOffset +
                                       static_cast<std::uint64_t>(rh.chunkCount) * 2U;
        if (relocEnd > size) {
            error = "PEF relocation instruction stream lies outside loader section";
            return false;
        }
        parsed.info.relocationChunkCount += rh.chunkCount;
        parsed.relocHeaders.push_back(rh);
    }

    // Export layout: hash table, key table, packed 10-byte symbol entries.
    const std::uint64_t hashCount = std::uint64_t{1} << l.exportHashPower;
    const std::uint64_t keyOffset = static_cast<std::uint64_t>(l.exportHashOffset) + hashCount * 4U;
    const std::uint64_t exportOffset = keyOffset + static_cast<std::uint64_t>(l.exportCount) * 4U;
    const std::uint64_t exportEnd = exportOffset + static_cast<std::uint64_t>(l.exportCount) * 10U;
    if (l.exportCount != 0 && exportEnd > size) {
        error = "PEF export tables lie outside loader section";
        return false;
    }
    for (std::uint32_t i = 0; i < l.exportCount; ++i) {
        const std::size_t keyAt = base + static_cast<std::size_t>(keyOffset) + static_cast<std::size_t>(i) * 4U;
        const std::size_t symAt = base + static_cast<std::size_t>(exportOffset) + static_cast<std::size_t>(i) * 10U;
        const auto hashWord = be32(b, keyAt);
        const std::uint32_t nameLength = hashWord >> 16U;
        const auto classAndName = be32(b, symAt);
        const auto symbolValue = be32(b, symAt + 4);
        const auto sectionIndex = beS16(b, symAt + 8);
        const std::uint32_t nameOffset = classAndName & 0x00ffffffU;
        std::string name;
        if (nameOffset < stringSize && nameLength <= stringSize - nameOffset) {
            name.assign(reinterpret_cast<const char*>(b.data() + stringBase + nameOffset), nameLength);
        }
        ImageSymbol symbol{};
        symbol.name = std::move(name);
        symbol.value = symbolValue;
        symbol.sectionIndex = sectionIndex >= 0 ? static_cast<std::uint32_t>(sectionIndex) : 0xffffffffU;
        symbol.type = static_cast<std::uint8_t>(classAndName >> 24U);
        symbol.defined = sectionIndex != -3;
        symbol.imported = sectionIndex == -3;
        parsed.info.symbols.push_back(std::move(symbol));
    }

    parsed.info.mainSection = l.mainSection;
    parsed.info.mainOffset = l.mainOffset;
    parsed.info.initSection = l.initSection;
    parsed.info.initOffset = l.initOffset;
    parsed.info.termSection = l.termSection;
    parsed.info.termOffset = l.termOffset;
    parsed.info.importCount = l.importCount;
    parsed.info.relocationSectionCount = l.relocSectionCount;
    return true;
}

bool parse(const std::vector<std::uint8_t>& bytes, ParsedPef& parsed, std::string& error) {
    if (!parseHeader(bytes, parsed, error)) return false;
    return parseLoader(parsed, error);
}

bool readPidataArg(std::span<const std::uint8_t> src, std::size_t& cursor,
                   std::uint32_t& value, std::string& error) {
    value = 0;
    for (unsigned i = 0; i < 5; ++i) {
        if (cursor >= src.size()) {
            error = "truncated PEF pattern-data argument";
            return false;
        }
        const auto byte = src[cursor++];
        value = (value << 7U) | (byte & 0x7fU);
        if ((byte & 0x80U) == 0) return true;
    }
    error = "PEF pattern-data argument exceeds five bytes";
    return false;
}

bool pidataCount(std::uint8_t inlineCount, std::span<const std::uint8_t> src,
                 std::size_t& cursor, std::uint32_t& value, std::string& error) {
    if (inlineCount != 0) {
        value = inlineCount;
        return true;
    }
    return readPidataArg(src, cursor, value, error);
}

bool appendRaw(std::vector<std::uint8_t>& out, std::span<const std::uint8_t> src,
               std::size_t& cursor, std::size_t count, std::size_t limit,
               std::string& error) {
    if (cursor > src.size() || count > src.size() - cursor || out.size() + count > limit) {
        error = "PEF pattern-data raw block exceeds input/output bounds";
        return false;
    }
    out.insert(out.end(), src.begin() + static_cast<std::ptrdiff_t>(cursor),
               src.begin() + static_cast<std::ptrdiff_t>(cursor + count));
    cursor += count;
    return true;
}

bool unpackPattern(std::span<const std::uint8_t> src,
                   std::size_t outputSize,
                   std::vector<std::uint8_t>& out,
                   std::string& error) {
    out.clear();
    out.reserve(outputSize);
    std::size_t cursor = 0;
    while (cursor < src.size()) {
        const auto control = src[cursor++];
        const auto opcode = control >> 5U;
        std::uint32_t count = 0;
        if (!pidataCount(control & 0x1fU, src, cursor, count, error)) return false;
        if (opcode == 0) { // zero
            if (out.size() + count > outputSize) { error = "PEF pidata zero exceeds output"; return false; }
            out.resize(out.size() + count, 0);
        } else if (opcode == 1) { // block copy
            if (!appendRaw(out, src, cursor, count, outputSize, error)) return false;
        } else if (opcode == 2) { // repeated block; extra arg is repeatCount-1
            std::uint32_t repeatMinusOne = 0;
            if (!readPidataArg(src, cursor, repeatMinusOne, error)) return false;
            if (cursor > src.size() || count > src.size() - cursor) {
                error = "truncated PEF pidata repeated block";
                return false;
            }
            const auto block = src.subspan(cursor, count);
            cursor += count;
            const std::uint64_t repeats = static_cast<std::uint64_t>(repeatMinusOne) + 1U;
            if (repeats * count > outputSize - out.size()) {
                error = "PEF pidata repeated block exceeds output";
                return false;
            }
            for (std::uint64_t r = 0; r < repeats; ++r) out.insert(out.end(), block.begin(), block.end());
        } else if (opcode == 3 || opcode == 4) {
            const std::uint32_t commonSize = count;
            std::uint32_t customSize = 0, repeatCount = 0;
            if (!readPidataArg(src, cursor, customSize, error) ||
                !readPidataArg(src, cursor, repeatCount, error)) return false;
            std::vector<std::uint8_t> common;
            if (opcode == 3) {
                if (cursor > src.size() || commonSize > src.size() - cursor) {
                    error = "truncated PEF pidata common block";
                    return false;
                }
                common.assign(src.begin() + static_cast<std::ptrdiff_t>(cursor),
                              src.begin() + static_cast<std::ptrdiff_t>(cursor + commonSize));
                cursor += commonSize;
            } else {
                common.assign(commonSize, 0);
            }
            const std::uint64_t required = static_cast<std::uint64_t>(commonSize) * (repeatCount + 1ULL) +
                                           static_cast<std::uint64_t>(customSize) * repeatCount;
            if (required > outputSize - out.size()) {
                error = "PEF pidata interleave exceeds output";
                return false;
            }
            for (std::uint32_t r = 0; r < repeatCount; ++r) {
                out.insert(out.end(), common.begin(), common.end());
                if (!appendRaw(out, src, cursor, customSize, outputSize, error)) return false;
            }
            out.insert(out.end(), common.begin(), common.end());
        } else {
            error = "reserved PEF pattern-data opcode " + std::to_string(opcode);
            return false;
        }
    }
    if (out.size() > outputSize) {
        error = "PEF pattern data produced too much output";
        return false;
    }
    out.resize(outputSize, 0);
    return true;
}

bool mapSections(const ParsedPef& parsed,
                 Memory& memory,
                 PefImageInfo& info,
                 std::uint32_t imageBase,
                 std::string& error) {
    std::uint32_t cursor = imageBase;
    for (auto& section : info.sections) {
        if (!isInstantiated(section.kind) || section.totalLength == 0) continue;
        if (section.alignmentPower >= 31) {
            error = "PEF section alignment is too large";
            return false;
        }
        const std::uint32_t alignment = 1U << section.alignmentPower;
        cursor = alignUp(cursor, alignment);
        const std::uint64_t end = static_cast<std::uint64_t>(cursor) + section.totalLength;
        if (end > 0x1'0000'0000ULL) {
            error = "PEF instantiated sections exceed 32-bit address space";
            return false;
        }
        section.mappedAddress = cursor;
        if (!memory.map(cursor, section.totalLength, sectionPerms(section.kind),
                        "pef:section[" + std::to_string(section.index) + "]:" +
                        pefSectionKindName(section.kind))) {
            error = "failed to map PEF section " + std::to_string(section.index);
            return false;
        }
        auto* region = memory.find(cursor, section.totalLength);
        if (!region) { error = "internal PEF mapping failure"; return false; }
        if (section.kind == kPatternData) {
            const auto src = std::span<const std::uint8_t>(parsed.bytes).subspan(
                section.containerOffset, section.containerLength);
            std::vector<std::uint8_t> unpacked;
            if (!unpackPattern(src, section.unpackedLength, unpacked, error)) return false;
            std::copy(unpacked.begin(), unpacked.end(), region->bytes.begin());
        } else if (section.containerLength != 0) {
            const std::size_t copySize = std::min<std::size_t>(section.containerLength,
                                                               section.unpackedLength);
            std::copy_n(parsed.bytes.begin() + static_cast<std::ptrdiff_t>(section.containerOffset),
                        copySize, region->bytes.begin());
        }
        cursor = static_cast<std::uint32_t>(end);
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

bool addWord(Memory& memory, std::uint32_t address, std::uint32_t add, std::string& error) {
    std::uint32_t word = 0;
    if (!directRead32(memory, address, word) || !directWrite32(memory, address, word + add)) {
        error = "PEF relocation target is outside an instantiated section";
        return false;
    }
    return true;
}

bool sectionAddress(const PefImageInfo& info, std::uint32_t index,
                    std::uint32_t& address, std::string& error) {
    if (index >= info.sections.size() || info.sections[index].mappedAddress == 0) {
        error = "PEF relocation references a non-instantiated/invalid section " + std::to_string(index);
        return false;
    }
    address = info.sections[index].mappedAddress;
    return true;
}

struct RelocState {
    std::uint32_t targetBase = 0;
    std::uint32_t address = 0;
    std::uint32_t sectionC = 0;
    std::uint32_t sectionD = 0;
    std::uint32_t importIndex = 0;
};

bool importAddress(const std::vector<ImportInfo>& imports, std::uint32_t index,
                   std::uint32_t& address, std::string& error) {
    if (index >= imports.size()) {
        error = "PEF relocation import index is outside imported-symbol table";
        return false;
    }
    const auto& imp = imports[index];
    if (!imp.resolved) {
        error = "unresolved PEF import: " +
                (imp.name.empty() ? std::string("<anonymous>") : imp.name) +
                " (supply --bind NAME=ADDRESS)";
        return false;
    }
    address = imp.address;
    return true;
}

class RelocInterpreter {
public:
    RelocInterpreter(Memory& memory, const PefImageInfo& info,
                     const std::vector<ImportInfo>& imports, std::string& error)
        : memory_(memory), info_(info), imports_(imports), error_(error) {}

    bool run(const std::vector<std::uint16_t>& chunks, RelocState& state) {
        return execute(chunks, 0, chunks.size(), state, true);
    }

private:
    bool addRun(std::uint32_t value, std::uint32_t count, RelocState& s) {
        for (std::uint32_t i = 0; i < count; ++i) {
            if (!addWord(memory_, s.address, value, error_)) return false;
            s.address += 4;
        }
        return true;
    }

    bool execute(const std::vector<std::uint16_t>& chunks, std::size_t begin,
                 std::size_t end, RelocState& s, bool repeatsAllowed) {
        std::size_t i = begin;
        while (i < end) {
            const std::size_t instructionStart = i;
            const auto first = chunks[i++];
            if ((first & 0xc000U) == 0) { // 00: BySectDWithSkip
                const std::uint32_t skip = (first >> 6U) & 0xffU;
                const std::uint32_t count = first & 0x3fU;
                s.address += skip * 4U;
                if (!addRun(s.sectionD, count, s)) return false;
                continue;
            }
            if ((first >> 13U) == 2U) { // 010: value group
                const std::uint32_t sub = (first >> 9U) & 0x0fU;
                const std::uint32_t count = (first & 0x01ffU) + 1U;
                if (sub == 0) {
                    if (!addRun(s.sectionC, count, s)) return false;
                } else if (sub == 1) {
                    if (!addRun(s.sectionD, count, s)) return false;
                } else if (sub == 2 || sub == 3) {
                    for (std::uint32_t n = 0; n < count; ++n) {
                        if (!addWord(memory_, s.address, s.sectionC, error_) ||
                            !addWord(memory_, s.address + 4U, s.sectionD, error_)) return false;
                        s.address += sub == 2 ? 12U : 8U;
                    }
                } else if (sub == 4) {
                    for (std::uint32_t n = 0; n < count; ++n) {
                        if (!addWord(memory_, s.address, s.sectionD, error_)) return false;
                        s.address += 8U;
                    }
                } else if (sub == 5) {
                    for (std::uint32_t n = 0; n < count; ++n) {
                        std::uint32_t address = 0;
                        if (!importAddress(imports_, s.importIndex++, address, error_) ||
                            !addWord(memory_, s.address, address, error_)) return false;
                        s.address += 4U;
                    }
                } else {
                    error_ = "unsupported/reserved PEF relocate-value subopcode " + std::to_string(sub);
                    return false;
                }
                continue;
            }
            if ((first >> 13U) == 3U) { // 011: by index
                const std::uint32_t sub = (first >> 9U) & 0x0fU;
                const std::uint32_t index = first & 0x01ffU;
                if (sub == 0) {
                    std::uint32_t address = 0;
                    if (!importAddress(imports_, index, address, error_) ||
                        !addWord(memory_, s.address, address, error_)) return false;
                    s.address += 4U;
                    s.importIndex = index + 1U;
                } else if (sub == 1 || sub == 2) {
                    std::uint32_t address = 0;
                    if (!sectionAddress(info_, index, address, error_)) return false;
                    if (sub == 1) s.sectionC = address; else s.sectionD = address;
                } else if (sub == 3) {
                    std::uint32_t address = 0;
                    if (!sectionAddress(info_, index, address, error_) ||
                        !addWord(memory_, s.address, address, error_)) return false;
                    s.address += 4U;
                } else {
                    error_ = "unsupported/reserved PEF relocate-by-index subopcode " + std::to_string(sub);
                    return false;
                }
                continue;
            }
            if ((first >> 12U) == 8U) { // 1000 increment
                s.address += (first & 0x0fffU) + 1U;
                continue;
            }
            if ((first >> 12U) == 9U) { // 1001 small repeat
                if (!repeatsAllowed) { error_ = "nested PEF relocation repeat is invalid"; return false; }
                const std::size_t blockCount = ((first >> 8U) & 0x0fU) + 1U;
                const std::uint32_t repeatCount = (first & 0xffU) + 1U;
                if (instructionStart < begin + blockCount) {
                    error_ = "PEF small repeat reaches before relocation stream";
                    return false;
                }
                const std::size_t repeatBegin = instructionStart - blockCount;
                for (std::uint32_t r = 0; r < repeatCount; ++r) {
                    if (!execute(chunks, repeatBegin, instructionStart, s, false)) return false;
                }
                continue;
            }
            const std::uint32_t op6 = first >> 10U;
            if (op6 == 0x28U || op6 == 0x29U || op6 == 0x2cU || op6 == 0x2dU) {
                if (i >= end) { error_ = "truncated two-block PEF relocation instruction"; return false; }
                const auto second = chunks[i++];
                if (op6 == 0x28U) { // SetPosition: unsigned 26-bit offset
                    const std::uint32_t offset = ((first & 0x03ffU) << 16U) | second;
                    s.address = s.targetBase + offset;
                } else if (op6 == 0x29U) { // LgByImport
                    const std::uint32_t index = ((first & 0x03ffU) << 16U) | second;
                    std::uint32_t address = 0;
                    if (!importAddress(imports_, index, address, error_) ||
                        !addWord(memory_, s.address, address, error_)) return false;
                    s.address += 4U;
                    s.importIndex = index + 1U;
                } else if (op6 == 0x2cU) { // LgRepeat
                    if (!repeatsAllowed) { error_ = "nested PEF relocation repeat is invalid"; return false; }
                    const std::size_t blockCount = ((first >> 6U) & 0x0fU) + 1U;
                    const std::uint32_t repeatCount = ((first & 0x3fU) << 16U) | second;
                    if (instructionStart < begin + blockCount) {
                        error_ = "PEF large repeat reaches before relocation stream";
                        return false;
                    }
                    const std::size_t repeatBegin = instructionStart - blockCount;
                    for (std::uint32_t r = 0; r < repeatCount; ++r) {
                        if (!execute(chunks, repeatBegin, instructionStart, s, false)) return false;
                    }
                } else { // LgSetOrBySection: subopcode + 22-bit section index
                    const std::uint32_t sub = (first >> 6U) & 0x0fU;
                    const std::uint32_t index = ((first & 0x3fU) << 16U) | second;
                    std::uint32_t address = 0;
                    if (!sectionAddress(info_, index, address, error_)) return false;
                    if (sub == 0) {
                        if (!addWord(memory_, s.address, address, error_)) return false;
                        s.address += 4U;
                    } else if (sub == 1) s.sectionC = address;
                    else if (sub == 2) s.sectionD = address;
                    else {
                        error_ = "unsupported PEF large section subopcode " + std::to_string(sub);
                        return false;
                    }
                }
                continue;
            }
            if ((first >> 13U) == 7U) {
                error_ = "third-party PEF relocation opcodes are not supported";
                return false;
            }
            error_ = "unsupported/reserved PEF relocation opcode at chunk " + std::to_string(instructionStart);
            return false;
        }
        return true;
    }

    Memory& memory_;
    const PefImageInfo& info_;
    const std::vector<ImportInfo>& imports_;
    std::string& error_;
};

bool resolveImports(ParsedPef& parsed,
                    PefImageInfo& info,
                    const std::vector<SymbolBinding>& bindings) {
    for (auto& imp : parsed.imports) {
        if (findSymbolBinding(bindings, imp.name, imp.address)) imp.resolved = true;
        else if (imp.weak) { imp.resolved = true; imp.address = 0; }
    }
    // Update import symbols at the beginning of public symbols.
    for (std::size_t i = 0; i < parsed.imports.size() && i < info.symbols.size(); ++i) {
        info.symbols[i].value = parsed.imports[i].address;
        info.symbols[i].defined = parsed.imports[i].resolved;
    }
    return true;
}

bool applyRelocations(const ParsedPef& parsed,
                      Memory& memory,
                      PefImageInfo& info,
                      std::string& error) {
    if (!parsed.loaderSectionIndex || parsed.relocHeaders.empty()) return true;
    const auto& loaderSection = info.sections[*parsed.loaderSectionIndex];
    const std::size_t loaderBase = loaderSection.containerOffset;
    const auto b = std::span<const std::uint8_t>(parsed.bytes);
    std::uint32_t sectionC = info.sections.size() > 0 ? info.sections[0].mappedAddress : 0;
    std::uint32_t sectionD = info.sections.size() > 1 ? info.sections[1].mappedAddress : 0;
    RelocInterpreter interpreter(memory, info, parsed.imports, error);
    for (const auto& rh : parsed.relocHeaders) {
        if (info.sections[rh.sectionIndex].mappedAddress == 0) {
            error = "PEF relocation targets a non-instantiated section";
            return false;
        }
        std::vector<std::uint16_t> chunks;
        chunks.reserve(rh.chunkCount);
        const std::size_t off = loaderBase + parsed.loader.relocInstrOffset + rh.firstOffset;
        for (std::uint32_t i = 0; i < rh.chunkCount; ++i)
            chunks.push_back(be16(b, off + static_cast<std::size_t>(i) * 2U));
        RelocState state{};
        state.targetBase = info.sections[rh.sectionIndex].mappedAddress;
        state.address = state.targetBase;
        state.sectionC = sectionC;
        state.sectionD = sectionD;
        if (!interpreter.run(chunks, state)) return false;
    }
    return true;
}

void relocateExports(const ParsedPef& parsed, PefImageInfo& info) {
    const std::size_t importCount = parsed.imports.size();
    for (std::size_t i = importCount; i < info.symbols.size(); ++i) {
        auto& symbol = info.symbols[i];
        // sectionIndex 0xffffffff is a pseudo-section; preserve absolute/reexport raw value.
        if (symbol.sectionIndex < info.sections.size() && info.sections[symbol.sectionIndex].mappedAddress != 0) {
            symbol.value = info.sections[symbol.sectionIndex].mappedAddress + symbol.value;
            symbol.defined = true;
        }
    }
}

bool discoverEntries(PefImageInfo& info, std::string& error) {
    auto addressFor = [&](std::int32_t sectionIndex, std::uint32_t offset,
                          std::uint32_t& address, const char* label) -> bool {
        address = 0;
        if (sectionIndex < 0) return true;
        if (static_cast<std::uint32_t>(sectionIndex) >= info.sections.size() ||
            info.sections[sectionIndex].mappedAddress == 0 ||
            offset >= info.sections[sectionIndex].totalLength) {
            error = std::string("PEF ") + label + " entry points outside an instantiated section";
            return false;
        }
        address = info.sections[sectionIndex].mappedAddress + offset;
        return true;
    };
    if (!addressFor(info.mainSection, info.mainOffset, info.entry, "main")) return false;
    if (!addressFor(info.initSection, info.initOffset, info.initTransitionVector, "init")) return false;
    if (!addressFor(info.termSection, info.termOffset, info.termTransitionVector, "term")) return false;
    if (info.entry != 0) {
        ImageSymbol main{};
        main.name = "__pef_main";
        main.value = info.entry;
        main.defined = true;
        main.type = 0;
        info.symbols.push_back(std::move(main));
    }
    return true;
}

} // namespace

bool PefLoader::inspectFile(const std::string& path,
                            PefImageInfo& info,
                            std::string& error) {
    std::vector<std::uint8_t> bytes;
    if (!readFile(path, bytes, error)) return false;
    ParsedPef parsed{};
    if (!parse(bytes, parsed, error)) return false;
    info = std::move(parsed.info);
    return true;
}

bool PefLoader::loadFile(const std::string& path,
                         Memory& memory,
                         PefImageInfo& info,
                         std::string& error,
                         std::uint32_t imageBase,
                         const std::vector<SymbolBinding>& bindings) {
    std::vector<std::uint8_t> bytes;
    if (!readFile(path, bytes, error)) return false;
    ParsedPef parsed{};
    if (!parse(bytes, parsed, error)) return false;
    info = parsed.info;
    if (!mapSections(parsed, memory, info, imageBase, error)) return false;
    resolveImports(parsed, info, bindings);
    if (!applyRelocations(parsed, memory, info, error)) return false;
    relocateExports(parsed, info);
    return discoverEntries(info, error);
}

std::string pefSectionKindName(std::uint8_t kind) {
    switch (kind) {
    case kCode: return "code";
    case kUnpackedData: return "unpacked-data";
    case kPatternData: return "pattern-data";
    case kConstant: return "constant";
    case kLoader: return "loader";
    case 5: return "debug";
    case kExecutableData: return "executable-data";
    case 7: return "exception";
    case 8: return "traceback";
    default: return "unknown";
    }
}

} // namespace ppclab::ppc
