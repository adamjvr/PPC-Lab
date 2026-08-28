// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/BuiltinInterpreter.hpp"
#include "ppclab/ppc/CallHarness.hpp"
#include "ppclab/ppc/Elf32Loader.hpp"
#include "ppclab/ppc/ImportStubs.hpp"
#include "ppclab/ppc/MachOLoader.hpp"
#include "ppclab/ppc/Microtests.hpp"
#include "ppclab/ppc/PefLoader.hpp"
#include "ppclab/ppc/UnicornBackend.hpp"
#include "ppclab/ppc/UniversalImage.hpp"

#include <algorithm>
#include <bit>
#include <charconv>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <optional>
#include <span>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#ifndef PPC_LAB_VERSION
#define PPC_LAB_VERSION "dev"
#endif

namespace {
using namespace ppclab::ppc;

constexpr std::string_view kVersion = PPC_LAB_VERSION;

struct DumpRequest { std::uint32_t address = 0; std::size_t size = 0; };
enum class ImageKind { Unknown, Elf, MachO, Pef };

std::optional<std::uint64_t> parseUnsigned(std::string_view text) {
    int base = 10;
    if (text.size() > 2 && text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) {
        text.remove_prefix(2); base = 16;
    }
    if (text.empty()) return std::nullopt;
    std::uint64_t value = 0;
    auto [ptr, ec] = std::from_chars(text.data(), text.data() + text.size(), value, base);
    if (ec != std::errc{} || ptr != text.data() + text.size()) return std::nullopt;
    return value;
}

std::optional<double> parseDouble(std::string_view text) {
    try {
        std::size_t n = 0; const double v = std::stod(std::string(text), &n);
        if (n != text.size()) return std::nullopt; return v;
    } catch (...) { return std::nullopt; }
}

bool splitAssignment(std::string_view text, std::string_view& left, std::string_view& right) {
    const auto pos = text.find('=');
    if (pos == std::string_view::npos || pos == 0 || pos + 1 >= text.size()) return false;
    left = text.substr(0, pos); right = text.substr(pos + 1); return true;
}

std::string hex32(std::uint32_t value) {
    std::ostringstream out; out << "0x" << std::hex << std::setw(8) << std::setfill('0') << value; return out.str();
}
std::string hex64(std::uint64_t value) {
    std::ostringstream out; out << "0x" << std::hex << std::setw(16) << std::setfill('0') << value; return out.str();
}
std::string jsonEscape(std::string_view text) {
    std::ostringstream out;
    for (unsigned char c : text) {
        switch (c) {
        case '\\': out << "\\\\"; break;
        case '"': out << "\\\""; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default:
            if (c < 0x20) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(c);
            else out << static_cast<char>(c);
        }
    }
    return out.str();
}
std::uint64_t fnv1a64(std::span<const std::uint8_t> bytes) {
    std::uint64_t hash = 14695981039346656037ULL;
    for (auto byte : bytes) { hash ^= byte; hash *= 1099511628211ULL; }
    return hash;
}
std::size_t fileSize(const std::string& path) {
    std::ifstream in(path, std::ios::binary | std::ios::ate); if (!in) return 0;
    const auto end = in.tellg(); return end > 0 ? static_cast<std::size_t>(end) : 0;
}

ImageKind detectImage(const std::string& path) {
    switch (UniversalImageLoader::detectFile(path)) {
    case UniversalImageFormat::Elf32PpcBe: return ImageKind::Elf;
    case UniversalImageFormat::MachOPpc32Be: return ImageKind::MachO;
    case UniversalImageFormat::PefCfmPpc: return ImageKind::Pef;
    case UniversalImageFormat::Unknown: return ImageKind::Unknown;
    }
    return ImageKind::Unknown;
}

std::unique_ptr<ExecutionBackend> makeBackend(const std::string& requested, std::string& error) {
    if (requested == "builtin") return std::make_unique<BuiltinInterpreter>();
    if (requested == "unicorn") {
        if (!UnicornBackend::available()) { error = "Unicorn backend not available in this build"; return {}; }
        return std::make_unique<UnicornBackend>();
    }
    if (requested == "auto") return UnicornBackend::available()
        ? std::unique_ptr<ExecutionBackend>(std::make_unique<UnicornBackend>())
        : std::unique_ptr<ExecutionBackend>(std::make_unique<BuiltinInterpreter>());
    error = "unknown backend: " + requested; return {};
}

void usage() {
    std::cout << "PPC Lab " << kVersion << R"( — PowerPC execution and behavioral-research platform

Usage:
  ppc-lab selftest [--backend auto|builtin|unicorn]
  ppc-lab doctor
  ppc-lab capabilities [--json]
  ppc-lab analyze FILE [--json] [--symbols]
  ppc-lab image-info FILE
  ppc-lab elf-info FILE | macho-info FILE | pef-info FILE
  ppc-lab symbols FILE
  ppc-lab metadata FILE [--image-base HEX] [--bind NAME=ADDRESS]
  ppc-lab disasm (--code FILE | --image FILE | --elf FILE | --macho FILE | --pef FILE)
      [--base HEX] [--image-base HEX] [--start HEX] [--count N] [--bind NAME=ADDRESS]
  ppc-lab call|run (--code FILE | --image FILE | --elf FILE | --macho FILE | --pef FILE) [--data FILE]
      [--entry HEX | --entry-symbol NAME | --transition-vector HEX]
      [--image-base HEX] [--bind NAME=ADDRESS]
      [--backend auto|builtin|unicorn]
      [--code-base HEX] [--data-base HEX] [--data-map-size N]
      [--heap-base HEX] [--heap-size N] [--stack-base HEX] [--stack-size N]
      [--import-base HEX] [--import-size N] [--return HEX] [--toc HEX]
      [--max-instructions N] [--set rN=VALUE] [--set-f fN=VALUE]
      [--write-u32 ADDRESS=VALUE] [--write-f32 ADDRESS=VALUE]
      [--stub KIND@ADDRESS] [--syscall-return NUMBER=VALUE]
      [--default-syscall-return VALUE] [--ignore-traps] [--dump ADDRESS:SIZE]
      [--trace] [--trace-range START:END] [--json FILE] [--snapshot FILE]

Fast path:
  Use --image FILE for auto-detection. Explicit --elf/--macho/--pef remain available.

Native intake:
  ELF32 PPC BE: ET_EXEC, ET_DYN and ET_REL + symbols/common PPC relocations
  Mach-O PPC32 BE: thin/fat MH_OBJECT/MH_EXECUTE/MH_DYLIB/MH_BUNDLE
  PEF/CFM PPC: instantiated sections, pidata, imports/exports, relocation bytecode

Undefined imports are target policy, not core policy: bind them explicitly with
--bind NAME=ADDRESS and optionally attach behavioral --stub KIND@ADDRESS traps.
)";
}

