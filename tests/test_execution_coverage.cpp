// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/BuiltinInterpreter.hpp"
#include "ppclab/ppc/Execution.hpp"
#include "ppclab/ppc/Memory.hpp"

#include <cassert>
#include <bit>
#include <cstdint>
#include <iostream>
#include <span>
#include <string>
#include <vector>

using namespace ppclab::ppc;

namespace {
constexpr std::uint32_t xForm(unsigned op, unsigned rt, unsigned ra, unsigned rb, unsigned xo, bool rc=false) {
    return (op<<26U)|(rt<<21U)|(ra<<16U)|(rb<<11U)|(xo<<1U)|(rc?1U:0U);
}
constexpr std::uint32_t dForm(unsigned op,unsigned rt,unsigned ra,std::uint16_t imm) {
    return (op<<26U)|(rt<<21U)|(ra<<16U)|imm;
}
constexpr std::uint32_t blr(){ return 0x4e800020U; }
std::vector<std::uint8_t> words(std::initializer_list<std::uint32_t> v){
    std::vector<std::uint8_t>b; for(auto w:v){b.push_back(w>>24U);b.push_back(w>>16U);b.push_back(w>>8U);b.push_back(w);}return b;
}
ExecutionResult run(const std::vector<std::uint8_t>& code, CpuState& cpu, Memory& memory, ExecutionConfig cfg={}) {
    assert(memory.load(0x10000000U,code,MemoryPerm::Read|MemoryPerm::Execute,"coverage-code"));
    if (!memory.find(0x70000000U, 1)) assert(memory.map(0x70000000U,0x10000,MemoryPerm::Read|MemoryPerm::Write,"stack"));
    cpu.pc=0x10000000U; cpu.lr=cfg.returnAddress; cpu.gpr[1]=0x7000fff0U; cfg.instructionLimit=1000;
    BuiltinInterpreter backend; return backend.run(memory,cpu,cfg);
}
}

int main(){
    // Structured syscall: unbound stops; bound returns through r3 and execution resumes.
    {
        auto code=words({0x44000002U,dForm(14,3,3,1),blr()}); // sc; addi r3,r3,1; blr
        Memory m; CpuState c{}; c.gpr[0]=42; c.gpr[3]=7;
        auto r=run(code,c,m); assert(r.reason==StopReason::SystemCall); assert(r.pc==0x10000000U);
        Memory m2; CpuState c2{}; c2.gpr[0]=42; c2.gpr[3]=7; ExecutionConfig cfg{}; cfg.systemCallStubs.push_back({42,99});
        r=run(code,c2,m2,cfg); assert(r.ok()); assert(c2.gpr[3]==100U);
    }
    // Trap interception and intentional ignore mode.
    {
        const std::uint32_t twi=(3U<<26U)|(4U<<21U)|(3U<<16U)|10U; // tweqi r3,10
        auto code=words({twi,dForm(14,3,3,1),blr()});
        Memory m; CpuState c{}; c.gpr[3]=10; auto r=run(code,c,m); assert(r.reason==StopReason::Trap);
        Memory m2; CpuState c2{}; c2.gpr[3]=10; ExecutionConfig cfg{}; cfg.ignoreTraps=true;
        r=run(code,c2,m2,cfg); assert(r.ok()); assert(c2.gpr[3]==11U);
    }
    // Atomic reservation pair.
    {
        auto code=words({xForm(31,5,0,3,20),dForm(14,5,5,1),xForm(31,5,0,3,150,true),blr()});
        Memory m; assert(m.map(0x40000000U,0x1000,MemoryPerm::Read|MemoryPerm::Write,"atomic")); assert(m.write32(0x40000020U,41));
        CpuState c{}; c.gpr[3]=0x40000020U; auto r=run(code,c,m); assert(r.ok());
        std::uint32_t v=0; assert(m.read32(0x40000020U,v)); assert(v==42U); assert((c.cr & 0x20000000U)!=0); assert(!c.reservationValid);
    }
    // Byte-reversed memory operations + update-indexed forms.
    {
        auto code=words({xForm(31,5,3,4,534),xForm(31,5,3,4,662),xForm(31,6,3,4,331),blr()});
        Memory m; assert(m.map(0x40000000U,0x1000,MemoryPerm::Read|MemoryPerm::Write,"reverse"));
        assert(m.write32(0x40000008U,0x11223344U)); CpuState c{}; c.gpr[3]=0x40000000U;c.gpr[4]=8;
        auto r=run(code,c,m); assert(r.ok()); assert(c.gpr[5]==0x44332211U); assert(c.gpr[6]==0x1122U); assert(c.gpr[3]==0x40000008U);
    }
    // OE variants update OV/SO and CR logical forms operate on individual CR bits.
    {
        const std::uint32_t crxor=(19U<<26U)|(7U<<21U)|(5U<<16U)|(6U<<11U)|(193U<<1U);
        auto code=words({xForm(31,5,3,4,778,true),crxor,blr()});
        Memory m; CpuState c{}; c.gpr[3]=0x7fffffffU;c.gpr[4]=1;c.cr=0x04000000U; // CR bit5=1, bit6=0; field 1 survives addo. Rc
        auto r=run(code,c,m); assert(r.ok()); assert(c.gpr[5]==0x80000000U); assert((c.xer&0xc0000000U)==0xc0000000U); assert(c.crBit(7));
    }
    // fctiwz + stfiwx give the common float-to-int compiler sequence.
    {
        auto code=words({xForm(63,2,0,1,15),xForm(31,2,3,4,983),blr()});
        Memory m; assert(m.map(0x40000000U,0x1000,MemoryPerm::Read|MemoryPerm::Write,"fp-int"));
        CpuState c{}; c.fpr[1]=3.75;c.gpr[3]=0x40000000U;c.gpr[4]=12; auto r=run(code,c,m); assert(r.ok());
        std::uint32_t v=0; assert(m.read32(0x4000000cU,v)); assert(v==3U);
    }
    // dcbz has an observable deterministic 32-byte zeroing effect.
    {
        auto code=words({xForm(31,0,3,4,1014),blr()});
        Memory m; assert(m.map(0x40000000U,0x1000,MemoryPerm::Read|MemoryPerm::Write,"dcbz"));
        for(unsigned i=0;i<64;++i) assert(m.write8(0x40000000U+i,0xaa));
        CpuState c{};c.gpr[3]=0x40000000U;c.gpr[4]=39;auto r=run(code,c,m);assert(r.ok());
        for(unsigned i=32;i<64;++i){std::uint8_t v=0;assert(m.read8(0x40000000U+i,v));assert(v==0);}
        std::uint8_t v=0; assert(m.read8(0x4000001fU,v)); assert(v==0xaa);
    }
    std::cout << "coverage execution tests passed\n";
    return 0;
}
