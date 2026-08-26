// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/BuiltinInterpreter.hpp"
#include "ppclab/ppc/CallHarness.hpp"
#include "ppclab/ppc/Microtests.hpp"
#include "ppclab/ppc/ImportStubs.hpp"
#include "ppclab/ppc/UnicornBackend.hpp"

#include <bit>
#include <charconv>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace ppclab::ppc;

struct DumpRequest {
    std::uint32_t address = 0;
    std::size_t size = 0;
};

std::optional<std::uint64_t> parseUnsigned(std::string_view text) {
    int base = 10;
    if (text.size() > 2 && text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) {
        text.remove_prefix(2);
        base = 16;
    }
    std::uint64_t value = 0;
    const auto* begin = text.data();
    const auto* end = text.data() + text.size();
    auto [ptr, ec] = std::from_chars(begin, end, value, base);
    if (ec != std::errc{} || ptr != end) return std::nullopt;
    return value;
}

std::optional<double> parseDouble(std::string_view text) {
    try {
        std::size_t consumed = 0;
        double value = std::stod(std::string(text), &consumed);
        if (consumed != text.size()) return std::nullopt;
        return value;
    } catch (...) {
        return std::nullopt;
    }
}

bool splitAssignment(std::string_view text, std::string_view& left, std::string_view& right) {
    const auto pos = text.find('=');
    if (pos == std::string_view::npos || pos == 0 || pos + 1 >= text.size()) return false;
    left = text.substr(0, pos);
    right = text.substr(pos + 1);
    return true;
}

std::string hex32(std::uint32_t value) {
    std::ostringstream out;
    out << "0x" << std::hex << std::setw(8) << std::setfill('0') << value;
    return out.str();
}

std::unique_ptr<ExecutionBackend> makeBackend(const std::string& requested, std::string& error) {
    if (requested == "builtin") return std::make_unique<BuiltinInterpreter>();
    if (requested == "unicorn") {
        if (!UnicornBackend::available()) {
            error = "Unicorn backend not available in this build";
            return {};
        }
        return std::make_unique<UnicornBackend>();
    }
    if (requested == "auto") {
        if (UnicornBackend::available()) return std::make_unique<UnicornBackend>();
        return std::make_unique<BuiltinInterpreter>();
    }
    error = "unknown backend: " + requested;
    return {};
}

void usage() {
    std::cout << R"(PPC Lab — deterministic PowerPC execution and reverse-engineering harness

Usage:
  ppc-lab selftest [--backend auto|builtin|unicorn]
  ppc-lab call --code FILE [--data FILE]
      (--entry HEX | --transition-vector HEX)
      [--backend auto|builtin|unicorn]
      [--code-base HEX] [--data-base HEX] [--data-map-size N]
      [--heap-base HEX] [--heap-size N]
      [--stack-base HEX] [--stack-size N]
      [--import-base HEX] [--import-size N] [--return HEX]
      [--toc HEX] [--max-instructions N]
      [--set rN=VALUE] [--set-f fN=VALUE]
      [--write-u32 ADDRESS=VALUE] [--write-f32 ADDRESS=VALUE]
      [--stub KIND@ADDRESS]
      [--dump ADDRESS:SIZE]
      [--trace] [--trace-range START:END]
      [--json FILE]

Built-in stub kinds:
  pow cos sqrt sin exp blockmove

Default deterministic map (all configurable):
  CODE    0x10000000
  DATA    0x20000000
  imports 0x30000000
  heap    0x40000000
  stack   0x70000000
  return  0x7fff0000

Examples:
  ppc-lab selftest --backend builtin
  ppc-lab call --code code.bin --entry 0x10000000 --set r3=5 --dump 0x40000000:64
  ppc-lab call --code code.bin --entry 0x10000000 --stub sin@0x30000014

PPC Lab contains no target-program code. Target binaries, relocated sections and
firmware images are always supplied externally at runtime.
)";
}
void printCpu(const CpuState& cpu) {
    std::cout << "pc=" << hex32(cpu.pc)
              << " lr=" << hex32(cpu.lr)
              << " ctr=" << hex32(cpu.ctr)
              << " cr=" << hex32(cpu.cr) << '\n';
    for (unsigned row = 0; row < 4; ++row) {
        for (unsigned col = 0; col < 8; ++col) {
            const unsigned r = row * 8 + col;
            std::cout << 'r' << std::setw(2) << std::setfill('0') << r << '='
                      << hex32(cpu.gpr[r]) << (col == 7 ? '\n' : ' ');
        }
    }
    std::cout << std::setfill(' ');
}

