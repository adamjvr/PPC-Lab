#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Shared trace-analysis primitives for PPC Lab."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from typing import Any

def parse_u32(value: Any) -> int:
    if isinstance(value, int): return value & 0xFFFFFFFF
    return int(str(value), 0) & 0xFFFFFFFF

def hex32(value: int) -> str: return f"0x{value & 0xFFFFFFFF:08x}"
def mnemonic(disassembly: str) -> str:
    text=(disassembly or "").strip(); return text.split(None,1)[0].lower() if text else ""
def symbol_root(symbol: str) -> str:
    symbol=(symbol or "").strip(); return symbol.split("+0x",1)[0] if symbol else "<unknown>"
def is_control_transfer(mn: str) -> bool:
    return bool(mn) and (mn.startswith("b") or mn in {"sc","rfi","rfid","tw","twi"})
def is_call(mn: str) -> bool:
    return bool(mn) and (mn in {"bl","bla","bctrl","blrl","bcl","bcla","bcctrl","bcctrl."} or (mn.startswith("b") and mn.endswith("l") and mn != "blr"))
def is_return(mn: str) -> bool: return mn in {"blr","blrl"}

@dataclass(frozen=True)
class NormalEvent:
    index:int; pc:int; instruction:str; disassembly:str; symbol:str
    @property
    def mnemonic(self)->str:return mnemonic(self.disassembly)
    @property
    def function(self)->str:return symbol_root(self.symbol)

def normalize_events(trace:dict[str,Any])->list[NormalEvent]:
    out=[]
    for index,raw in enumerate(trace.get("events",[])):
        if not isinstance(raw,dict) or raw.get("pc") is None: continue
        try: pc=parse_u32(raw["pc"])
        except (TypeError,ValueError): continue
        out.append(NormalEvent(index,pc,str(raw.get("instruction","")).lower(),str(raw.get("disassembly","")).strip(),str(raw.get("symbol","")).strip()))
    return out

def _block_key(events:list[NormalEvent])->tuple[int,int,tuple[int,...]]:return events[0].pc,events[-1].pc,tuple(e.pc for e in events)
def split_dynamic_blocks(events:list[NormalEvent])->list[list[NormalEvent]]:
    if not events:return []
    blocks=[]; current=[]
    for i,event in enumerate(events):
        current.append(event); nxt=events[i+1] if i+1<len(events) else None
        if is_control_transfer(event.mnemonic) or nxt is None or nxt.pc != ((event.pc+4)&0xffffffff):
            blocks.append(current); current=[]
    if current:blocks.append(current)
    return blocks

def analyze_trace(trace:dict[str,Any])->dict[str,Any]:
    events=normalize_events(trace); pc_counts=Counter(e.pc for e in events); instr_counts=Counter(e.instruction for e in events if e.instruction); mnemonic_counts=Counter(e.mnemonic for e in events if e.mnemonic); function_counts=Counter(e.function for e in events)
    first={}
    for e in events:first.setdefault(e.pc,e)
    dyn=split_dynamic_blocks(events); bcounts=Counter(_block_key(b) for b in dyn); bfirst={}
    for b in dyn:bfirst.setdefault(_block_key(b),b)
    bid={}; blocks=[]
    for idx,(key,count) in enumerate(sorted(bcounts.items(),key=lambda x:(-x[1],x[0][0],x[0][1]))):
        b=bfirst[key]; name=f"b{idx:04d}"; bid[key]=name
        blocks.append({"id":name,"start":hex32(b[0].pc),"end":hex32(b[-1].pc),"instruction_count":len(b),"executions":count,"symbol":b[0].symbol,"function":b[0].function,"terminator":b[-1].mnemonic,"pcs":[hex32(e.pc) for e in b]})
    ecounts=Counter(); cc=Counter()
    for left,right in zip(dyn,dyn[1:]):
        lk,rk=_block_key(left),_block_key(right); term=left[-1]
        if is_call(term.mnemonic):kind="call"
        elif is_return(term.mnemonic):kind="return"
        elif is_control_transfer(term.mnemonic) or right[0].pc != ((term.pc+4)&0xffffffff):kind="branch"
        else:kind="fallthrough"
        ecounts[(lk,rk,kind)]+=1
        if kind=="call":cc[(term.function,right[0].function,term.pc,right[0].pc)]+=1
    edges=[{"source":bid[s],"target":bid[d],"kind":k,"count":c} for (s,d,k),c in sorted(ecounts.items(),key=lambda x:(-x[1],x[0][0][0],x[0][1][0],x[0][2]))]
    calls=[{"caller":a,"callee":b,"site":hex32(site),"target":hex32(target),"count":c} for (a,b,site,target),c in sorted(cc.items(),key=lambda x:(-x[1],x[0]))]
    pcs=sorted(pc_counts)
    if pcs:lo,hi=pcs[0],pcs[-1]; span=(hi-lo)+4; covered=len(pcs)*4; density=covered/span
    else:lo=hi=span=covered=0; density=0.0
    hot=[]
    for pc,count in pc_counts.most_common():
        e=first[pc]; hot.append({"pc":hex32(pc),"count":count,"instruction":e.instruction,"disassembly":e.disassembly,"symbol":e.symbol,"function":e.function})
    return {"schema":"ppc-lab-trace-analysis-v1","source_trace_schema":trace.get("schema"),"source_exit_code":trace.get("exit_code"),"summary":{"events":len(events),"unique_pcs":len(pcs),"unique_instruction_words":len(instr_counts),"unique_mnemonics":len(mnemonic_counts),"dynamic_blocks":len(dyn),"unique_blocks":len(blocks),"unique_edges":len(edges),"call_edges":sum(x["count"] for x in calls),"address_min":hex32(lo) if pcs else None,"address_max":hex32(hi) if pcs else None,"address_span_bytes":span,"covered_bytes":covered,"coverage_density":density},"hot_pcs":hot,"functions":[{"name":n,"instructions_executed":c} for n,c in function_counts.most_common()],"mnemonics":[{"name":n,"count":c} for n,c in mnemonic_counts.most_common()],"blocks":blocks,"edges":edges,"calls":calls}
def analysis_pc_counts(a):return {str(x.get("pc")):int(x.get("count",0)) for x in a.get("hot_pcs",[])}
def analysis_function_counts(a):return {str(x.get("name")):int(x.get("instructions_executed",0)) for x in a.get("functions",[])}
def analysis_call_counts(a):return {(str(x.get("caller")),str(x.get("callee")),str(x.get("site")),str(x.get("target"))):int(x.get("count",0)) for x in a.get("calls",[])}
