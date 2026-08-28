#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Deterministic PPC Lab hypothesis generation and review.

The tool turns guided-exploration evidence into bounded, inspectable hypotheses.
It is intentionally heuristic and evidence-first: every score is derived from
recorded cases, every proposed follow-up is an explicit exploration manifest,
and promotion requires replayable PPC Lab execution evidence.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "ppc-lab-hypothesis-report-v1"
EXPERIMENT_SCHEMA = "ppc-lab-hypothesis-experiment-v1"
PROMOTED_SCHEMA = "ppc-lab-hypothesis-v1"
CASE_SCHEMA = "ppc-lab-exploration-case-v1"
SUMMARY_SCHEMA = "ppc-lab-exploration-summary-v1"
MANIFEST_SCHEMA = "ppc-lab-exploration-v1"
SUPPORTED_EVIDENCE = {
    CASE_SCHEMA,
    "ppc-lab-result-v1",
    "ppc-lab-worker-response-v1",
    "ppc-lab-corpus-case-v1",
    "ppc-lab-corpus-replay-summary-v1",
    "ppc-lab-differential-triage-v1",
    "ppc-lab-triage-bundle-v1",
}


class HypothesisError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def parse_number(value: Any) -> float | None:
    try:
        if isinstance(value, bool):
            return float(int(value))
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
        if isinstance(value, str):
            return float(int(value, 0))
    except (ValueError, TypeError, OverflowError):
        return None
    return None


def result_from_case(row: dict[str, Any]) -> dict[str, Any]:
    worker = row.get("worker") if isinstance(row.get("worker"), dict) else {}
    result = worker.get("result") if isinstance(worker.get("result"), dict) else {}
    return result


def correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3 or len(xs) != len(ys):
        return 0.0
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    dx = [x - mx for x in xs]; dy = [y - my for y in ys]
    denom = math.sqrt(sum(x*x for x in dx) * sum(y*y for y in dy))
    if denom == 0:
        return 0.0
    return sum(a*b for a,b in zip(dx,dy)) / denom