std::string dumpHex(const Memory& memory, std::uint32_t address, std::size_t size) {
    std::vector<std::uint8_t> bytes(size);
    if (!memory.readBytes(address, bytes)) return "<unreadable>";
    std::ostringstream out;
    for (std::size_t i = 0; i < bytes.size(); ++i) {
        if (i) out << ' ';
        out << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned>(bytes[i]);
    }
    return out.str();
}

std::optional<std::uint64_t> dumpFnv1a64(const Memory& memory, std::uint32_t address, std::size_t size) {
    std::vector<std::uint8_t> bytes(size);
    if (!memory.readBytes(address, bytes)) return std::nullopt;
    std::uint64_t hash = 14695981039346656037ULL;
    for (const auto byte : bytes) {
        hash ^= static_cast<std::uint64_t>(byte);
        hash *= 1099511628211ULL;
    }
    return hash;
}

std::string hex64(std::uint64_t value) {
    std::ostringstream out;
    out << "0x" << std::hex << std::setw(16) << std::setfill('0') << value;
    return out.str();
}

void writeJson(const std::string& path,
               const std::string& backend,
               const CallResult& result,
               const std::vector<DumpRequest>& dumps) {
    std::ofstream out(path);
    if (!out) throw std::runtime_error("cannot open JSON output: " + path);
    out << "{\n"
        << "  \"schema\": \"ppc-lab-result-v1\",\n"
        << "  \"backend\": \"" << backend << "\",\n"
        << "  \"stop_reason\": \"" << stopReasonName(result.execution.reason) << "\",\n"
        << "  \"instructions\": " << result.execution.instructions << ",\n"
        << "  \"pc\": \"" << hex32(result.execution.pc) << "\",\n"
        << "  \"instruction\": \"" << hex32(result.execution.instruction) << "\",\n"
        << "  \"registers\": {\n";
    for (unsigned i = 0; i < 32; ++i) {
        out << "    \"r" << i << "\": \"" << hex32(result.cpu.gpr[i]) << "\""
            << (i == 31 ? '\n' : ',') << (i == 31 ? "" : "\n");
    }
    out << "  },\n"
        << "  \"lr\": \"" << hex32(result.cpu.lr) << "\",\n"
        << "  \"ctr\": \"" << hex32(result.cpu.ctr) << "\",\n"
        << "  \"cr\": \"" << hex32(result.cpu.cr) << "\",\n"
        << "  \"dumps\": [\n";
    for (std::size_t i = 0; i < dumps.size(); ++i) {
        const auto fnv = dumpFnv1a64(result.memory, dumps[i].address, dumps[i].size);
        out << "    {\"address\": \"" << hex32(dumps[i].address)
            << "\", \"size\": " << dumps[i].size
            << ", \"fnv1a64\": \"" << (fnv ? hex64(*fnv) : std::string("unreadable"))
            << "\", \"hex\": \"" << dumpHex(result.memory, dumps[i].address, dumps[i].size) << "\"}"
            << (i + 1 == dumps.size() ? '\n' : ',') << (i + 1 == dumps.size() ? "" : "\n");
    }
    out << "  ]\n}\n";
}

