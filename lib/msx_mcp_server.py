#!/usr/bin/env python3
"""Minimal MCP stdio server for MSX media triage (multi-LLM)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("MSX_AGENTS_ROOT", Path(__file__).resolve().parent.parent))
SKILL = ROOT / "skill" / "analyze-msx-media"
TRIAGE = SKILL / "scripts" / "msx_triage.py"
SERVER_NAME = "msx-agents"
SERVER_VERSION = "1.0.0"


def _read_message() -> dict[str, Any] | None:
    """Read one LSP/MCP-style Content-Length framed JSON message from stdin."""
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        if b":" in line:
            k, v = line.decode("utf-8", errors="replace").split(":", 1)
            headers[k.strip().lower()] = v.strip()
    n = int(headers.get("content-length", "0"))
    if n <= 0:
        return None
    body = sys.stdin.buffer.read(n)
    return json.loads(body.decode("utf-8"))


def _write_message(msg: dict[str, Any]) -> None:
    data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _result(req_id: Any, result: Any) -> None:
    _write_message({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id: Any, code: int, message: str) -> None:
    _write_message(
        {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
    )


TOOLS = [
    {
        "name": "msx_doctor",
        "description": "Check msx-agents skill install, MCP, and analysis tools (z80dasm/openmsx).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "msx_triage",
        "description": (
            "Triage an MSX ROM/DISK/CAS file: AB header, mapper heuristic, FAT12 listing, "
            "optional z80dasm. Returns Evidence JSON and report markdown."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to .rom/.bin/.dsk/.dmk/.cas",
                },
                "out_dir": {
                    "type": "string",
                    "description": "Output directory for evidence.json/report.md (optional)",
                },
                "no_disasm": {
                    "type": "boolean",
                    "description": "Skip z80dasm (default false)",
                    "default": False,
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "msx_read_evidence",
        "description": "Read evidence.json previously written by msx_triage from an output directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "out_dir": {"type": "string", "description": "Triage output directory"},
            },
            "required": ["out_dir"],
            "additionalProperties": False,
        },
    },
]


def tool_doctor() -> dict[str, Any]:
    import shutil

    return {
        "root": str(ROOT),
        "skill": str(SKILL),
        "triage_script": str(TRIAGE),
        "triage_present": TRIAGE.is_file(),
        "tools": {
            "z80dasm": bool(shutil.which("z80dasm")),
            "openmsx": bool(shutil.which("openmsx")),
            "msxforge": bool(shutil.which("msxforge")),
            "java": bool(shutil.which("java")),
        },
    }


def tool_triage(path: str, out_dir: str | None, no_disasm: bool) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return {"ok": False, "error": f"not a file: {p}"}
    if out_dir:
        out = Path(out_dir).expanduser().resolve()
    else:
        out = Path(tempfile.mkdtemp(prefix="msx-triage-"))
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(TRIAGE), str(p), "--out", str(out), "--json-only"]
    if no_disasm:
        cmd.append("--no-disasm")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    evidence_path = out / "evidence.json"
    evidence = None
    if evidence_path.is_file():
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    report_path = out / "report.md"
    # triage --json-only skips report.md; regenerate lightly if missing
    report = None
    if report_path.is_file():
        report = report_path.read_text(encoding="utf-8")
    elif evidence:
        # re-run without json-only for report
        subprocess.run(
            [sys.executable, str(TRIAGE), str(p), "--out", str(out)]
            + (["--no-disasm"] if no_disasm else []),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if report_path.is_file():
            report = report_path.read_text(encoding="utf-8")
    return {
        "ok": r.returncode == 0 and evidence is not None,
        "out_dir": str(out),
        "evidence": evidence,
        "report_markdown": report,
        "stderr": (r.stderr or "")[-1000:],
        "returncode": r.returncode,
    }


def tool_read_evidence(out_dir: str) -> dict[str, Any]:
    out = Path(out_dir).expanduser().resolve()
    ep = out / "evidence.json"
    rp = out / "report.md"
    if not ep.is_file():
        return {"ok": False, "error": f"missing {ep}"}
    return {
        "ok": True,
        "evidence": json.loads(ep.read_text(encoding="utf-8")),
        "report_markdown": rp.read_text(encoding="utf-8") if rp.is_file() else None,
    }


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    if name == "msx_doctor":
        return tool_doctor()
    if name == "msx_triage":
        return tool_triage(
            arguments["path"],
            arguments.get("out_dir"),
            bool(arguments.get("no_disasm", False)),
        )
    if name == "msx_read_evidence":
        return tool_read_evidence(arguments["out_dir"])
    raise ValueError(f"unknown tool {name}")


def handle(msg: dict[str, Any]) -> None:
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    # Notifications (no id)
    if req_id is None and method:
        if method == "notifications/initialized":
            return
        return

    if method == "initialize":
        _result(
            req_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
        return

    if method == "ping":
        _result(req_id, {})
        return

    if method == "tools/list":
        _result(req_id, {"tools": TOOLS})
        return

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            result = call_tool(name, arguments)
            _result(
                req_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2, ensure_ascii=False),
                        }
                    ],
                    "structuredContent": result,
                    "isError": bool(isinstance(result, dict) and result.get("ok") is False),
                },
            )
        except Exception as e:
            _result(
                req_id,
                {
                    "content": [{"type": "text", "text": f"error: {e}"}],
                    "isError": True,
                },
            )
        return

    if method == "resources/list":
        _result(req_id, {"resources": []})
        return

    if method == "prompts/list":
        _result(req_id, {"prompts": []})
        return

    _error(req_id, -32601, f"Method not found: {method}")


def main() -> int:
    # stderr logging only
    print(f"{SERVER_NAME} mcp listening on stdio root={ROOT}", file=sys.stderr)
    while True:
        msg = _read_message()
        if msg is None:
            break
        handle(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
