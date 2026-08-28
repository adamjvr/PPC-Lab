// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/UniversalImage.hpp"

#include "ppclab/ppc/Elf32Loader.hpp"
#include "ppclab/ppc/MachOLoader.hpp"
#include "ppclab/ppc/PefLoader.hpp"

#include <array>
#include <fstream>

namespace ppclab::ppc {

UniversalImageFormat UniversalImageLoader::detectFile(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    std::array<unsigned char, 8> bytes{};
    in.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    if (in.gcount() < 4) return UniversalImageFormat::Unknown;

    if (bytes[0] == 0x7fU && bytes[1] == 'E' && bytes[2] == 'L' && bytes[3] == 'F')
        return UniversalImageFormat::Elf32PpcBe;
    if (bytes[0] == 'J' && bytes[1] == 'o' && bytes[2] == 'y' && bytes[3] == '!')
        return UniversalImageFormat::PefCfmPpc;

    const std::uint32_t magic = (std::uint32_t(bytes[0]) << 24U) |
                                (std::uint32_t(bytes[1]) << 16U) |
                                (std::uint32_t(bytes[2]) << 8U) |
                                std::uint32_t(bytes[3]);
    if (magic == 0xfeedfaceU || magic == 0xcafebabeU)
        return UniversalImageFormat::MachOPpc32Be;
    return UniversalImageFormat::Unknown;
}

const char* UniversalImageLoader::formatName(UniversalImageFormat format) noexcept {
    switch (format) {
    case UniversalImageFormat::Elf32PpcBe: return "ELF32-PPC-BE";
    case UniversalImageFormat::MachOPpc32Be: return "Mach-O-PPC32-BE";
    case UniversalImageFormat::PefCfmPpc: return "PEF-CFM-PPC";
    case UniversalImageFormat::Unknown: return "unknown";
    }
    return "unknown";
}

bool UniversalImageLoader::inspectFile(const std::string& path,
                                       UniversalImageInfo& info,
                                       std::string& error) {
    info = {};
    info.format = detectFile(path);
    switch (info.format) {
    case UniversalImageFormat::Elf32PpcBe: {
        Elf32ImageInfo typed{};
        if (!Elf32Loader::inspectFile(path, typed, error)) return false;
        info.entry = typed.originalEntry;
        info.symbols = std::move(typed.symbols);
        return true;
    }
    case UniversalImageFormat::MachOPpc32Be: {
        MachOImageInfo typed{};
        if (!MachOLoader::inspectFile(path, typed, error)) return false;
        info.entry = typed.entry;
        info.symbols = std::move(typed.symbols);
        return true;
    }
    case UniversalImageFormat::PefCfmPpc: {
        PefImageInfo typed{};
        if (!PefLoader::inspectFile(path, typed, error)) return false;
        info.entry = typed.entry;
        info.symbols = std::move(typed.symbols);
        return true;
    }
    case UniversalImageFormat::Unknown:
        error = "unknown or unsupported image format";
        return false;
    }
    error = "unknown or unsupported image format";
    return false;
}

bool UniversalImageLoader::loadFile(const std::string& path,
                                    Memory& memory,
                                    UniversalImageInfo& info,
                                    std::string& error,
                                    std::uint32_t imageBase,
                                    const std::vector<SymbolBinding>& bindings) {
    info = {};
    info.format = detectFile(path);
    switch (info.format) {
    case UniversalImageFormat::Elf32PpcBe: {
        Elf32ImageInfo typed{};
        if (!Elf32Loader::loadFile(path, memory, typed, error, imageBase, bindings)) return false;
        info.entry = typed.entry;
        info.symbols = std::move(typed.symbols);
        return true;
    }
    case UniversalImageFormat::MachOPpc32Be: {
        MachOImageInfo typed{};
        if (!MachOLoader::loadFile(path, memory, typed, error, imageBase, bindings)) return false;
        info.entry = typed.entry;
        info.symbols = std::move(typed.symbols);
        return true;
    }
    case UniversalImageFormat::PefCfmPpc: {
        PefImageInfo typed{};
        if (!PefLoader::loadFile(path, memory, typed, error, imageBase, bindings)) return false;
        info.entry = typed.entry;
        info.symbols = std::move(typed.symbols);
        return true;
    }
    case UniversalImageFormat::Unknown:
        error = "unknown or unsupported image format";
        return false;
    }
    error = "unknown or unsupported image format";
    return false;
}

} // namespace ppclab::ppc