void printCpu(const CpuState& cpu) {
    std::cout << "pc=" << hex32(cpu.pc) << " lr=" << hex32(cpu.lr)
              << " ctr=" << hex32(cpu.ctr) << " cr=" << hex32(cpu.cr) << '\n';
    for (unsigned row = 0; row < 4; ++row) {
        for (unsigned col = 0; col < 8; ++col) {
            const unsigned r = row * 8 + col;
            std::cout << 'r' << std::setw(2) << std::setfill('0') << r << '=' << hex32(cpu.gpr[r])
                      << (col == 7 ? '\n' : ' ');
        }
    }
    std::cout << std::setfill(' ');
}

std::string dumpHex(const Memory& memory, std::uint32_t address, std::size_t size) {
    std::vector<std::uint8_t> bytes(size); if (!memory.readBytes(address, bytes)) return "<unreadable>";
    std::ostringstream out;
    for (std::size_t i = 0; i < bytes.size(); ++i) {
        if (i) out << ' '; out << std::hex << std::setw(2) << std::setfill('0') << unsigned(bytes[i]);
    }
    return out.str();
}
std::optional<std::uint64_t> dumpFnv1a64(const Memory& memory, std::uint32_t address, std::size_t size) {
    std::vector<std::uint8_t> bytes(size); if (!memory.readBytes(address, bytes)) return std::nullopt;
    std::uint64_t hash = 14695981039346656037ULL;
    for (auto byte : bytes) { hash ^= byte; hash *= 1099511628211ULL; } return hash;
}

void writeJson(const std::string& path, const std::string& backend,
               const CallResult& result, const std::vector<DumpRequest>& dumps) {
    std::ofstream out(path); if (!out) throw std::runtime_error("cannot open JSON output: " + path);
    out << "{\n  \"schema\": \"ppc-lab-result-v1\",\n  \"backend\": \"" << backend
        << "\",\n  \"stop_reason\": \"" << stopReasonName(result.execution.reason)
        << "\",\n  \"instructions\": " << result.execution.instructions
        << ",\n  \"pc\": \"" << hex32(result.execution.pc) << "\",\n  \"instruction\": \""
        << hex32(result.execution.instruction) << "\",\n  \"registers\": {\n";
    for (unsigned i = 0; i < 32; ++i)
        out << "    \"r" << i << "\": \"" << hex32(result.cpu.gpr[i]) << "\"" << (i == 31 ? '\n' : ',') << (i == 31 ? "" : "\n");
    out << "  },\n  \"lr\": \"" << hex32(result.cpu.lr) << "\",\n  \"ctr\": \"" << hex32(result.cpu.ctr)
        << "\",\n  \"cr\": \"" << hex32(result.cpu.cr) << "\",\n  \"dumps\": [\n";
    for (std::size_t i = 0; i < dumps.size(); ++i) {
        const auto fnv = dumpFnv1a64(result.memory, dumps[i].address, dumps[i].size);
        out << "    {\"address\": \"" << hex32(dumps[i].address) << "\", \"size\": " << dumps[i].size
            << ", \"fnv1a64\": \"" << (fnv ? hex64(*fnv) : "unreadable") << "\", \"hex\": \""
            << dumpHex(result.memory, dumps[i].address, dumps[i].size) << "\"}" << (i + 1 == dumps.size() ? '\n' : ',') << (i + 1 == dumps.size() ? "" : "\n");
    }
    out << "  ]\n}\n";
}

