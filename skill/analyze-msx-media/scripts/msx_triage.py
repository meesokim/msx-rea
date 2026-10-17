#!/usr/bin/env python3
"""Triage MSX ROM / disk images into Evidence JSON + report.md."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tool_status() -> dict[str, str]:
    tools = ("z80dasm", "openmsx", "msxforge", "java")
    out: dict[str, str] = {}
    for name in tools:
        out[name] = "ok" if shutil.which(name) else "missing"
    return out


def parse_ab_header(data: bytes) -> dict[str, Any] | None:
    if len(data) < 16 or data[0:2] != b"AB":
        return None

    def word(off: int) -> int:
        return data[off] | (data[off + 1] << 8)

    fields = {
        "signature": "AB",
        "init": word(2),
        "statement": word(4),
        "device": word(6),
        "text": word(8),
    }
    return fields


def guess_load_base(size: int, header: dict[str, Any] | None) -> int:
    if not header:
        if size <= 0x4000:
            return 0x4000
        return 0x4000
    addrs = [header[k] for k in ("init", "statement", "device", "text") if header[k]]
    page2 = sum(1 for a in addrs if (a & 0xC000) == 0x8000)
    page1 = sum(1 for a in addrs if (a & 0xC000) == 0x4000)
    if page2 > page1:
        return 0x8000
    return 0x4000


def guess_mapper(data: bytes) -> dict[str, Any]:
    size = len(data)
    if size == 0:
        return {"name": "unknown", "confidence": "none", "scores": {}}
    if size < 0x10000:
        header = parse_ab_header(data)
        if header and size <= 0x4000:
            init, text = header["init"], header["text"]
            text_p2 = (text & 0xC000) == 0x8000
            no_init = init == 0
            init_p2 = (init & 0xC000) == 0x8000
            init_ret = init_p2 and data[init & (size - 1)] == 0xC9
            if text_p2 and (no_init or init_ret):
                return {
                    "name": "page2",
                    "confidence": "heuristic",
                    "scores": {},
                    "note": "16K AB header suggests page-2 mapping",
                }
        return {
            "name": "mirrored" if size < 0x10000 else "normal",
            "confidence": "heuristic",
            "scores": {},
            "note": "size < 64KiB; treat as plain/mirrored unless runtime says otherwise",
        }

    scores = {
        "ascii16": 0,
        "ascii8": 0,
        "konami": 0,
        "konami_scc": 0,
    }
    end = size - 3
    for i in range(end):
        if data[i] != 0x32:
            continue
        addr = data[i + 1] | (data[i + 2] << 8)
        if addr in (0x5000, 0x9000, 0xB000):
            scores["konami_scc"] += 1
        if addr in (0x4000, 0x8000, 0xA000):
            scores["konami"] += 1
        if addr in (0x6800, 0x7800):
            scores["ascii8"] += 1
        if addr == 0x6000:
            scores["konami"] += 1
            scores["ascii8"] += 1
            scores["ascii16"] += 1
        if addr == 0x7000:
            scores["konami_scc"] += 1
            scores["ascii8"] += 1
            scores["ascii16"] += 1
        if addr == 0x77FF:
            scores["ascii16"] += 1

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return {
            "name": "unknown",
            "confidence": "none",
            "scores": scores,
            "note": "no LD (nn),A bank writes found",
        }
    return {
        "name": best,
        "confidence": "heuristic",
        "scores": scores,
        "note": "openMSX-style write-target counts; verify with romdb/runtime",
    }


def extract_strings(data: bytes, min_len: int = 6, limit: int = 40) -> list[str]:
    out: list[str] = []
    cur = bytearray()
    for b in data:
        if 32 <= b < 127:
            cur.append(b)
        else:
            if len(cur) >= min_len:
                out.append(cur.decode("ascii", errors="ignore"))
                if len(out) >= limit:
                    return out
            cur.clear()
    if len(cur) >= min_len and len(out) < limit:
        out.append(cur.decode("ascii", errors="ignore"))
    return out


def classify_kind(path: Path, data: bytes) -> str:
    suf = path.suffix.lower()
    if suf in (".dsk", ".dmk"):
        return "dmk" if suf == ".dmk" else "dsk"
    if suf == ".cas":
        return "cas"
    if suf in (".rom", ".mx1", ".mx2"):
        return "rom"
    if len(data) >= 16 and data[0:2] == b"AB":
        return "rom"
    # common DSK sizes
    if len(data) in (163840, 184320, 368640, 737280) and len(data) % 512 == 0:
        return "dsk"
    if suf == ".bin" and data[0:2] == b"AB":
        return "rom"
    return "unknown"


def parse_fat12_root(data: bytes) -> dict[str, Any]:
    """Best-effort FAT12 listing for standard .dsk images."""
    if len(data) < 512:
        return {"ok": False, "error": "too small"}
    bpb = data[0:512]
    # Jump + OEM
    bytes_per_sector = struct.unpack_from("<H", bpb, 11)[0] or 512
    sectors_per_cluster = bpb[13] or 1
    reserved = struct.unpack_from("<H", bpb, 14)[0] or 1
    fats = bpb[16] or 2
    root_entries = struct.unpack_from("<H", bpb, 17)[0]
    sectors_per_fat = struct.unpack_from("<H", bpb, 22)[0]
    if bytes_per_sector == 0 or root_entries == 0 or sectors_per_fat == 0:
        return {"ok": False, "error": "not a recognizable FAT BPB"}

    root_sectors = (root_entries * 32 + bytes_per_sector - 1) // bytes_per_sector
    root_off = (reserved + fats * sectors_per_fat) * bytes_per_sector
    root_end = root_off + root_sectors * bytes_per_sector
    if root_end > len(data):
        return {"ok": False, "error": "root directory out of range"}

    files: list[dict[str, Any]] = []
    for off in range(root_off, root_end, 32):
        ent = data[off : off + 32]
        name = ent[0:8]
        if name[0] in (0x00, 0xE5):
            if name[0] == 0x00:
                break
            continue
        attr = ent[11]
        if attr == 0x0F:
            continue  # LFN
        ext = ent[8:11]
        fname = name.decode("ascii", errors="replace").strip()
        fext = ext.decode("ascii", errors="replace").strip()
        full = f"{fname}.{fext}" if fext else fname
        size = struct.unpack_from("<I", ent, 28)[0]
        files.append(
            {
                "name": full,
                "attr": attr,
                "size": size,
                "directory": bool(attr & 0x10),
            }
        )

    vol = None
    for f in files:
        if f["attr"] & 0x08:
            vol = f["name"]
            break

    return {
        "ok": True,
        "bytes_per_sector": bytes_per_sector,
        "sectors_per_cluster": sectors_per_cluster,
        "reserved_sectors": reserved,
        "fat_count": fats,
        "sectors_per_fat": sectors_per_fat,
        "root_entries": root_entries,
        "volume_label": vol,
        "files": files[:200],
        "file_count": len(files),
    }


def run_z80dasm(rom: Path, out_asm: Path, load_base: int) -> dict[str, Any]:
    if not shutil.which("z80dasm"):
        return {"status": "missing"}
    try:
        # Limit work: only first 64K for huge megaroms unless smaller
        src = rom
        tmp = None
        data = rom.read_bytes()
        if len(data) > 0x10000:
            tmp = out_asm.with_suffix(".first64k.bin")
            tmp.write_bytes(data[:0x10000])
            src = tmp
        cmd = [
            "z80dasm",
            "-l",
            "-g",
            hex(load_base),
            "-o",
            str(out_asm),
            str(src),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if tmp and tmp.exists():
            tmp.unlink(missing_ok=True)
        return {
            "status": "ok" if r.returncode == 0 else "failed",
            "command": cmd,
            "stderr": (r.stderr or "")[:500],
            "asm": str(out_asm) if r.returncode == 0 and out_asm.exists() else None,
            "note": "disassembled first 64KiB only" if len(data) > 0x10000 else None,
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def run_msxforge(path: Path, kind: str) -> dict[str, Any]:
    if not shutil.which("msxforge"):
        return {"status": "missing"}
    sub = "rom" if kind == "rom" else "list"
    try:
        r = subprocess.run(
            ["msxforge", sub, str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "status": "ok" if r.returncode == 0 else "failed",
            "stdout": (r.stdout or "")[:4000],
            "stderr": (r.stderr or "")[:500],
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def analyze_rom(path: Path, data: bytes, out_dir: Path, do_disasm: bool, load_base_override: int | None) -> dict[str, Any]:
    header = parse_ab_header(data)
    load_base = load_base_override if load_base_override is not None else guess_load_base(len(data), header)
    mapper = guess_mapper(data)
    pages = max(1, (len(data) + 0x3FFF) // 0x4000)
    evidence: dict[str, Any] = {
        "kind": "rom",
        "size": len(data),
        "header": header,
        "load_base": load_base,
        "entry": header["init"] if header and header["init"] else load_base,
        "mapper": mapper,
        "page_count_16k": pages,
        "strings": extract_strings(data),
        "msxforge": run_msxforge(path, "rom"),
    }
    if do_disasm:
        asm_path = out_dir / "disasm_main.asm"
        evidence["z80dasm"] = run_z80dasm(path, asm_path, load_base)
    else:
        evidence["z80dasm"] = {"status": "skipped"}
    return evidence


def analyze_disk(path: Path, data: bytes) -> dict[str, Any]:
    fat = parse_fat12_root(data)
    return {
        "kind": "dsk" if path.suffix.lower() != ".dmk" else "dmk",
        "size": len(data),
        "fat12": fat,
        "strings": extract_strings(data[: min(len(data), 65536)], limit=30),
        "msxforge": run_msxforge(path, "dsk"),
        "header": None,
        "mapper": None,
        "load_base": None,
        "entry": None,
    }


def render_report(meta: dict[str, Any], body: dict[str, Any]) -> str:
    lines = [
        f"# MSX media analysis: {meta['filename']}",
        "",
        "## Identity",
        f"- Path: `{meta['path']}`",
        f"- Size: {meta['size']} bytes",
        f"- SHA256: `{meta['sha256']}`",
        f"- Kind: {body.get('kind', meta.get('kind'))}",
    ]
    hdr = body.get("header")
    if hdr:
        lines.append(
            f"- AB header: INIT=`{hdr['init']:04X}` STATEMENT=`{hdr['statement']:04X}` "
            f"DEVICE=`{hdr['device']:04X}` TEXT=`{hdr['text']:04X}`"
        )
    else:
        lines.append("- AB header: no")
    mapper = body.get("mapper")
    if mapper:
        lines.append(
            f"- Mapper: `{mapper.get('name')}` (confidence: {mapper.get('confidence')})"
        )
        if mapper.get("note"):
            lines.append(f"- Mapper note: {mapper['note']}")
        if mapper.get("scores"):
            lines.append(f"- Mapper scores: `{json.dumps(mapper['scores'])}`")
    if body.get("load_base") is not None:
        lines.append(f"- Load base: `0x{body['load_base']:04X}`")
    if body.get("entry") is not None:
        lines.append(f"- Entry: `0x{body['entry']:04X}`")

    lines += ["", "## Inventory"]
    if body.get("kind") in ("dsk", "dmk"):
        fat = body.get("fat12") or {}
        if fat.get("ok"):
            lines.append(f"- Volume: {fat.get('volume_label') or '(none)'}")
            lines.append(f"- Root files: {fat.get('file_count')}")
            for f in (fat.get("files") or [])[:40]:
                kind = "DIR" if f.get("directory") else "FILE"
                lines.append(f"  - [{kind}] {f['name']} ({f['size']} bytes)")
        else:
            lines.append(f"- FAT12: failed ({fat.get('error')})")
    else:
        lines.append(f"- 16K pages (ceil): {body.get('page_count_16k')}")
        strs = body.get("strings") or []
        if strs:
            lines.append("- Notable strings:")
            for s in strs[:15]:
                lines.append(f"  - `{s}`")

    lines += ["", "## Static findings"]
    zd = body.get("z80dasm")
    if zd:
        lines.append(f"- z80dasm: {zd.get('status')}")
        if zd.get("asm"):
            lines.append(f"- Disassembly: `{zd['asm']}`")
        if zd.get("note"):
            lines.append(f"- {zd['note']}")
    mf = body.get("msxforge")
    if mf and mf.get("status") == "ok" and mf.get("stdout"):
        lines.append("- msxforge output (truncated):")
        lines.append("```")
        lines.append(mf["stdout"][:1500])
        lines.append("```")

    lines += ["", "## Dynamic findings", "- (not run by triage; use openMSX probe if needed)", ""]
    lines += ["## Tool status"]
    for k, v in (meta.get("tools") or {}).items():
        lines.append(f"- {k}: {v}")

    lines += [
        "",
        "## Next steps",
        "- Verify mapper via romdb or openMSX bank-write logging if confidence is heuristic",
        "- Breakpoint at INIT in openMSX and step bank switches / BIOS calls",
        "- Annotate disassembly with BIOS symbols from skill reference",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="MSX ROM/DISK triage (REA-style Evidence)")
    ap.add_argument("path", type=Path, help="Absolute or relative media path")
    ap.add_argument("--out", type=Path, required=True, help="Output directory")
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--no-disasm", action="store_true")
    ap.add_argument(
        "--load-base",
        type=lambda s: int(s, 0),
        default=None,
        help="Override load base (e.g. 0x4000)",
    )
    args = ap.parse_args()

    path = args.path.expanduser().resolve()
    if not path.is_file():
        print(f"error: not a file: {path}", file=sys.stderr)
        return 2

    data = path.read_bytes()
    kind = classify_kind(path, data)
    out_dir = args.out.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "filename": path.name,
        "path": str(path),
        "size": len(data),
        "sha256": sha256_file(path),
        "kind": kind,
        "tools": tool_status(),
        "skill": "analyze-msx-media",
    }

    if kind in ("rom", "unknown") and (kind == "rom" or data[:2] == b"AB"):
        body = analyze_rom(path, data, out_dir, not args.no_disasm, args.load_base)
        if kind == "unknown":
            body["kind"] = "rom"
    elif kind in ("dsk", "dmk"):
        body = analyze_disk(path, data)
    elif kind == "cas":
        body = {
            "kind": "cas",
            "size": len(data),
            "strings": extract_strings(data, limit=20),
            "note": "tape image; use openMSX cassette tools for load analysis",
        }
    else:
        body = {
            "kind": "unknown",
            "size": len(data),
            "strings": extract_strings(data, limit=20),
            "note": "unrecognized; inspect manually",
            "header": parse_ab_header(data),
            "mapper": guess_mapper(data) if len(data) > 0 else None,
        }

    evidence = {"meta": meta, "analysis": body}
    (out_dir / "evidence.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report = render_report(meta, body)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    if args.json_only:
        print(json.dumps(evidence, indent=2, ensure_ascii=False))
    else:
        print(report)

    print(f"\nWrote {out_dir / 'evidence.json'}", file=sys.stderr)
    if not args.json_only:
        print(f"Wrote {out_dir / 'report.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
