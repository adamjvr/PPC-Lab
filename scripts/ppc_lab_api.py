#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""PPC Lab dependency-free HTTP research API.

The API is deliberately a thin transport around the stable worker/evidence
contracts. It does not duplicate the PPC execution engine or invent a second
job schema. Default binding is loopback only. Non-loopback binding requires a
bearer token unless --allow-unauthenticated-remote is explicitly supplied.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

try:
    from ppc_lab_security import verify_token as _verify_scoped_token, audit_append as _audit_append
except ImportError:
    _verify_scoped_token = None
    _audit_append = None

API_PROTOCOL = "ppc-lab-http-api-v1"
HEALTH_SCHEMA = "ppc-lab-api-health-v1"
DISCOVERY_SCHEMA = "ppc-lab-api-discovery-v1"
MAX_BODY_DEFAULT = 1024 * 1024


def _find_command(explicit: str | None, env_name: str, installed: str, source_name: str) -> str:
    candidate = explicit or os.environ.get(env_name) or shutil.which(installed)
    if candidate:
        return str(Path(candidate).expanduser().resolve()) if os.sep in candidate else candidate
    source = (Path(__file__).resolve().parent / source_name).resolve()
    if source.is_file():
        return str(source)
    raise SystemExit(f"ppc-lab-api: cannot find {installed}; use the matching command-line option or {env_name}")


def _loopback(host: str) -> bool:
    return host in {"127.0.0.1", "::1", "localhost"}


def _json_loads(data: bytes) -> Any:
    return json.loads(data.decode("utf-8"))


def _run_json(command: list[str], *, stdin: str | None = None, timeout: float = 30.0) -> tuple[int, Any, str]:
    proc = subprocess.run(command, input=stdin, text=True, capture_output=True, timeout=timeout, check=False)
    try:
        value = json.loads(proc.stdout)
    except Exception as exc:
        raise RuntimeError(f"command returned invalid JSON ({exc}): {proc.stderr.strip() or proc.stdout.strip()}") from exc
    return proc.returncode, value, proc.stderr


class ServerState:
    def __init__(self, *, ppc_lab: str, worker: str, evidence: str | None, root: Path | None,
                 evidence_store: Path | None, token: str | None, auth_store: Path | None,
                 audit_log: Path | None, job_timeout: float, max_body: int, expose_command: bool) -> None:
        self.ppc_lab = ppc_lab
        self.worker = worker
        self.evidence = evidence
        self.root = root
        self.evidence_store = evidence_store
        self.token = token
        self.auth_store = auth_store
        self.audit_log = audit_log
        self.audit_lock = threading.Lock()
        self.job_timeout = job_timeout
        self.max_body = max_body
        self.expose_command = expose_command
        self.capabilities = self._load_capabilities()

    def audit(self, event: dict[str, Any]) -> None:
        if self.audit_log is None or _audit_append is None:
            return
        with self.audit_lock:
            _audit_append(self.audit_log, event)

    def _load_capabilities(self) -> dict[str, Any]:
        _, value, _ = _run_json([self.ppc_lab, "capabilities", "--json"], timeout=10.0)
        if not isinstance(value, dict) or value.get("schema") != "ppc-lab-capabilities-v1":
            raise SystemExit("ppc-lab-api: ppc-lab returned an unsupported capabilities document")
        return value


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], state: ServerState):
        super().__init__(address, handler)
        self.state = state


