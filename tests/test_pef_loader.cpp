// SPDX-License-Identifier: GPL-3.0-only

#include "ppclab/ppc/BuiltinInterpreter.hpp"
#include "ppclab/ppc/CallHarness.hpp"
#include "ppclab/ppc/PefLoader.hpp"

#include <cassert>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <vector>

namespace {void p16(std::vector<std::uint8_t>&b,std::size_t o,std::uint16_t v){b[o]=v>>8;b[o+1]=v;}void p32(std::vector<std::uint8_t>&b,std::size_t o,std::uint32_t v){b[o]=v>>24;b[o+1]=v>>16;b[o+2]=v>>8;b[o+3]=v;}
std::filesystem::path makePef(const std::filesystem::path&d){constexpr std::size_t code=0x80,data=0x88,loader=0x8c;constexpr std::size_t loaderSize=70;std::vector<std::uint8_t>b(loader+loaderSize,0);p32(b,0,0x4a6f7921);p32(b,4,0x70656666);p32(b,8,0x70777063);p32(b,12,1);p16(b,32,3);p16(b,34,2);
auto sec=[&](int i,std::uint32_t total,std::uint32_t unpack,std::uint32_t clen,std::uint32_t coff,std::uint8_t kind,std::uint8_t align){std::size_t o=40+i*28;p32(b,o+8,total);p32(b,o+12,unpack);p32(b,o+16,clen);p32(b,o+20,coff);b[o+24]=kind;b[o+26]=align;};sec(0,8,8,8,code,0,2);sec(1,4,4,4,data,1,2);sec(2,0,0,loaderSize,loader,4,0);p32(b,code,0x38630007);p32(b,code+4,0x4e800020);p32(b,data,0);
// loader header: main section 0, one relocation section, relocation area at 68
p32(b,loader+0,0);p32(b,loader+4,0);p32(b,loader+8,0xffffffffU);p32(b,loader+16,0xffffffffU);p32(b,loader+32,1);p32(b,loader+36,68);p32(b,loader+40,70);p32(b,loader+44,70);p32(b,loader+48,0);p32(b,loader+52,0);
// relocation header targets data section #1; one chunk
p16(b,loader+56,1);p32(b,loader+60,1);p32(b,loader+64,0);p16(b,loader+68,0x6600); // RelocSmBySection section 0
const auto path=d/"fixture.pef";std::ofstream f(path,std::ios::binary);f.write(reinterpret_cast<const char*>(b.data()),b.size());return path;}
}
int main(){namespace fs=std::filesystem;auto d=fs::temp_directory_path()/"ppc_lab_pef";fs::remove_all(d);fs::create_directories(d);auto path=makePef(d);ppclab::ppc::PefImageInfo info{};std::string e;assert(ppclab::ppc::PefLoader::inspectFile(path.string(),info,e));assert(info.sectionCount==3);assert(info.relocationChunkCount==1);ppclab::ppc::Memory m;assert(ppclab::ppc::PefLoader::loadFile(path.string(),m,info,e,0x11000000U));assert(info.entry==0x11000000U);std::uint32_t relocated=0;assert(m.read32(0x11000008U,relocated));assert(relocated==0x11000000U);ppclab::ppc::CallConfig c{};c.image.pefPath=path.string();c.image.imageBase=0x11000000U;c.registers.push_back({3,5});ppclab::ppc::BuiltinInterpreter be;auto r=ppclab::ppc::CallHarness::run(c,be);assert(r.execution.reason==ppclab::ppc::StopReason::Returned);assert(r.cpu.gpr[3]==12);fs::remove_all(d);return 0;}
