// SPDX-License-Identifier: GPL-3.0-only
#include "ppclab/ppc/ImportStubs.hpp"
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
using namespace ppclab::ppc;
int main(){
    Memory mem; assert(mem.map(0x40000000,0x1000,MemoryPerm::Read|MemoryPerm::Write,"test"));
    const std::uint8_t src[]={1,2,3,4,5}; assert(mem.writeBytes(0x40000020,src)); CpuState cpu{};
    cpu.gpr[3]=0x40000080; cpu.gpr[4]=0x40000020; cpu.gpr[5]=5;
    auto r=executeImportStub({0,ImportStubKind::Memcpy,"memcpy"},mem,cpu); assert(r.success && cpu.gpr[3]==0x40000080);
    std::uint8_t out[5]{}; assert(mem.readBytes(0x40000080,out)); for(unsigned i=0;i<5;++i) assert(out[i]==src[i]);
    cpu.gpr[3]=0x40000090; cpu.gpr[4]=0xaa; cpu.gpr[5]=4; r=executeImportStub({0,ImportStubKind::Memset,"memset"},mem,cpu); assert(r.success);
    std::uint8_t fill[4]{}; assert(mem.readBytes(0x40000090,fill)); for(auto b:fill) assert(b==0xaa);
    cpu.gpr[3]=0x40000090; cpu.gpr[4]=4; r=executeImportStub({0,ImportStubKind::Bzero,"bzero"},mem,cpu); assert(r.success); assert(mem.readBytes(0x40000090,fill)); for(auto b:fill) assert(b==0);
    cpu.fpr[1]=-3.25; r=executeImportStub({0,ImportStubKind::Fabs,"fabs"},mem,cpu); assert(r.success && std::fabs(cpu.fpr[1]-3.25)<1e-12);
    std::cout<<"runtime stub tests passed\n"; return 0;
}