void writeSnapshot(const std::string& path, const std::string& backend,
                   const CallResult& result, const std::vector<DumpRequest>& dumps) {
    std::ofstream out(path); if (!out) throw std::runtime_error("cannot open snapshot output: " + path);
    out << "{\n  \"schema\": \"ppc-lab-snapshot-v1\",\n  \"backend\": \"" << jsonEscape(backend)
        << "\",\n  \"stop_reason\": \"" << stopReasonName(result.execution.reason)
        << "\",\n  \"instructions\": " << result.execution.instructions
        << ",\n  \"pc\": \"" << hex32(result.execution.pc) << "\",\n  \"instruction\": \"" << hex32(result.execution.instruction)
        << "\",\n  \"message\": \"" << jsonEscape(result.execution.message) << "\",\n  \"cpu\": {\n";
    out << "    \"gpr\": [";
    for (unsigned i=0;i<32;++i) out << (i ? ", " : "") << "\"" << hex32(result.cpu.gpr[i]) << "\"";
    out << "],\n    \"fpr_bits\": [";
    for (unsigned i=0;i<32;++i) out << (i ? ", " : "") << "\"" << hex64(std::bit_cast<std::uint64_t>(result.cpu.fpr[i])) << "\"";
    out << "],\n    \"lr\": \"" << hex32(result.cpu.lr) << "\", \"ctr\": \"" << hex32(result.cpu.ctr)
        << "\", \"cr\": \"" << hex32(result.cpu.cr) << "\", \"xer\": \"" << hex32(result.cpu.xer)
        << "\", \"fpscr\": \"" << hex32(result.cpu.fpscr) << "\"\n  },\n";
    out << "  \"regions\": [\n";
    for (std::size_t i=0;i<result.memory.regions().size();++i) {
        const auto& r=result.memory.regions()[i];
        out << "    {\"name\": \"" << jsonEscape(r.name) << "\", \"base\": \"" << hex32(r.base)
            << "\", \"size\": " << r.bytes.size() << ", \"perms\": \""
            << (hasPerm(r.perms,MemoryPerm::Read)?"r":"-") << (hasPerm(r.perms,MemoryPerm::Write)?"w":"-")
            << (hasPerm(r.perms,MemoryPerm::Execute)?"x":"-") << "\", \"fnv1a64\": \""
            << hex64(fnv1a64(r.bytes)) << "\"}" << (i+1==result.memory.regions().size()?"\n":",\n");
    }
    out << "  ],\n  \"symbols\": [\n";
    for (std::size_t i=0;i<result.symbols.size();++i) {
        const auto& sym=result.symbols[i];
        out << "    {\"name\": \"" << jsonEscape(sym.name) << "\", \"address\": \"" << hex32(sym.value)
            << "\", \"size\": " << sym.size << ", \"defined\": " << (sym.defined?"true":"false")
            << ", \"imported\": " << (sym.imported?"true":"false") << "}" << (i+1==result.symbols.size()?"\n":",\n");
    }
    out << "  ],\n  \"dumps\": [\n";
    for (std::size_t i=0;i<dumps.size();++i) {
        const auto hash=dumpFnv1a64(result.memory,dumps[i].address,dumps[i].size);
        out << "    {\"address\": \"" << hex32(dumps[i].address) << "\", \"size\": " << dumps[i].size
            << ", \"fnv1a64\": \"" << (hash?hex64(*hash):"unreadable") << "\", \"hex\": \""
            << dumpHex(result.memory,dumps[i].address,dumps[i].size) << "\"}" << (i+1==dumps.size()?"\n":",\n");
    }
    out << "  ]\n}\n";
}

int stopExitCode(StopReason reason) {
    switch (reason) {
    case StopReason::Returned: return 0; case StopReason::UnsupportedInstruction: return 2;
    case StopReason::MemoryFault: return 3; case StopReason::ImportTrap: return 4;
    case StopReason::InstructionLimit: return 5; case StopReason::InvalidConfiguration: return 6;
    case StopReason::BackendError: return 7; case StopReason::Trap: return 8;
    case StopReason::SystemCall: return 9; } return 7;
}

void printSymbols(const std::vector<ImageSymbol>& symbols) {
    for (const auto& s : symbols) {
        std::cout << hex32(s.value) << ' ' << (s.imported ? 'U' : (s.defined ? 'D' : '?'))
                  << " sec=" << s.sectionIndex << " type=" << unsigned(s.type) << ' ' << s.name << '\n';
    }
}

int printElfInfo(const std::string& file) {
    Elf32ImageInfo info{}; std::string error;
    if (!Elf32Loader::inspectFile(file, info, error)) { std::cerr << "elf-info: " << error << '\n'; return 1; }
    std::cout << "format=ELF32-PPC-BE\ntype=" << info.type << " (" << elf32TypeName(info.type) << ")\n"
              << "machine=" << info.machine << " (EM_PPC)\nentry=" << hex32(info.originalEntry)
              << "\nsegments=" << info.loadSegments.size() << "\nsections=" << info.sections.size()
              << "\nsymbols=" << info.symbols.size() << "\nrelocations=" << info.relocationCount << '\n';
    for (const auto& s : info.loadSegments)
        std::cout << "  PT_LOAD[" << s.index << "] " << elf32SegmentFlags(s.flags) << " vaddr=" << hex32(s.virtualAddress)
                  << " filesz=" << hex32(s.fileSize) << " memsz=" << hex32(s.memorySize) << '\n';
    return 0;
}

int printMachOInfo(const std::string& file) {
    MachOImageInfo info{}; std::string error;
    if (!MachOLoader::inspectFile(file, info, error)) { std::cerr << "macho-info: " << error << '\n'; return 1; }
    std::cout << "format=Mach-O-PPC32-BE\ncontainer=" << (info.fatContainer ? "fat" : "thin")
              << "\ntype=" << info.fileType << " (" << machoFileTypeName(info.fileType) << ")\n"
              << "entry=" << hex32(info.entry) << "\nsegments=" << info.segments.size()
              << "\nsections=" << info.sections.size() << "\nsymbols=" << info.symbols.size() << '\n';
    for (const auto& s : info.segments)
        std::cout << "  " << s.name << ' ' << machoVmProtection(s.initProt) << " vmaddr=" << hex32(s.vmAddress)
                  << " vmsize=" << hex32(s.vmSize) << " filesz=" << hex32(s.fileSize) << '\n';
    return 0;
}

