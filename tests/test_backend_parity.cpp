// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/BuiltinInterpreter.hpp"
#include "ppclab/ppc/UnicornBackend.hpp"
#include "ppclab/ppc/Memory.hpp"
#include <cassert>
#include <cstdint>
#include <iostream>
#include <vector>
using namespace ppclab::ppc;
namespace {
constexpr std::uint32_t x(unsigned rt,unsigned ra,unsigned rb,unsigned xo,bool rc=false){return (31U<<26U)|(rt<<21U)|(ra<<16U)|(rb<<11U)|(xo<<1U)|(rc?1U:0U);}
constexpr std::uint32_t d(unsigned op,unsigned rt,unsigned ra,unsigned imm){return (op<<26U)|(rt<<21U)|(ra<<16U)|(imm&0xffffU);}
std::vector<std::uint8_t> bytes(std::initializer_list<std::uint32_t> ws){std::vector<std::uint8_t>b;for(auto w:ws){b.push_back(w>>24);b.push_back(w>>16);b.push_back(w>>8);b.push_back(w);}return b;}
struct State{CpuState cpu;Memory memory;ExecutionResult result;};
State run(ExecutionBackend& backend){State s{};auto code=bytes({d(14,3,3,7),x(5,3,4,235),x(6,3,4,11),x(3,7,4,60),0x4e800020U});assert(s.memory.load(0x10000000,code,MemoryPerm::Read|MemoryPerm::Execute,"parity"));s.cpu.pc=0x10000000;s.cpu.lr=0x7fff0000;s.cpu.gpr[3]=0x12345678;s.cpu.gpr[4]=17;ExecutionConfig c{};c.instructionLimit=32;s.result=backend.run(s.memory,s.cpu,c);return s;}
}
int main(){if(!UnicornBackend::available()){std::cout<<"SKIP unicorn unavailable\n";return 0;}BuiltinInterpreter b;UnicornBackend u;auto a=run(b),c=run(u);assert(a.result.reason==c.result.reason);for(unsigned i=0;i<32;++i)assert(a.cpu.gpr[i]==c.cpu.gpr[i]);assert(a.cpu.cr==c.cpu.cr);assert(a.cpu.xer==c.cpu.xer);std::cout<<"builtin/unicorn parity passed\n";return 0;}