int stopExitCode(StopReason reason) {
    switch (reason) {
    case StopReason::Returned: return 0;
    case StopReason::UnsupportedInstruction: return 2;
    case StopReason::MemoryFault: return 3;
    case StopReason::ImportTrap: return 4;
    case StopReason::InstructionLimit: return 5;
    case StopReason::InvalidConfiguration: return 6;
    case StopReason::BackendError: return 7;
    }
    return 7;
}

} // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        usage();
        return 1;
    }
    const std::string command = argv[1];

    if (command == "selftest") {
        std::string backendName = "auto";
        for (int i = 2; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--backend" && i + 1 < argc) backendName = argv[++i];
            else {
                std::cerr << "unknown selftest option: " << arg << '\n';
                return 1;
            }
        }
        std::string error;
        auto backend = makeBackend(backendName, error);
        if (!backend) {
            std::cerr << error << '\n';
            return 7;
        }
        const auto result = runMicrotests(*backend);
        std::cout << result.report;
        return result.passed ? 0 : 1;
    }

    if (command != "call") {
        usage();
        return 1;
    }

    CallConfig config{};
    std::string backendName = "auto";
    std::string jsonPath;
    std::vector<DumpRequest> dumps;

    for (int i = 2; i < argc; ++i) {
        const std::string arg = argv[i];
        auto needValue = [&](const char* option) -> std::string {
            if (i + 1 >= argc) throw std::runtime_error(std::string(option) + " requires a value");
            return argv[++i];
        };
        try {
            if (arg == "--backend") backendName = needValue("--backend");
            else if (arg == "--code") config.image.codePath = needValue("--code");
            else if (arg == "--data") config.image.dataPath = needValue("--data");
            else if (arg == "--trace") config.execution.trace = true;
                        else if (arg == "--json") jsonPath = needValue("--json");
            else if (arg == "--entry" || arg == "--transition-vector" || arg == "--toc" ||
                     arg == "--code-base" || arg == "--data-base" || arg == "--data-map-size" ||
                     arg == "--heap-base" || arg == "--heap-size" ||
                     arg == "--stack-base" || arg == "--stack-size" ||
                     arg == "--import-base" || arg == "--import-size" || arg == "--return" ||
                     arg == "--max-instructions") {
                const auto text = needValue(arg.c_str());
                const auto parsed = parseUnsigned(text);
                if (!parsed) throw std::runtime_error("invalid numeric value: " + text);
                if (arg == "--entry") config.entry = static_cast<std::uint32_t>(*parsed);
                else if (arg == "--transition-vector") config.transitionVector = static_cast<std::uint32_t>(*parsed);
                else if (arg == "--toc") config.toc = static_cast<std::uint32_t>(*parsed);
                else if (arg == "--code-base") config.image.codeBase = static_cast<std::uint32_t>(*parsed);
                else if (arg == "--data-base") config.image.dataBase = static_cast<std::uint32_t>(*parsed);
                else if (arg == "--data-map-size") config.image.dataMapSize = static_cast<std::size_t>(*parsed);
                else if (arg == "--heap-base") config.image.heapBase = static_cast<std::uint32_t>(*parsed);
                else if (arg == "--heap-size") config.image.heapSize = static_cast<std::size_t>(*parsed);
                else if (arg == "--stack-base") config.image.stackBase = static_cast<std::uint32_t>(*parsed);
                else if (arg == "--stack-size") config.image.stackSize = static_cast<std::size_t>(*parsed);
                else if (arg == "--import-base") config.execution.importBase = static_cast<std::uint32_t>(*parsed);
                else if (arg == "--import-size") config.execution.importSize = static_cast<std::uint32_t>(*parsed);
                else if (arg == "--return") config.execution.returnAddress = static_cast<std::uint32_t>(*parsed);
                else config.execution.instructionLimit = *parsed;
            } else if (arg == "--stub") {
                const auto text = needValue("--stub");
                const auto pos = text.find('@');
                if (pos == std::string::npos || pos == 0 || pos + 1 >= text.size())
                    throw std::runtime_error("expected --stub KIND@ADDRESS");
                ImportStubKind kind{};
                if (!parseImportStubKind(std::string_view(text).substr(0, pos), kind))
                    throw std::runtime_error("unknown stub kind: " + text.substr(0, pos));
                const auto address = parseUnsigned(std::string_view(text).substr(pos + 1));
                if (!address || *address > 0xffffffffULL)
                    throw std::runtime_error("invalid stub address");
                config.execution.importStubs.push_back({static_cast<std::uint32_t>(*address), kind,
                                                        text.substr(0, pos)});
            } else if (arg == "--set") {
                const auto text = needValue("--set");
                std::string_view left, right;
                if (!splitAssignment(text, left, right) || left.size() < 2 || left[0] != 'r')
                    throw std::runtime_error("expected --set rN=VALUE");
                const auto reg = parseUnsigned(left.substr(1));
                const auto value = parseUnsigned(right);
                if (!reg || !value || *reg >= 32) throw std::runtime_error("invalid GPR assignment");
                config.registers.push_back({static_cast<unsigned>(*reg), static_cast<std::uint32_t>(*value)});
            } else if (arg == "--set-f") {
                const auto text = needValue("--set-f");
                std::string_view left, right;
                if (!splitAssignment(text, left, right) || left.size() < 2 || left[0] != 'f')
                    throw std::runtime_error("expected --set-f fN=VALUE");
                const auto reg = parseUnsigned(left.substr(1));
                const auto value = parseDouble(right);
                if (!reg || !value || *reg >= 32) throw std::runtime_error("invalid FPR assignment");
                config.floatRegisters.push_back({static_cast<unsigned>(*reg), *value});
            } else if (arg == "--write-u32") {
                const auto text = needValue("--write-u32");
                std::string_view left, right;
                if (!splitAssignment(text, left, right)) throw std::runtime_error("expected ADDRESS=VALUE");
                const auto address = parseUnsigned(left), value = parseUnsigned(right);
                if (!address || !value) throw std::runtime_error("invalid --write-u32");
                config.writes32.push_back({static_cast<std::uint32_t>(*address), static_cast<std::uint32_t>(*value)});
            } else if (arg == "--write-f32") {
                const auto text = needValue("--write-f32");
                std::string_view left, right;
                if (!splitAssignment(text, left, right)) throw std::runtime_error("expected ADDRESS=VALUE");
                const auto address = parseUnsigned(left);
                const auto value = parseDouble(right);
                if (!address || !value) throw std::runtime_error("invalid --write-f32");
                config.writesFloat.push_back({static_cast<std::uint32_t>(*address), static_cast<float>(*value)});
            } else if (arg == "--dump" || arg == "--trace-range") {
                const auto text = needValue(arg.c_str());
                const auto pos = text.find(':');
                if (pos == std::string::npos) throw std::runtime_error("expected START:END/SIZE");
                const auto first = parseUnsigned(std::string_view(text).substr(0, pos));
                const auto second = parseUnsigned(std::string_view(text).substr(pos + 1));
                if (!first || !second) throw std::runtime_error("invalid range");
                if (arg == "--dump") dumps.push_back({static_cast<std::uint32_t>(*first), static_cast<std::size_t>(*second)});
                else config.execution.traceRange = TraceRange{static_cast<std::uint32_t>(*first), static_cast<std::uint32_t>(*second)};
            } else {
                throw std::runtime_error("unknown option: " + arg);
            }
        } catch (const std::exception& e) {
            std::cerr << e.what() << '\n';
            return 1;
        }
    }

    std::string backendError;
    auto backend = makeBackend(backendName, backendError);
    if (!backend) {
        std::cerr << backendError << '\n';
        return 7;
    }

    const auto result = CallHarness::run(config, *backend);
    std::cout << "PPC Lab\n"
              << "backend=" << backend->name() << '\n'
              << "stop=" << stopReasonName(result.execution.reason) << '\n'
              << "instructions=" << result.execution.instructions << '\n'
              << "pc=" << hex32(result.execution.pc) << '\n';
    if (!result.execution.message.empty()) std::cout << "message=" << result.execution.message << '\n';
    printCpu(result.cpu);
    for (const auto& dump : dumps) {
        const auto fnv = dumpFnv1a64(result.memory, dump.address, dump.size);
        std::cout << "dump " << hex32(dump.address) << ':' << dump.size
                  << " fnv1a64=" << (fnv ? hex64(*fnv) : std::string("unreadable")) << "  "
                  << dumpHex(result.memory, dump.address, dump.size) << '\n';
    }
    if (!jsonPath.empty()) {
        try {
            writeJson(jsonPath, backend->name(), result, dumps);
            std::cout << "json=" << jsonPath << '\n';
        } catch (const std::exception& e) {
            std::cerr << e.what() << '\n';
            return 1;
        }
    }
    return stopExitCode(result.execution.reason);
}