class Handler(BaseHTTPRequestHandler):
    server: ApiServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("ppc-lab-api: " + (fmt % args) + "\n")

    def _send(self, status: int, value: Any) -> None:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, status: int, message: str) -> None:
        self._send(status, {"schema": API_PROTOCOL, "ok": False, "error": message})

    def _principal(self, required_scope: str) -> dict[str, Any] | None:
        st = self.server.state
        supplied = self.headers.get("Authorization", "")
        prefix = "Bearer "
        raw = supplied[len(prefix):] if supplied.startswith(prefix) else None
        principal: dict[str, Any] | None = None
        if st.auth_store is not None:
            if raw and _verify_scoped_token is not None:
                result = _verify_scoped_token(st.auth_store, raw, required_scope)
                if result.get("ok"):
                    principal = result
        elif st.token is not None:
            if raw is not None and hmac.compare_digest(raw, st.token):
                principal = {"ok": True, "token_id": "legacy", "label": "legacy-token", "role": "admin", "scopes": ["*"]}
        else:
            principal = {"ok": True, "token_id": "anonymous-local", "label": "anonymous-local", "role": "local", "scopes": ["*"]}
        st.audit({
            "event": "api.authorization", "method": self.command, "path": urlparse(self.path).path,
            "required_scope": required_scope, "allowed": principal is not None,
            "token_id": principal.get("token_id") if principal else None,
            "client": self.client_address[0] if self.client_address else None,
        })
        return principal

    def _require_scope(self, scope: str) -> bool:
        if self._principal(scope) is not None:
            return True
        self.send_response(HTTPStatus.FORBIDDEN if self.headers.get("Authorization") else HTTPStatus.UNAUTHORIZED)
        body = b'{"schema":"ppc-lab-http-api-v1","ok":false,"error":"unauthorized"}\n'
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("WWW-Authenticate", 'Bearer realm="PPC Lab"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return False

    def _body(self) -> Any:
        length_text = self.headers.get("Content-Length")
        if length_text is None:
            raise ValueError("Content-Length is required")
        try:
            length = int(length_text)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length < 0 or length > self.server.state.max_body:
            raise OverflowError("request body exceeds configured limit")
        data = self.rfile.read(length)
        try:
            return _json_loads(data)
        except Exception as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        scope = "evidence:read" if path.startswith("/v1/evidence/") else "status:read"
        if not self._require_scope(scope):
            return
        try:
            if path in {"/", "/v1"}:
                st = self.server.state
                self._send(200, {
                    "schema": DISCOVERY_SCHEMA,
                    "protocol": API_PROTOCOL,
                    "version": st.capabilities.get("version"),
                    "security": {"scoped_tokens": st.auth_store is not None, "audit_log": st.audit_log is not None},
                    "endpoints": ["GET /v1/health", "GET /v1/capabilities", "POST /v1/run"] +
                                 (["GET /v1/evidence/report", "POST /v1/evidence/query", "GET /v1/evidence/artifacts/{ref}"] if st.evidence_store else []),
                })
                return
            if path == "/v1/health":
                self._send(200, {"schema": HEALTH_SCHEMA, "ok": True, "version": self.server.state.capabilities.get("version")})
                return
            if path == "/v1/capabilities":
                caps = dict(self.server.state.capabilities)
                protocols = dict(caps.get("protocols", {}))
                protocols["http_api"] = API_PROTOCOL
                caps["protocols"] = protocols
                api_info = dict(caps.get("api", {}))
                api_info.update({"evidence": self.server.state.evidence_store is not None, "scoped_auth": self.server.state.auth_store is not None})
                caps["api"] = api_info
                self._send(200, caps)
                return
            if path == "/v1/evidence/report":
                self._evidence_report()
                return
            prefix = "/v1/evidence/artifacts/"
            if path.startswith(prefix) and len(path) > len(prefix):
                self._evidence_show(unquote(path[len(prefix):]))
                return
            self._error(404, "not found")
        except subprocess.TimeoutExpired:
            self._error(504, "backend command timed out")
        except Exception as exc:
            self._error(500, str(exc))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        scope = "execute:run" if path == "/v1/run" else "evidence:read" if path.startswith("/v1/evidence/") else "status:read"
        if not self._require_scope(scope):
            return
        try:
            body = self._body()
        except OverflowError as exc:
            self._error(413, str(exc)); return
        except ValueError as exc:
            self._error(400, str(exc)); return
        try:
            if path == "/v1/run":
                self._run_job(body); return
            if path == "/v1/evidence/query":
                self._evidence_query(body); return
            self._error(404, "not found")
        except subprocess.TimeoutExpired:
            self._error(504, "backend command timed out")
        except Exception as exc:
            self._error(500, str(exc))

    def _run_job(self, body: Any) -> None:
        st = self.server.state
        command = [sys.executable, st.worker] if st.worker.endswith(".py") else [st.worker]
        command += ["--ppc-lab", st.ppc_lab]
        if st.root is not None:
            command += ["--root", str(st.root), "--base-dir", str(st.root)]
        command += ["--timeout", str(st.job_timeout)]
        if st.expose_command:
            command.append("--expose-command")
        command += ["run", "-"]
        code, value, _ = _run_json(command, stdin=json.dumps(body), timeout=st.job_timeout + 5.0)
        # A valid worker response is an HTTP-successful protocol exchange even when
        # guest execution itself stopped/fails. Clients inspect response.ok/exit_code.
        if isinstance(value, dict) and value.get("schema") == "ppc-lab-worker-response-v1":
            self._send(200, value)
        else:
            self._error(502, f"worker protocol failure (exit {code})")

    def _evidence_base(self) -> tuple[str, Path]:
        st = self.server.state
        if st.evidence_store is None or st.evidence is None:
            raise FileNotFoundError("evidence API is not configured")
        return st.evidence, st.evidence_store

    def _evidence_report(self) -> None:
        try:
            evidence, store = self._evidence_base()
        except FileNotFoundError as exc:
            self._error(404, str(exc)); return
        command = ([sys.executable, evidence] if evidence.endswith(".py") else [evidence]) + ["report", str(store), "--json"]
        _, value, _ = _run_json(command)
        self._send(200, value)

    def _evidence_show(self, ref: str) -> None:
        try:
            evidence, store = self._evidence_base()
        except FileNotFoundError as exc:
            self._error(404, str(exc)); return
        if not ref or any(ch not in "0123456789abcdefABCDEF" for ch in ref):
            self._error(400, "artifact ref must be an integer id or SHA-256 prefix")
            return
        command = ([sys.executable, evidence] if evidence.endswith(".py") else [evidence]) + ["show", str(store), ref]
        code, value, _ = _run_json(command)
        self._send(200 if code == 0 else 404, value)

    def _evidence_query(self, body: Any) -> None:
        try:
            evidence, store = self._evidence_base()
        except FileNotFoundError as exc:
            self._error(404, str(exc)); return
        if not isinstance(body, dict):
            self._error(400, "query must be a JSON object"); return
        allowed = {
            "schema": "--schema", "engine_version": "--engine-version", "backend": "--backend",
            "stop_reason": "--stop-reason", "host": "--host", "name": "--name",
            "cache_key": "--cache-key", "input_sha256": "--input-sha256",
        }
        command = ([sys.executable, evidence] if evidence.endswith(".py") else [evidence]) + ["query", str(store)]
        for key, flag in allowed.items():
            value = body.get(key)
            if value is not None:
                if not isinstance(value, str):
                    self._error(400, f"{key} must be a string"); return
                command += [flag, value]
        if "ok" in body:
            ok = body["ok"]
            if not isinstance(ok, bool):
                self._error(400, "ok must be boolean"); return
            command += ["--ok", "yes" if ok else "no"]
        if "limit" in body:
            limit = body["limit"]
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
                self._error(400, "limit must be an integer from 1 to 1000"); return
            command += ["--limit", str(limit)]
        if body.get("oldest") is True:
            command.append("--oldest")
        elif "oldest" in body and body.get("oldest") is not False:
            self._error(400, "oldest must be boolean"); return
        command.append("--json")
        _, value, _ = _run_json(command)
        self._send(200, value)


def main() -> int:
    parser = argparse.ArgumentParser(description="PPC Lab dependency-free HTTP research API")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="TCP port; 0 chooses an ephemeral port (default: 8765)")
    parser.add_argument("--ppc-lab", help="path to ppc-lab")
    parser.add_argument("--worker", help="path to ppc-lab-worker")
    parser.add_argument("--evidence", help="path to ppc-lab-evidence")
    parser.add_argument("--root", help="restrict executable job input files to this directory")
    parser.add_argument("--evidence-store", help="enable read-only evidence endpoints for this existing store")
    parser.add_argument("--token", help="legacy full-access bearer token (or use PPC_LAB_API_TOKEN)")
    parser.add_argument("--auth-store", help="scoped token store created by ppc-lab-security")
    parser.add_argument("--audit-log", help="tamper-evident JSONL API audit log (defaults beside --auth-store)")
    parser.add_argument("--allow-unauthenticated-remote", action="store_true", help="DANGEROUS: permit non-loopback bind without a token")
    parser.add_argument("--job-timeout", type=float, default=60.0, help="worker timeout per request (default: 60)")
    parser.add_argument("--max-body", type=int, default=MAX_BODY_DEFAULT, help="maximum JSON request bytes (default: 1 MiB)")
    parser.add_argument("--expose-command", action="store_true", help="include worker command argv in run responses")
    parser.add_argument("--write-ready", help="atomically write bound URL/protocol JSON after listen succeeds")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be 0..65535")
    if args.job_timeout <= 0:
        parser.error("--job-timeout must be > 0")
    if args.max_body <= 0:
        parser.error("--max-body must be > 0")
    token = args.token or os.environ.get("PPC_LAB_API_TOKEN")
    auth_store = Path(args.auth_store).expanduser().resolve() if args.auth_store else None
    if auth_store is not None:
        if _verify_scoped_token is None or not auth_store.is_file():
            parser.error("--auth-store must be an existing PPC Lab auth store")
        # Validate schema without exposing token material.
        probe = _verify_scoped_token(auth_store, "invalid.invalid", "status:read")
        if probe.get("reason") == "auth-store-error": parser.error("--auth-store is invalid")
    audit_log = Path(args.audit_log).expanduser().resolve() if args.audit_log else (auth_store.parent / "audit.jsonl" if auth_store else None)
    if auth_store is not None and token is not None:
        parser.error("use either --auth-store or --token, not both")
    if not _loopback(args.host) and token is None and auth_store is None and not args.allow_unauthenticated_remote:
        parser.error("non-loopback binding requires --auth-store or --token/PPC_LAB_API_TOKEN (or explicit --allow-unauthenticated-remote)")

    ppc_lab = _find_command(args.ppc_lab, "PPC_LAB_BIN", "ppc-lab", "../build/release/ppc-lab")
    worker = _find_command(args.worker, "PPC_LAB_WORKER", "ppc-lab-worker", "ppc_lab_worker.py")
    evidence = None
    evidence_store = None
    if args.evidence_store:
        evidence = _find_command(args.evidence, "PPC_LAB_EVIDENCE", "ppc-lab-evidence", "ppc_lab_evidence.py")
        evidence_store = Path(args.evidence_store).expanduser().resolve()
        if not (evidence_store / "evidence.sqlite3").is_file():
            parser.error("--evidence-store is not an initialized PPC Lab evidence store")
    root = Path(args.root).expanduser().resolve() if args.root else None
    if root is not None and not root.is_dir():
        parser.error("--root must be an existing directory")

    state = ServerState(ppc_lab=ppc_lab, worker=worker, evidence=evidence, root=root,
                        evidence_store=evidence_store, token=token, auth_store=auth_store, audit_log=audit_log,
                        job_timeout=args.job_timeout, max_body=args.max_body, expose_command=args.expose_command)
    server = ApiServer((args.host, args.port), Handler, state)
    host, port = server.server_address[:2]
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    ready = {"schema": "ppc-lab-api-ready-v1", "protocol": API_PROTOCOL, "host": host, "port": port,
             "url": f"http://{display_host}:{port}", "version": state.capabilities.get("version")}
    if args.write_ready:
        path = Path(args.write_ready).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
            json.dump(ready, tmp, sort_keys=True); tmp.write("\n"); temp_name = tmp.name
        os.replace(temp_name, path)
    print(json.dumps(ready, sort_keys=True), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