int printPefInfo(const std::string& file) {
    PefImageInfo info{}; std::string error;
    if (!PefLoader::inspectFile(file, info, error)) { std::cerr << "pef-info: " << error << '\n'; return 1; }
    std::cout << "format=PEF-CFM-PPC\narchitecture=pwpc\nversion=" << info.formatVersion
              << "\nsections=" << info.sectionCount << "\ninstantiated=" << info.instantiatedSectionCount
              << "\nmain=" << info.mainSection << ':' << hex32(info.mainOffset)
              << "\nimports=" << info.importCount << "\nrelocation_sections=" << info.relocationSectionCount
              << "\nrelocation_chunks=" << info.relocationChunkCount << "\nsymbols=" << info.symbols.size() << '\n';
    for (const auto& s : info.sections)
        std::cout << "  [" << s.index << "] " << pefSectionKindName(s.kind) << " total=" << hex32(s.totalLength)
                  << " packed=" << hex32(s.containerLength) << " align=2^" << unsigned(s.alignmentPower) << '\n';
    return 0;
}

int commandInfo(int argc, char** argv, std::optional<ImageKind> forced) {
    if (argc != 3) { std::cerr << "info command requires FILE\n"; return 1; }
    const std::string file = argv[2]; const ImageKind kind = forced.value_or(detectImage(file));
    if (kind == ImageKind::Elf) return printElfInfo(file);
    if (kind == ImageKind::MachO) return printMachOInfo(file);
    if (kind == ImageKind::Pef) return printPefInfo(file);
    std::cerr << "image-info: unknown input format\n"; return 1;
}

int commandSymbols(int argc, char** argv) {
    if (argc != 3) { std::cerr << "usage: ppc-lab symbols FILE\n"; return 1; }
    const std::string file = argv[2]; std::string error;
    switch (detectImage(file)) {
    case ImageKind::Elf: { Elf32ImageInfo i{}; if (!Elf32Loader::inspectFile(file, i, error)) break; printSymbols(i.symbols); return 0; }
    case ImageKind::MachO: { MachOImageInfo i{}; if (!MachOLoader::inspectFile(file, i, error)) break; printSymbols(i.symbols); return 0; }
    case ImageKind::Pef: { PefImageInfo i{}; if (!PefLoader::inspectFile(file, i, error)) break; printSymbols(i.symbols); return 0; }
    default: error = "unknown input format"; break;
    }
    std::cerr << "symbols: " << error << '\n'; return 1;
}

bool parseBinding(const std::string& text, SymbolBinding& binding) {
    std::string_view left, right; if (!splitAssignment(text, left, right)) return false;
    const auto address = parseUnsigned(right); if (!address || *address > 0xffffffffULL) return false;
    binding.name = std::string(left); binding.address = static_cast<std::uint32_t>(*address); return true;
}

void writeMetadataSymbols(std::ostream& out, const std::vector<ImageSymbol>& symbols) {
    out << "[\n";
    for (std::size_t i=0;i<symbols.size();++i) {
        const auto& sym=symbols[i];
        out << "    {\"name\": \"" << jsonEscape(sym.name) << "\", \"address\": \"" << hex32(sym.value)
            << "\", \"size\": " << sym.size << ", \"section\": " << sym.sectionIndex
            << ", \"binding\": " << unsigned(sym.binding) << ", \"type\": " << unsigned(sym.type)
            << ", \"defined\": " << (sym.defined?"true":"false") << ", \"imported\": " << (sym.imported?"true":"false")
            << "}" << (i+1==symbols.size()?"\n":",\n");
    }
    out << "  ]";
}


const char* hostPlatform() noexcept {
#if defined(_WIN32)
    return "windows";
#elif defined(__APPLE__)
    return "macos";
#elif defined(__linux__)
    return "linux";
#else
    return "unknown";
#endif
}

int commandCapabilities(int argc, char** argv) {
    bool json = false;
    if (argc == 3 && std::string_view(argv[2]) == "--json") json = true;
    else if (argc != 2) { std::cerr << "usage: ppc-lab capabilities [--json]\n"; return 1; }
    const bool unicorn = UnicornBackend::available();
    if (json) {
        std::cout << "{\n"
                  << "  \"schema\": \"ppc-lab-capabilities-v1\",\n"
                  << "  \"version\": \"" << kVersion << "\",\n"
                  << "  \"host\": \"" << hostPlatform() << "\",\n"
                  << "  \"guest\": {\"architecture\": \"ppc32\", \"endian\": \"big\"},\n"
                  << "  \"formats\": [\"ELF32-PPC-BE\", \"Mach-O-PPC32-BE\", \"PEF-CFM-PPC\", \"raw\"],\n"
                  << "  \"backends\": {\"builtin\": true, \"unicorn\": " << (unicorn ? "true" : "false") << "},\n"
                  << "  \"protocols\": {\"job\": \"ppc-lab-job-v1\", \"worker_response\": \"ppc-lab-worker-response-v1\", \"stream\": \"ndjson\", \"orchestration\": \"ppc-lab-orchestration-v1\", \"orchestration_job_result\": \"ppc-lab-orchestration-job-result-v1\", \"orchestration_summary\": \"ppc-lab-orchestration-summary-v1\", \"fleet\": \"ppc-lab-fleet-v1\", \"fleet_job_result\": \"ppc-lab-fleet-job-result-v1\", \"fleet_summary\": \"ppc-lab-fleet-summary-v1\", \"evidence_query\": \"ppc-lab-evidence-query-v1\", \"evidence_report\": \"ppc-lab-evidence-report-v1\", \"evidence_verify\": \"ppc-lab-evidence-verify-v1\"}\n"
                  << "}\n";
    } else {
        std::cout << "PPC Lab " << kVersion << '\n'
                  << "host=" << hostPlatform() << '\n'
                  << "guest=ppc32-big-endian\n"
                  << "formats=ELF32-PPC-BE,Mach-O-PPC32-BE,PEF-CFM-PPC,raw\n"
                  << "backend.builtin=yes\n"
                  << "backend.unicorn=" << (unicorn ? "yes" : "no") << '\n'
                  << "protocol.job=ppc-lab-job-v1\n"
                  << "protocol.worker-response=ppc-lab-worker-response-v1\n"
                  << "protocol.stream=ndjson\n"
                  << "protocol.orchestration=ppc-lab-orchestration-v1\n"
                  << "protocol.orchestration-job-result=ppc-lab-orchestration-job-result-v1\n"
                  << "protocol.orchestration-summary=ppc-lab-orchestration-summary-v1\n"
                  << "protocol.fleet=ppc-lab-fleet-v1\n"
                  << "protocol.fleet-job-result=ppc-lab-fleet-job-result-v1\n"
                  << "protocol.fleet-summary=ppc-lab-fleet-summary-v1\n"
                  << "protocol.evidence-query=ppc-lab-evidence-query-v1\n"
                  << "protocol.evidence-report=ppc-lab-evidence-report-v1\n"
                  << "protocol.evidence-verify=ppc-lab-evidence-verify-v1\n";
    }
    return 0;
}