def load_exploration(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = root.expanduser().resolve(strict=True)
    summary_path = root / "summary.json"
    cases_dir = root / "cases"
    if not summary_path.is_file() or not cases_dir.is_dir():
        raise HypothesisError(f"not a PPC Lab exploration directory: {root}")
    summary = read_json(summary_path)
    if not isinstance(summary, dict) or summary.get("schema") != SUMMARY_SCHEMA:
        raise HypothesisError("exploration summary schema mismatch")
    rows=[]
    for path in sorted(cases_dir.glob("*.json")):
        row=read_json(path)
        if not isinstance(row, dict) or row.get("schema") != CASE_SCHEMA:
            raise HypothesisError(f"case schema mismatch: {path}")
        row=copy.deepcopy(row); row["_source"] = str(path); row["_sha256"] = sha256_json({k:v for k,v in row.items() if not k.startswith("_")})
        rows.append(row)
    if len(rows) < 2:
        raise HypothesisError("hypothesis analysis requires at least two exploration cases")
    return summary, rows


def resolve_manifest(summary: dict[str, Any], explicit: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    candidate = explicit
    if candidate is None and isinstance(summary.get("manifest"), str):
        p=Path(summary["manifest"]).expanduser()
        if p.is_file(): candidate=p
    if candidate is None:
        return None, None
    candidate=candidate.expanduser().resolve(strict=True)
    doc=read_json(candidate)
    if not isinstance(doc, dict) or doc.get("schema") != MANIFEST_SCHEMA:
        raise HypothesisError(f"manifest schema must be {MANIFEST_SCHEMA}")
    return doc, str(candidate)


def axis_values(rows: list[dict[str, Any]]) -> dict[str, list[tuple[Any, dict[str, Any]]]]:
    out: dict[str,list[tuple[Any,dict[str,Any]]]]={}
    for row in rows:
        a=row.get("assignment") if isinstance(row.get("assignment"),dict) else {}
        for path,value in a.items(): out.setdefault(path,[]).append((value,row))
    return out


def classify(path: str, observations: list[tuple[Any,dict[str,Any]]]) -> tuple[str,str,dict[str,Any]]:
    vals=[]; nums=[]; behavior_by_value: dict[str,set[str]]={}; pcs_by_value: dict[str,set[str]]={}; instr_by_num=[]; failures=0
    for value,row in observations:
        key=json.dumps(value,sort_keys=True,separators=(",",":"))
        if key not in vals: vals.append(key)
        num=parse_number(value)
        if num is not None: nums.append(num)
        behavior_by_value.setdefault(key,set()).add(str(row.get("behavior_sha256")))
        trace=row.get("trace") if isinstance(row.get("trace"),dict) else {}
        pcs_by_value.setdefault(key,set()).update(str(x).lower() for x in trace.get("pcs",[]) if isinstance(x,str))
        worker=row.get("worker") if isinstance(row.get("worker"),dict) else {}
        failures += int(not bool(worker.get("ok")))
        result=result_from_case(row)
        ins=parse_number(result.get("instructions"))
        if num is not None and ins is not None: instr_by_num.append((num,ins))
    distinct=len(vals); all_numeric=len(nums)==len(observations); unique_num=sorted(set(nums)) if all_numeric else []
    behavior_partitions=len({tuple(sorted(v)) for v in behavior_by_value.values()})
    pc_partitions=len({tuple(sorted(v)) for v in pcs_by_value.values()})
    effect=max(behavior_partitions,pc_partitions)
    corr=correlation([x for x,_ in instr_by_num],[y for _,y in instr_by_num]) if len(instr_by_num)>=3 else 0.0
    root=path.split(".",1)[0]
    role="scalar-argument"; claim=f"{path} influences routine behavior as a scalar input"
    if root=="bindings": role="import-binding"; claim=f"{path} controls an external import/runtime dependency"
    elif root=="syscall_returns": role="environment-result"; claim=f"{path} models an environment/syscall result consumed by the routine"
    elif root=="writes_f32": role="floating-state-field"; claim=f"{path} is a floating-point state/coefficient field read by the routine"
    elif root=="float_registers": role="floating-argument"; claim=f"{path} is a floating-point call argument"
    elif root=="writes_u32": role="state-field"; claim=f"{path} is a 32-bit state field that affects execution"
    if all_numeric and set(unique_num).issubset({0.0,1.0}) and distinct>=2:
        role="boolean-flag" if root in {"registers","writes_u32"} else role
        claim=f"{path} behaves like a boolean enable/flag"
    elif all_numeric and distinct<=8 and effect>=2 and all(0 <= n <= 255 for n in unique_num):
        role="selector-enum" if root in {"registers","writes_u32"} else role
        claim=f"{path} behaves like a small selector/enumeration"
    elif all_numeric and abs(corr)>=0.75 and distinct>=3 and root in {"registers","writes_u32"}:
        role="count-or-length"; claim=f"{path} behaves like a count/length controlling execution work"
    elif all_numeric and distinct>=2 and root=="registers" and all(n>=0x10000 and int(n)%4==0 for n in unique_num):
        role="pointer-or-address"; claim=f"{path} behaves like an aligned pointer/address argument"
    metrics={"distinct_values":distinct,"behavior_partitions":behavior_partitions,"coverage_partitions":pc_partitions,
             "failures":failures,"instruction_correlation":round(corr,6),"numeric":all_numeric}
    return role,claim,metrics


def suggested_values(role: str, observations: list[tuple[Any,dict[str,Any]]]) -> list[Any]:
    raw=[]
    for v,_ in observations:
        if v not in raw: raw.append(v)
    nums=[parse_number(v) for v in raw]; numeric=all(x is not None for x in nums)
    if role=="boolean-flag": candidates=[0,1,2,0xFFFFFFFF]
    elif role=="selector-enum" and numeric:
        ints=sorted({int(x) for x in nums if x is not None}); candidates=ints + ([max(ints)+1] if ints else []) + ([min(ints)-1] if ints and min(ints)>0 else [])
    elif role=="count-or-length" and numeric:
        ints=sorted({max(0,int(x)) for x in nums if x is not None}); m=max(ints) if ints else 4; candidates=[0,1,2,max(3,m//2),m,m+1]
    elif role=="pointer-or-address" and numeric:
        ints=sorted({int(x) for x in nums if x is not None}); base=ints[0] if ints else 0x10000; candidates=[0,base,base+4,base+0x10]
    elif role in {"floating-argument","floating-state-field"}:
        candidates=[0.0,0.5,1.0,-1.0,2.0]
    else:
        candidates=raw[:]
        if numeric:
            ints=sorted({int(x) for x in nums if x is not None});
            if ints: candidates += [0,1,max(ints)+1]
    out=[]
    for v in candidates:
        if v not in out: out.append(v)
    return out[:8]


def confidence(metrics: dict[str,Any], observations: list[tuple[Any,dict[str,Any]]]) -> tuple[float,list[int],list[int]]:
    support=[]; contra=[]
    baseline_behavior=None
    for _,row in observations:
        if baseline_behavior is None: baseline_behavior=row.get("behavior_sha256")
        changed = row.get("behavior_sha256") != baseline_behavior or int((row.get("novelty") or {}).get("new_pc_count",0) or 0)>0
        (support if changed else contra).append(int(row.get("index",-1)))
    distinct=metrics["distinct_values"]
    effect=max(metrics["behavior_partitions"],metrics["coverage_partitions"])
    score=0.20 + min(0.30,0.08*distinct) + min(0.30,0.12*max(0,effect-1))
    if abs(float(metrics["instruction_correlation"]))>=0.75: score+=0.15
    if metrics["failures"] and metrics["failures"] < len(observations): score+=0.05
    if not support: score=min(score,0.25)
    return round(min(score,0.98),3),support,contra


def target_provenance(summary: dict[str,Any]) -> list[dict[str,Any]]:
    out=[]
    for item in summary.get("input_provenance",[]):
        if isinstance(item,dict) and isinstance(item.get("sha256"),str):
            out.append({k:item.get(k) for k in ("field","sha256","size") if item.get(k) is not None})
    return out


def analyze(exploration: Path, manifest_path: Path|None, top:int) -> dict[str,Any]:
    summary,rows=load_exploration(exploration)
    manifest,manifest_source=resolve_manifest(summary,manifest_path)
    axes=axis_values(rows); hypotheses=[]
    for path,obs in sorted(axes.items()):
        role,claim,metrics=classify(path,obs); conf,support,contra=confidence(metrics,obs)
        vals=suggested_values(role,obs)
        exp=None
        if manifest is not None:
            exp=copy.deepcopy(manifest); exp["strategy"]="cartesian"; exp["max_cases"]=min(16,max(4,len(vals)))
            exp["axes"]=[{"path":path,"values":vals}]
        hypotheses.append({"id":"", "subject":path,"role":role,"claim":claim,"confidence":conf,
            "metrics":metrics,"supporting_cases":sorted(set(support)),"contradicting_cases":sorted(set(contra)),
            "suggested_values":vals,"supporting_behaviors":sorted({str(r.get("behavior_sha256")) for _,r in obs if int(r.get("index",-1)) in support}),"experiment":exp})
    hypotheses.sort(key=lambda x:(-x["confidence"],-len(x["supporting_cases"]),x["subject"]))
    for i,h in enumerate(hypotheses,1): h["id"]=f"hyp-{i:03d}"
    if top>=0: hypotheses=hypotheses[:top]
    case_evidence=[{"index":int(r.get("index",-1)),"sha256":r["_sha256"],"source":r["_source"],"schema":CASE_SCHEMA} for r in rows]
    return {"schema":REPORT_SCHEMA,"exploration":str(exploration.expanduser().resolve()),"manifest":manifest_source,
        "input_provenance":target_provenance(summary),"cases":case_evidence,"hypotheses":hypotheses,
        "method":{"deterministic":True,"opaque_ai":False,"note":"Heuristic classification from recorded PPC Lab execution/coverage/behavior evidence."}}


def lookup(report:dict[str,Any],hid:str)->dict[str,Any]:
    for h in report.get("hypotheses",[]):
        if isinstance(h,dict) and h.get("id")==hid: return h
    raise HypothesisError(f"hypothesis not found: {hid}")


def verify_case_evidence(report:dict[str,Any], exploration:Path, h:dict[str,Any]) -> list[dict[str,Any]]:
    _,rows=load_exploration(exploration); by_index={int(r.get("index",-1)):r for r in rows}
    report_ev={int(x["index"]):x for x in report.get("cases",[]) if isinstance(x,dict) and "index" in x}
    verified=[]
    for idx in sorted(set(h.get("supporting_cases",[]))):
        row=by_index.get(int(idx)); expected=report_ev.get(int(idx))
        if not row or not expected: continue
        if row["_sha256"] != expected.get("sha256"): raise HypothesisError(f"case {idx} changed since hypothesis analysis")
        worker=row.get("worker") if isinstance(row.get("worker"),dict) else {}
        if worker.get("ok"):
            verified.append({"schema":CASE_SCHEMA,"index":idx,"sha256":row["_sha256"],"behavior_sha256":row.get("behavior_sha256")})
    return verified


def promote(report_path:Path,hid:str,exploration:Path,min_conf:float,min_support:int)->dict[str,Any]:
    report=read_json(report_path)
    if not isinstance(report,dict) or report.get("schema")!=REPORT_SCHEMA: raise HypothesisError("hypothesis report schema mismatch")
    h=lookup(report,hid); conf=float(h.get("confidence",0))
    verified=verify_case_evidence(report,exploration,h)
    if conf<min_conf: raise HypothesisError(f"confidence {conf:.3f} is below promotion threshold {min_conf:.3f}")
    if len(verified)<min_support: raise HypothesisError(f"only {len(verified)} verified supporting executions; need {min_support}")
    contradictions=len(h.get("contradicting_cases",[])); total=contradictions+len(h.get("supporting_cases",[]))
    if total and contradictions/total>0.75: raise HypothesisError("contradicting evidence dominates this hypothesis")
    return {"schema":PROMOTED_SCHEMA,"id":hid,"status":"supported","subject":h["subject"],"role":h["role"],"claim":h["claim"],
        "confidence":conf,"input_provenance":report.get("input_provenance",[]),"verified_support":verified,
        "contradicting_cases":h.get("contradicting_cases",[]),"metrics":h.get("metrics",{}),"suggested_experiment":h.get("experiment"),
        "source_report_sha256":sha256_json(report),"promotion_policy":{"minimum_confidence":min_conf,"minimum_verified_support":min_support}}


def main()->int:
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest="cmd",required=True)
    a=sub.add_parser("analyze",help="infer candidate roles from an exploration")
    a.add_argument("exploration",type=Path); a.add_argument("--manifest",type=Path); a.add_argument("--top",type=int,default=16); a.add_argument("--json",type=Path)
    e=sub.add_parser("experiments",help="write follow-up exploration manifests")
    e.add_argument("report",type=Path); e.add_argument("--out",type=Path,required=True); e.add_argument("--top",type=int,default=8)
    p=sub.add_parser("promote",help="promote a candidate only after verifying execution evidence")
    p.add_argument("report",type=Path); p.add_argument("hypothesis_id"); p.add_argument("--evidence",type=Path,required=True); p.add_argument("--json",type=Path,required=True)
    p.add_argument("--min-confidence",type=float,default=0.55); p.add_argument("--min-support",type=int,default=2)
    ns=ap.parse_args()
    try:
        if ns.cmd=="analyze":
            if ns.top<0: raise HypothesisError("--top must be >= 0")
            report=analyze(ns.exploration,ns.manifest,ns.top)
            if ns.json: write_json(ns.json.expanduser().resolve(),report)
            print(f"hypotheses={len(report['hypotheses'])}")
            for h in report["hypotheses"]: print(f"{h['id']} confidence={h['confidence']:.3f} role={h['role']} subject={h['subject']} claim={h['claim']}")
        elif ns.cmd=="experiments":
            report=read_json(ns.report.expanduser().resolve(strict=True))
            if not isinstance(report,dict) or report.get("schema")!=REPORT_SCHEMA: raise HypothesisError("hypothesis report schema mismatch")
            out=ns.out.expanduser().resolve(); out.mkdir(parents=True,exist_ok=True); made=0
            for h in report.get("hypotheses",[])[:max(0,ns.top)]:
                if not isinstance(h,dict) or not isinstance(h.get("experiment"),dict): continue
                doc={"schema":EXPERIMENT_SCHEMA,"hypothesis_id":h["id"],"claim":h["claim"],"confidence":h["confidence"],"exploration":h["experiment"]}
                write_json(out/f"{h['id']}.experiment.json",doc); write_json(out/f"{h['id']}.exploration.json",h["experiment"]); made+=1
            print(f"experiments={made} out={out}")
        else:
            if not 0<=ns.min_confidence<=1 or ns.min_support<1: raise HypothesisError("invalid promotion thresholds")
            doc=promote(ns.report.expanduser().resolve(strict=True),ns.hypothesis_id,ns.evidence,ns.min_confidence,ns.min_support)
            write_json(ns.json.expanduser().resolve(),doc); print(f"promoted={doc['id']} status={doc['status']} confidence={doc['confidence']:.3f}")
        return 0
    except (HypothesisError,OSError,json.JSONDecodeError,ValueError) as exc:
        print(f"ppc-lab-hypothesize: {exc}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
