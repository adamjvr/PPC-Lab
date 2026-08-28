// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/BuiltinInterpreter.hpp"
#include "ppclab/ppc/Memory.hpp"
#include <cassert>
#include <cstdint>
#include <iostream>
#include <random>
#include <vector>
using namespace ppclab::ppc;
namespace {
constexpr std::uint32_t x(unsigned rt,unsigned ra,unsigned rb,unsigned xo,bool rc=false){return (31U<<26U)|(rt<<21U)|(ra<<16U)|(rb<<11U)|(xo<<1U)|(rc?1U:0U);}
constexpr std::uint32_t blr(){return 0x4e800020U;}
std::vector<std::uint8_t> words(std::uint32_t a){return {std::uint8_t(a>>24),std::uint8_t(a>>16),std::uint8_t(a>>8),std::uint8_t(a),0x4e,0x80,0x00,0x20};}
std::uint32_t runOne(std::uint32_t ins,std::uint32_t a,std::uint32_t b,std::uint32_t& xer){
    Memory m;auto code=words(ins);assert(m.load(0x10000000,code,MemoryPerm::Read|MemoryPerm::Execute,"property"));CpuState c{};c.pc=0x10000000;c.lr=0x7fff0000;c.gpr[3]=a;c.gpr[4]=b;BuiltinInterpreter bi;ExecutionConfig cfg{};cfg.instructionLimit=4;auto r=bi.run(m,c,cfg);assert(r.ok());xer=c.xer;return c.gpr[5];
}
}
int main(){
    std::mt19937 rng(0x50504335U);
    for(unsigned i=0;i<2000;++i){
        const std::uint32_t a=rng(),b=rng();std::uint32_t xer=0;
        assert(runOne(x(3,5,4,60),a,b,xer)==(a & ~b)); // andc RT/RA field aliasing: result in r5
        assert(runOne(x(3,5,4,284),a,b,xer)==~(a ^ b));
        assert(runOne(x(3,5,4,476),a,b,xer)==~(a & b));
        const auto product=static_cast<std::uint64_t>(a)*b;
        assert(runOne(x(5,3,4,11),a,b,xer)==static_cast<std::uint32_t>(product>>32U));
    }
    // Decoder must remain total over arbitrary 32-bit words: no exceptions, bounded output.
    for(unsigned i=0;i<10000;++i){auto text=BuiltinInterpreter::disassemble(rng(),rng());assert(!text.empty());assert(text.size()<256);}
    // Memory boundary/property checks.
    for(unsigned i=0;i<1000;++i){Memory m;const std::uint32_t base=0x10000U+(i*0x100U);assert(m.map(base,64,MemoryPerm::Read|MemoryPerm::Write,"fuzz"));const auto off=rng()%61U;const auto value=rng();assert(m.write32(base+off,value));std::uint32_t got=0;assert(m.read32(base+off,got));assert(got==value);assert(!m.write32(base+62,value));}
    std::cout<<"deterministic property tests passed\n";return 0;
}