int commandDoctor(int argc, char**) {
    if (argc != 2) { std::cerr << "usage: ppc-lab doctor\n"; return 1; }
    std::cout << "PPC Lab " << kVersion << " doctor\n"
              << "host=" << hostPlatform() << '\n'
              << "builtin=checking\n";
    BuiltinInterpreter builtin;
    const auto builtinResult = runMicrotests(builtin);
    if (!builtinResult.passed) {
        std::cout << builtinResult.report << "status=FAIL\n";
        return 1;
    }
    std::cout << "builtin=PASS\n";
    if (UnicornBackend::available()) {
        UnicornBackend unicorn;
        const auto unicornResult = runMicrotests(unicorn);
        if (!unicornResult.passed) {
            std::cout << unicornResult.report << "unicorn=FAIL\nstatus=FAIL\n";
            return 1;
        }
        std::cout << "unicorn=PASS\n";
    } else {
        std::cout << "unicorn=not-built\n";
    }
    std::cout << "intake=ELF32-PPC-BE,Mach-O-PPC32-BE,PEF-CFM-PPC,raw\n"
              << "worker-protocol=ppc-lab-job-v1/ndjson\n"
              << "orchestration=ppc-lab-orchestration-v1\n"
              << "fleet=ppc-lab-fleet-v1\n"
              << "evidence-store=sqlite3/content-addressed-json\nstatus=PASS\n";
    return 0;
}

int commandAnalyze(int argc, char** argv) {
    if (argc < 3) { std::cerr << "usage: ppc-lab analyze FILE [--json] [--symbols]\n"; return 1; }
    const std::string file = argv[2];
    bool json = false, showSymbols = false;
    for (int i = 3; i < argc; ++i) {
        const std::string_view arg = argv[i];
        if (arg == "--json") json = true;
        else if (arg == "--symbols") showSymbols = true;
        else { std::cerr << "analyze: unknown option " << arg << '\n'; return 1; }
    }
    UniversalImageInfo info{};
    std::string error;
    if (!UniversalImageLoader::inspectFile(file, info, error)) {
        std::cerr << "analyze: " << error << '\n';
        return 1;
    }
    const auto defined = std::count_if(info.symbols.begin(), info.symbols.end(), [](const ImageSymbol& s){ return s.defined; });
    const auto imported = std::count_if(info.symbols.begin(), info.symbols.end(), [](const ImageSymbol& s){ return s.imported; });
    if (json) {
        std::cout << "{\n  \"schema\": \"ppc-lab-analysis-v1\",\n"
                  << "  \"format\": \"" << UniversalImageLoader::formatName(info.format) << "\",\n"
                  << "  \"entry\": \"" << hex32(info.entry) << "\",\n"
                  << "  \"symbol_count\": " << info.symbols.size() << ",\n"
                  << "  \"defined_symbols\": " << defined << ",\n"
                  << "  \"imported_symbols\": " << imported;
        if (showSymbols) {
            std::cout << ",\n  \"symbols\": ";
            writeMetadataSymbols(std::cout, info.symbols);
            std::cout << '\n';
        } else std::cout << '\n';
        std::cout << "}\n";
    } else {
        std::cout << "format=" << UniversalImageLoader::formatName(info.format) << '\n'
                  << "entry=" << hex32(info.entry) << '\n'
                  << "symbols=" << info.symbols.size() << '\n'
                  << "defined_symbols=" << defined << '\n'
                  << "imported_symbols=" << imported << '\n';
        if (showSymbols) printSymbols(info.symbols);
    }
    return 0;
}

