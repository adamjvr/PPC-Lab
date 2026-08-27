# SPDX-License-Identifier: GPL-3.0-only
"""Binary Ninja helper: call import_ppc_lab_evidence(bv, path)."""
import json
from binaryninja import Symbol, SymbolType
def import_ppc_lab_evidence(bv,path):
    obj=json.load(open(path,"r"))
    if obj.get("schema")!="ppc-lab-evidence-v1": raise ValueError("Unsupported PPC Lab evidence schema")
    for s in obj.get("symbols",[]):
        if s.get("defined") and s.get("name"):
            try: bv.define_user_symbol(Symbol(SymbolType.FunctionSymbol,int(s["address"],0),s["name"]))
            except Exception: pass
    for a in obj.get("annotations",[]):
        ea=int(a["address"],0); old=bv.get_comment_at(ea) or ""; text=a.get("comment","")
        bv.set_comment_at(ea,(old+"\n" if old else "")+text)
    return len(obj.get("symbols",[])),len(obj.get("annotations",[]))
