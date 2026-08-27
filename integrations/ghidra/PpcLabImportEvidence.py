# SPDX-License-Identifier: GPL-3.0-only
# @category PPC Lab
# Import ppc-lab-evidence-v1 symbols and behavioral comments into the current program.
import json
f=askFile("PPC Lab evidence JSON","Open")
obj=json.load(open(f.getAbsolutePath(),"r"))
if obj.get("schema")!="ppc-lab-evidence-v1": raise Exception("Unsupported PPC Lab evidence schema")
for s in obj.get("symbols",[]):
    if not s.get("defined") or not s.get("name"): continue
    try: createLabel(toAddr(int(s["address"],0)),s["name"],True)
    except Exception: pass
for a in obj.get("annotations",[]):
    addr=toAddr(int(a["address"],0)); old=getEOLComment(addr); text=a.get("comment","")
    setEOLComment(addr,(old+"\n" if old else "")+text)
print("PPC Lab evidence imported")