int commandMetadata(int argc, char** argv) {
    if (argc < 3) { std::cerr << "usage: ppc-lab metadata FILE [--image-base HEX] [--bind NAME=ADDRESS]\n"; return 1; }
    const std::string file=argv[2]; std::uint32_t imageBase=0x10000000U; std::vector<SymbolBinding> bindings;
    for (int i=3;i<argc;++i) {
        const std::string arg=argv[i];
        if (arg=="--image-base" && i+1<argc) { auto v=parseUnsigned(argv[++i]); if(!v||*v>0xffffffffULL){std::cerr<<"metadata: invalid image base\n";return 1;} imageBase=std::uint32_t(*v); }
        else if (arg=="--bind" && i+1<argc) { SymbolBinding b{}; if(!parseBinding(argv[++i],b)){std::cerr<<"metadata: invalid binding\n";return 1;} bindings.push_back(std::move(b)); }
        else { std::cerr << "metadata: unknown option " << arg << '\n'; return 1; }
    }
    Memory memory; std::string error; std::string format; std::uint32_t entry=0; std::vector<ImageSymbol> symbols;
    switch(detectImage(file)) {
    case ImageKind::Elf: { Elf32ImageInfo i{}; if(!Elf32Loader::loadFile(file,memory,i,error,imageBase,bindings)){std::cerr<<"metadata: "<<error<<'\n';return 1;} format="ELF32-PPC-BE";entry=i.entry;symbols=std::move(i.symbols);break; }
    case ImageKind::MachO: { MachOImageInfo i{}; if(!MachOLoader::loadFile(file,memory,i,error,imageBase,bindings)){std::cerr<<"metadata: "<<error<<'\n';return 1;} format="Mach-O-PPC32-BE";entry=i.entry;symbols=std::move(i.symbols);break; }
    case ImageKind::Pef: { PefImageInfo i{}; if(!PefLoader::loadFile(file,memory,i,error,imageBase,bindings)){std::cerr<<"metadata: "<<error<<'\n';return 1;} format="PEF-CFM-PPC";entry=i.entry;symbols=std::move(i.symbols);break; }
    default: std::cerr<<"metadata: unknown input format\n";return 1;
    }
    std::cout << "{\n  \"schema\": \"ppc-lab-metadata-v1\",\n  \"format\": \"" << format << "\",\n  \"entry\": \"" << hex32(entry) << "\",\n  \"regions\": [\n";
    for(std::size_t n=0;n<memory.regions().size();++n){const auto&r=memory.regions()[n];std::cout<<"    {\"name\": \""<<jsonEscape(r.name)<<"\", \"base\": \""<<hex32(r.base)<<"\", \"size\": "<<r.bytes.size()<<", \"perms\": \""<<(hasPerm(r.perms,MemoryPerm::Read)?"r":"-")<<(hasPerm(r.perms,MemoryPerm::Write)?"w":"-")<<(hasPerm(r.perms,MemoryPerm::Execute)?"x":"-")<<"\"}"<<(n+1==memory.regions().size()?"\n":",\n");}
    std::cout << "  ],\n  \"symbols\": "; writeMetadataSymbols(std::cout,symbols); std::cout << "\n}\n";
    return 0;
}

int commandDisasm(int argc, char** argv) {
    ImageConfig image{}; std::optional<std::uint32_t> start; std::size_t count = 32;
    for (int i = 2; i < argc; ++i) {
        const std::string arg = argv[i];
        auto need = [&](const char* opt) { if (i + 1 >= argc) throw std::runtime_error(std::string(opt)+" requires a value"); return std::string(argv[++i]); };
        try {
            if (arg == "--code") image.codePath = need("--code");
            else if (arg == "--image") image.imagePath = need("--image");
            else if (arg == "--elf") image.elfPath = need("--elf");
            else if (arg == "--macho") image.machoPath = need("--macho");
            else if (arg == "--pef") image.pefPath = need("--pef");
            else if (arg == "--bind") { SymbolBinding b{}; auto t=need("--bind"); if(!parseBinding(t,b)) throw std::runtime_error("expected --bind NAME=ADDRESS"); image.symbolBindings.push_back(std::move(b)); }
            else if (arg == "--base" || arg == "--image-base" || arg == "--start" || arg == "--count") {
                const auto t=need(arg.c_str()); const auto v=parseUnsigned(t); if(!v) throw std::runtime_error("invalid numeric value: "+t);
                if(arg=="--base") image.codeBase=static_cast<std::uint32_t>(*v); else if(arg=="--image-base") image.imageBase=static_cast<std::uint32_t>(*v);
                else if(arg=="--start") start=static_cast<std::uint32_t>(*v); else count=static_cast<std::size_t>(*v);
            } else throw std::runtime_error("unknown disasm option: "+arg);
        } catch(const std::exception& e){ std::cerr<<e.what()<<'\n'; return 1; }
    }
    const unsigned inputs=!image.codePath.empty()+!image.imagePath.empty()+!image.elfPath.empty()+!image.machoPath.empty()+!image.pefPath.empty();
    if(inputs!=1 || count==0){ std::cerr<<"disasm requires exactly one input and --count > 0\n"; return 1; }
    Memory memory; std::uint32_t pc=image.codeBase; std::string error;
    if(!image.codePath.empty()) { const auto sz=fileSize(image.codePath); if(sz==0||!memory.loadFile(image.codeBase,image.codePath,sz,MemoryPerm::Read|MemoryPerm::Execute,"disasm:raw")){std::cerr<<"disasm: cannot map raw code\n";return 1;} pc=start.value_or(image.codeBase); }
    else if(!image.imagePath.empty()) { UniversalImageInfo i{}; if(!UniversalImageLoader::loadFile(image.imagePath,memory,i,error,image.imageBase,image.symbolBindings)){std::cerr<<"disasm: "<<error<<'\n';return 1;} pc=start.value_or(i.entry); }
    else if(!image.elfPath.empty()) { Elf32ImageInfo i{}; if(!Elf32Loader::loadFile(image.elfPath,memory,i,error,image.imageBase,image.symbolBindings)){std::cerr<<"disasm: "<<error<<'\n';return 1;} pc=start.value_or(i.entry); }
    else if(!image.machoPath.empty()) { MachOImageInfo i{}; if(!MachOLoader::loadFile(image.machoPath,memory,i,error,image.imageBase,image.symbolBindings)){std::cerr<<"disasm: "<<error<<'\n';return 1;} pc=start.value_or(i.entry); }
    else { PefImageInfo i{}; if(!PefLoader::loadFile(image.pefPath,memory,i,error,image.imageBase,image.symbolBindings)){std::cerr<<"disasm: "<<error<<'\n';return 1;} pc=start.value_or(i.entry); }
    if(pc==0){ for(const auto& r:memory.regions()) if(hasPerm(r.perms,MemoryPerm::Execute)){pc=r.base;break;} }
    if(pc==0){std::cerr<<"disasm: no executable entry/region\n";return 1;}
    for(std::size_t i=0;i<count;++i,pc+=4U){std::uint32_t ins=0;if(!memory.executable(pc,4)||!memory.read32(pc,ins)){std::cerr<<"disasm: stopped at "<<hex32(pc)<<" (not executable/mapped)\n";return i==0?1:0;} std::cout<<hex32(pc)<<"  "<<hex32(ins)<<"  "<<BuiltinInterpreter::disassemble(pc,ins)<<'\n';}
    return 0;
}

} // namespace

