// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/BuiltinInterpreter.hpp"
#include "ppclab/ppc/CallHarness.hpp"
#include "ppclab/ppc/Elf32Loader.hpp"

#include <cassert>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <vector>

namespace {
void p16(std::vector<std::uint8_t>& b, std::size_t o, std::uint16_t v){b[o]=v>>8;b[o+1]=v;}
void p32(std::vector<std::uint8_t>& b, std::size_t o, std::uint32_t v){b[o]=v>>24;b[o+1]=v>>16;b[o+2]=v>>8;b[o+3]=v;}

std::filesystem::path makeRel(const std::filesystem::path& dir) {
    constexpr std::size_t textOff=0x40, relaOff=0x4c, symOff=0x58, strOff=0x88, shstrOff=0x98, shOff=0xc0;
    std::vector<std::uint8_t>b(shOff+6*40,0);
    b[0]=0x7f;b[1]='E';b[2]='L';b[3]='F';b[4]=1;b[5]=2;b[6]=1;
    p16(b,16,1);p16(b,18,20);p32(b,20,1);p32(b,32,shOff);p16(b,40,52);p16(b,46,40);p16(b,48,6);p16(b,50,5);
    p32(b,textOff+0,0x48000000U); // b target, relocated
    p32(b,textOff+4,0x38630007U); // target: addi r3,r3,7
    p32(b,textOff+8,0x4e800020U); // blr
    // RELA: offset 0, symbol #2, R_PPC_REL24, addend 0
    p32(b,relaOff,0);p32(b,relaOff+4,(2U<<8)|10U);p32(b,relaOff+8,0);
    const char str[]="\0entry\0target\0"; std::copy(str,str+sizeof(str),b.begin()+strOff);
    // symbol 1 entry: local func section1 @0
    p32(b,symOff+16+0,1);p32(b,symOff+16+4,0);p32(b,symOff+16+8,12);b[symOff+16+12]=0x02;p16(b,symOff+16+14,1);
    // symbol 2 target: global func section1 @4
    p32(b,symOff+32+0,7);p32(b,symOff+32+4,4);p32(b,symOff+32+8,8);b[symOff+32+12]=0x12;p16(b,symOff+32+14,1);
    const char shstr[]="\0.text\0.rela.text\0.symtab\0.strtab\0.shstrtab\0"; std::copy(shstr,shstr+sizeof(shstr),b.begin()+shstrOff);
    auto sh=[&](int n,std::uint32_t name,std::uint32_t type,std::uint32_t flags,std::uint32_t off,std::uint32_t size,std::uint32_t link,std::uint32_t info,std::uint32_t align,std::uint32_t entsize){std::size_t o=shOff+n*40;p32(b,o,name);p32(b,o+4,type);p32(b,o+8,flags);p32(b,o+16,off);p32(b,o+20,size);p32(b,o+24,link);p32(b,o+28,info);p32(b,o+32,align);p32(b,o+36,entsize);};
    sh(1,1,1,0x6,textOff,12,0,0,4,0);
    sh(2,7,4,0,relaOff,12,3,1,4,12);
    sh(3,18,2,0,symOff,48,4,1,4,16);
    sh(4,26,3,0,strOff,sizeof(str),0,0,1,0);
    sh(5,34,3,0,shstrOff,sizeof(shstr),0,0,1,0);
    const auto path=dir/"rel.o";std::ofstream out(path,std::ios::binary);out.write(reinterpret_cast<const char*>(b.data()),b.size());return path;
}
}

int main(){namespace fs=std::filesystem;const auto dir=fs::temp_directory_path()/"ppc_lab_elf_rel";fs::remove_all(dir);fs::create_directories(dir);const auto path=makeRel(dir);
    ppclab::ppc::Elf32ImageInfo info{};std::string error;assert(ppclab::ppc::Elf32Loader::inspectFile(path.string(),info,error));assert(info.type==1);assert(info.relocationCount==1);assert(info.symbols.size()==2);
    ppclab::ppc::Memory mem;assert(ppclab::ppc::Elf32Loader::loadFile(path.string(),mem,info,error,0x12000000U));std::uint32_t branch=0;assert(mem.read32(0x12000000U,branch));assert(branch==0x48000004U);
    ppclab::ppc::CallConfig cfg{};cfg.image.elfPath=path.string();cfg.image.imageBase=0x12000000U;cfg.entrySymbol="entry";cfg.registers.push_back({3,5});ppclab::ppc::BuiltinInterpreter backend;auto result=ppclab::ppc::CallHarness::run(cfg,backend);assert(result.execution.reason==ppclab::ppc::StopReason::Returned);assert(result.cpu.gpr[3]==12U);assert(result.execution.instructions==3U);
    fs::remove_all(dir);return 0;}
