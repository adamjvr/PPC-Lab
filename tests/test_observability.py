#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
MOD_PATH = ROOT / "scripts" / "ppc_lab_observe.py"
spec = importlib.util.spec_from_file_location("ppc_lab_observe", MOD_PATH)
assert spec and spec.loader
obs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(obs)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ppclab-observe-") as td:
        base = pathlib.Path(td)
        control = base / "control"; control.mkdir()
        state = control / "fake.json"
        fake = base / "ppc-lab-control"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json,pathlib,sys\n"
            f"state=pathlib.Path({str(state)!r})\n"
            "doc=json.loads(state.read_text())\n"
            "cmd=sys.argv[1]\n"
            "if cmd=='status': print(json.dumps(doc['status']))\n"
            "elif cmd=='history': print(json.dumps({'schema':'ppc-lab-control-history-v1','records':doc['records']}))\n"
            "else: raise SystemExit(2)\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        store = obs.ensure_store(base / "observability", create=True)

        def records(complete: int, failed: int):
            rows=[]
            for i in range(complete):
                rows.append({'id':f'c{i}','status':'complete','started_unix':100+i*10,'finished_unix':700+i*10})
            for i in range(failed):
                rows.append({'id':f'f{i}','status':'failed','started_unix':200+i*10,'finished_unix':800+i*10})
            return rows

        fixtures = [
            (1000.0, 8, 2, {'queued':8,'running':2,'complete':10}, records(10,0)),
            (4600.0, 5, 2, {'queued':5,'running':2,'complete':14,'failed':1}, records(14,1)),
            (8200.0, 2, 1, {'queued':2,'running':1,'complete':18,'failed':2}, records(18,2)),
        ]
        for ts, queue, active, counts, rows in fixtures:
            state.write_text(json.dumps({'status':{
                'schema':'ppc-lab-control-telemetry-v1','queue_depth':queue,'history_count':len(rows),
                'active':[{'id':f'a{i}'} for i in range(active)],'counts':counts,
                'paused':False,'draining':False,'global_cancel':False},'records':rows}), encoding='utf-8')
            doc = obs.collect(control, fake, slots=2, disk_paths=[base])
            doc['unix']=ts; doc['utc']=obs.utc_iso(ts)
            obs.save_sample(store, doc)

        samples=obs.load_samples(store,since_hours=None)
        assert len(samples)==3
        report=obs.build_report(samples)
        assert report['schema']=='ppc-lab-observability-report-v1'
        assert report['queue']['latest']==2 and report['queue']['max']==8
        assert abs(report['throughput']['completed_per_hour']-4.0) < 1e-9
        assert abs(report['throughput']['failure_rate']-0.2) < 1e-9
        assert abs(report['service_time_seconds']['p50']-600.0) < 1e-9
        assert abs(report['capacity']['estimated_backlog_clear_hours']-0.5) < 1e-9

        health=obs.health_check(report,obs.DEFAULT_POLICY)
        assert health['status']=='warning' and health['ok'] is True
        cap=obs.capacity_report(report,1.0)
        assert cap['recommended_slots_for_current_backlog']==1

        strict=dict(obs.DEFAULT_POLICY); strict['failure_rate_critical']=0.15
        checked=obs.health_check(report,strict)
        assert checked['status']=='critical' and checked['ok'] is False

        cli=subprocess.run([sys.executable,str(MOD_PATH),'report',str(store),'--json'],text=True,capture_output=True,timeout=10)
        assert cli.returncode==0,cli.stderr
        assert json.loads(cli.stdout)['schema']=='ppc-lab-observability-report-v1'
        cli=subprocess.run([sys.executable,str(MOD_PATH),'capacity',str(store),'--target-clear-hours','1','--json'],text=True,capture_output=True,timeout=10)
        assert cli.returncode==0 and json.loads(cli.stdout)['recommended_slots_for_current_backlog']==1

        # Store contract is JSON-only; no target/binary payload is ever produced.
        files=[p.relative_to(store).as_posix() for p in store.rglob('*') if p.is_file()]
        assert files and all(p.endswith('.json') for p in files), files

    print('PASS: observability sampling, health thresholds, trends, and capacity planning')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