int main(int argc, char** argv) {
    if (argc < 2) { usage(); return 1; }
    const std::string command = argv[1];
    if (command == "--version" || command == "version") { std::cout << "PPC Lab " << kVersion << "\n"; return 0; }
    if (command == "doctor") return commandDoctor(argc, argv);
    if (command == "capabilities") return commandCapabilities(argc, argv);
    if (command == "analyze") return commandAnalyze(argc, argv);
    if (command == "selftest") {
        std::string backendName="auto"; for(int i=2;i<argc;++i){std::string a=argv[i];if(a=="--backend"&&i+1<argc)backendName=argv[++i];else{std::cerr<<"unknown selftest option: "<<a<<'\n';return 1;}}
        std::string error; auto backend=makeBackend(backendName,error); if(!backend){std::cerr<<error<<'\n';return 7;} const auto r=runMicrotests(*backend); std::cout<<r.report; return r.passed?0:1;
    }
    if(command=="image-info") return commandInfo(argc,argv,std::nullopt);
    if(command=="elf-info") return commandInfo(argc,argv,ImageKind::Elf);
    if(command=="macho-info") return commandInfo(argc,argv,ImageKind::MachO);
    if(command=="pef-info") return commandInfo(argc,argv,ImageKind::Pef);
    if(command=="symbols") return commandSymbols(argc,argv);
    if(command=="metadata") return commandMetadata(argc,argv);
    if(command=="disasm") return commandDisasm(argc,argv);
    if(command!="call" && command!="run"){usage();return 1;}

    CallConfig config{}; std::string backendName="auto",jsonPath,snapshotPath; std::vector<DumpRequest>dumps;
    for(int i=2;i<argc;++i){const std::string arg=argv[i];auto need=[&](const char*o){if(i+1>=argc)throw std::runtime_error(std::string(o)+" requires a value");return std::string(argv[++i]);};
        try{
            if(arg=="--backend")backendName=need("--backend"); else if(arg=="--code")config.image.codePath=need("--code"); else if(arg=="--image")config.image.imagePath=need("--image"); else if(arg=="--elf")config.image.elfPath=need("--elf"); else if(arg=="--macho")config.image.machoPath=need("--macho"); else if(arg=="--pef")config.image.pefPath=need("--pef"); else if(arg=="--data")config.image.dataPath=need("--data"); else if(arg=="--entry-symbol")config.entrySymbol=need("--entry-symbol"); else if(arg=="--bind"){SymbolBinding b{};auto t=need("--bind");if(!parseBinding(t,b))throw std::runtime_error("expected --bind NAME=ADDRESS");config.image.symbolBindings.push_back(std::move(b));}
            else if(arg=="--trace")config.execution.trace=true; else if(arg=="--ignore-traps")config.execution.ignoreTraps=true; else if(arg=="--json")jsonPath=need("--json"); else if(arg=="--snapshot")snapshotPath=need("--snapshot");
            else if(arg=="--entry"||arg=="--transition-vector"||arg=="--toc"||arg=="--image-base"||arg=="--code-base"||arg=="--data-base"||arg=="--data-map-size"||arg=="--heap-base"||arg=="--heap-size"||arg=="--stack-base"||arg=="--stack-size"||arg=="--import-base"||arg=="--import-size"||arg=="--return"||arg=="--max-instructions"){
                auto t=need(arg.c_str());auto v=parseUnsigned(t);if(!v)throw std::runtime_error("invalid numeric value: "+t);
                if(arg=="--entry")config.entry=std::uint32_t(*v);else if(arg=="--transition-vector")config.transitionVector=std::uint32_t(*v);else if(arg=="--toc")config.toc=std::uint32_t(*v);else if(arg=="--image-base")config.image.imageBase=std::uint32_t(*v);else if(arg=="--code-base")config.image.codeBase=std::uint32_t(*v);else if(arg=="--data-base")config.image.dataBase=std::uint32_t(*v);else if(arg=="--data-map-size")config.image.dataMapSize=std::size_t(*v);else if(arg=="--heap-base")config.image.heapBase=std::uint32_t(*v);else if(arg=="--heap-size")config.image.heapSize=std::size_t(*v);else if(arg=="--stack-base")config.image.stackBase=std::uint32_t(*v);else if(arg=="--stack-size")config.image.stackSize=std::size_t(*v);else if(arg=="--import-base")config.execution.importBase=std::uint32_t(*v);else if(arg=="--import-size")config.execution.importSize=std::uint32_t(*v);else if(arg=="--return")config.execution.returnAddress=std::uint32_t(*v);else config.execution.instructionLimit=*v;
            } else if(arg=="--stub"){auto t=need("--stub");auto p=t.find('@');if(p==std::string::npos||p==0||p+1>=t.size())throw std::runtime_error("expected --stub KIND@ADDRESS");ImportStubKind k{};if(!parseImportStubKind(std::string_view(t).substr(0,p),k))throw std::runtime_error("unknown stub kind: "+t.substr(0,p));auto a=parseUnsigned(std::string_view(t).substr(p+1));if(!a||*a>0xffffffffULL)throw std::runtime_error("invalid stub address");config.execution.importStubs.push_back({std::uint32_t(*a),k,t.substr(0,p)});
            } else if(arg=="--syscall-return"){auto t=need("--syscall-return");std::string_view l,r;if(!splitAssignment(t,l,r))throw std::runtime_error("expected --syscall-return NUMBER=VALUE");auto n=parseUnsigned(l),v=parseUnsigned(r);if(!n||!v||*n>0xffffffffULL||*v>0xffffffffULL)throw std::runtime_error("invalid --syscall-return");config.execution.systemCallStubs.push_back({std::uint32_t(*n),std::uint32_t(*v)});
            } else if(arg=="--default-syscall-return"){auto t=need("--default-syscall-return");auto v=parseUnsigned(t);if(!v||*v>0xffffffffULL)throw std::runtime_error("invalid --default-syscall-return");config.execution.defaultSystemCallReturn=std::uint32_t(*v);
            } else if(arg=="--set"){auto t=need("--set");std::string_view l,r;if(!splitAssignment(t,l,r)||l.size()<2||l[0]!='r')throw std::runtime_error("expected --set rN=VALUE");auto reg=parseUnsigned(l.substr(1)),v=parseUnsigned(r);if(!reg||!v||*reg>=32)throw std::runtime_error("invalid GPR assignment");config.registers.push_back({unsigned(*reg),std::uint32_t(*v)});
            } else if(arg=="--set-f"){auto t=need("--set-f");std::string_view l,r;if(!splitAssignment(t,l,r)||l.size()<2||l[0]!='f')throw std::runtime_error("expected --set-f fN=VALUE");auto reg=parseUnsigned(l.substr(1));auto v=parseDouble(r);if(!reg||!v||*reg>=32)throw std::runtime_error("invalid FPR assignment");config.floatRegisters.push_back({unsigned(*reg),*v});
            } else if(arg=="--write-u32"){auto t=need("--write-u32");std::string_view l,r;if(!splitAssignment(t,l,r))throw std::runtime_error("expected ADDRESS=VALUE");auto a=parseUnsigned(l),v=parseUnsigned(r);if(!a||!v)throw std::runtime_error("invalid --write-u32");config.writes32.push_back({std::uint32_t(*a),std::uint32_t(*v)});
            } else if(arg=="--write-f32"){auto t=need("--write-f32");std::string_view l,r;if(!splitAssignment(t,l,r))throw std::runtime_error("expected ADDRESS=VALUE");auto a=parseUnsigned(l);auto v=parseDouble(r);if(!a||!v)throw std::runtime_error("invalid --write-f32");config.writesFloat.push_back({std::uint32_t(*a),float(*v)});
            } else if(arg=="--dump"||arg=="--trace-range"){auto t=need(arg.c_str());auto p=t.find(':');if(p==std::string::npos)throw std::runtime_error("expected START:END/SIZE");auto a=parseUnsigned(std::string_view(t).substr(0,p)),b=parseUnsigned(std::string_view(t).substr(p+1));if(!a||!b)throw std::runtime_error("invalid range");if(arg=="--dump")dumps.push_back({std::uint32_t(*a),std::size_t(*b)});else config.execution.traceRange=TraceRange{std::uint32_t(*a),std::uint32_t(*b)};
            } else throw std::runtime_error("unknown option: "+arg);
        }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
    }
    std::string be;auto backend=makeBackend(backendName,be);if(!backend){std::cerr<<be<<'\n';return 7;}const auto result=CallHarness::run(config,*backend);
    std::cout<<"PPC Lab\nbackend="<<backend->name()<<"\nstop="<<stopReasonName(result.execution.reason)<<"\ninstructions="<<result.execution.instructions<<"\npc="<<hex32(result.execution.pc)<<'\n';if(!result.execution.message.empty())std::cout<<"message="<<result.execution.message<<'\n';printCpu(result.cpu);
    for(const auto&d:dumps){auto f=dumpFnv1a64(result.memory,d.address,d.size);std::cout<<"dump "<<hex32(d.address)<<':'<<d.size<<" fnv1a64="<<(f?hex64(*f):"unreadable")<<"  "<<dumpHex(result.memory,d.address,d.size)<<'\n';}
    if(!jsonPath.empty())try{writeJson(jsonPath,backend->name(),result,dumps);std::cout<<"json="<<jsonPath<<'\n';}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
    if(!snapshotPath.empty())try{writeSnapshot(snapshotPath,backend->name(),result,dumps);std::cout<<"snapshot="<<snapshotPath<<'\n';}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
    return stopExitCode(result.execution.reason);
}
