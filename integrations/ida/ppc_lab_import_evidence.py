# SPDX-License-Identifier: GPL-3.0-only
"""IDAPython helper: call import_ppc_lab_evidence(path)."""
import json, ida_bytes, ida_name
def import_ppc_lab_evidence(path):
    obj=json.load(open(path,"r"))
    if obj.get("schema")!="ppc-lab-evidence-v1": raise ValueError("Unsupported PPC Lab evidence schema")
    for s in obj.get("symbols",[]):
        if s.get("defined") and s.get("name"): ida_name.set_name(int(s["address"],0),s["name"],ida_name.SN_NOWARN)
    for a in obj.get("annotations",[]):
        ea=int(a["address"],0); old=ida_bytes.get_cmt(ea,False) or ""; text=a.get("comment","")
        ida_bytes.set_cmt(ea,(old+"\n" if old else "")+text,False)
    return len(obj.get("symbols",[])),len(obj.get("annotations",[]))
