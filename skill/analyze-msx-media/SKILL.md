---
name: analyze-msx-media
description: >-
  Triage and reverse-engineer MSX cartridge ROMs (.rom/.bin) and disk images
  (.dsk/.dmk) like an REA-style pipeline: header/mapper inventory, static Z80
  disassembly, optional openMSX/Emulicious dynamic probes, and an Evidence
  report. Use when the user asks to analyze, disassemble, RE, dump, or explain
  an MSX ROM, disk, mapper, AB header, BIOS calls, or cartridge behavior.
---

# Analyze MSX Media

REA does not admit Z80/MSX. This skill is the MSX substitute: run local triage
first, then deepen with emulator tools. Prefer evidence over guesses; mark
mapper guesses as heuristic.

Multi-LLM install (REA-style skill + MCP) lives in
`~/msx-rea`. Prefer MCP tools `msx_triage` / `msx_doctor` when
the `msx-agents` server is connected; otherwise run the CLI/scripts below.

```bash
msx-agents setup --all-detected -y    # skills + MCP for every detected agent
msx-agents doctor
msx-agents triage /abs/path/game.rom --out /tmp/msx-triage-game
```

## When to use

- User supplies or points at `.rom`, `.bin`, `.dsk`, `.dmk`, `.cas`, or an MSX
  dump path
- Questions about mappers (Konami/SCC/ASCII8/16), `AB` headers, INIT, slots,
  disk loaders, or Z80 routines inside MSX media

Skip for ordinary bluemsx/openMSX **source** architecture questions with no
binary target.

## Quick start (always)

1. Resolve an **absolute path** to the media file. Refuse to invent paths.
2. Run triage (creates JSON + markdown under a work dir):

```bash
python3 ~/msx-rea/skill/analyze-msx-media/scripts/msx_triage.py \
  /absolute/path/to/media.rom \
  --out /tmp/msx-triage-<basename>
# or: msx-agents triage /absolute/path/to/media.rom --out /tmp/msx-triage-<basename>
```

3. Read `report.md` and `evidence.json` from `--out`.
4. Answer from that Evidence. Continue only where the user's question needs
   deeper static or dynamic work (below).

If triage fails, say what failed and continue with any partial fields plus
manual hex/`xxd` checks.

## Pipeline (REA-like routing)

```
media path
  → msx_triage.py          (inventory + heuristic mapper + strings + tools)
  → static deepen          (z80dasm / MDL / optional Ghidra Z80)
  → dynamic deepen         (openMSX debugger Tcl; Emulicious if MSX1 RE UI)
  → Evidence report        (template below)
```

### Target routing

| Target | First action | Next |
|--------|--------------|------|
| `.rom` / raw cart dump | `msx_triage.py` | Disasm from INIT; openMSX BP at INIT |
| `.dsk` / `.dmk` | `msx_triage.py` (FAT12 listing) | Identify boot/`AUTOEXEC`/BLOAD; openMSX disk boot |
| `.cas` | Note in report as tape; list with available tools | openMSX cassette load if needed |
| Unknown binary claiming MSX | `msx_triage.py` then classify | Stop if no `AB` and not disk geometry |

### Tool preference (installed tools only)

Do **not** install Ghidra/Java/Emulicious unless the user asks. Detect with
`command -v` / path checks; skip missing tools and record `tool_status`.

| Role | Prefer | Fallback |
|------|--------|----------|
| Inventory | `msx_triage.py` | `xxd` + manual `AB` parse |
| Mapper DB | https://romdb.vampier.net (known titles) | Heuristic only |
| CLI forge | `msxforge` if on PATH | triage heuristics |
| Static asm | `z80dasm` then MDL (`java -jar mdl.jar -da`) | Ghidra Z80 GUI/headless if user has it |
| Dynamic | `openmsx` + [openmsx_boot_probe.tcl](scripts/openmsx_boot_probe.tcl) | Emulicious interactive RE |
| Disk carve | MSXFileForge / triage FAT12 | openMSX diskmanipulator |

Command cheat sheet: [references/tool-commands.md](references/tool-commands.md).  
Headers/mappers: [references/mappers-and-headers.md](references/mappers-and-headers.md).

## Static deepen

After triage:

1. Use reported `load_base` (usually `0x4000` or `0x8000`) and `init` address.
2. Disassemble:

```bash
z80dasm -l -g 0x4000 -o /tmp/out.asm /absolute/path/to/file.rom
# or -g 0x8000 when header/text points at page 2
```

3. Name BIOS/MSX-DOS calls using known entry points from the mapper/header
   reference; do not invent symbol names without an address hit.
4. For megarom (>64 KiB): treat banks as separate windows; never claim a single
   linear 64K image covers the whole cart without bank evidence.
5. Optional Ghidra: import as raw Z80, base = load address. No mapper emulation.

## Dynamic deepen (openMSX)

When behavior, banking, or VDP/IO matters:

```bash
openmsx -carta /absolute/path/to/file.rom \
  -script ~/msx-rea/skill/analyze-msx-media/scripts/openmsx_boot_probe.tcl
```

Adapt the Tcl: set breakpoint at INIT from Evidence, log writes to mapper
regs (`0x6000`/`0x7000`/`0x5000`/…), dump slots. Prefer non-interactive
`-script` for agent runs; use GUI debugger when the user is driving.

Emulicious: prefer for MSX1 interactive code/data separation and reverse-step
when installed; note MSX2+/mapper limits.

## Evidence report format

Deliver a short Korean or English report (match the user) with these sections.
Fill unknowns explicitly.

```markdown
# MSX media analysis: <filename>

## Identity
- Path, size, SHA256
- Kind: rom | dsk | dmk | cas | unknown
- AB header: yes/no; INIT/STATEMENT/DEVICE/TEXT
- Mapper: <name> (confidence: database | heuristic | user | unknown)
- Load base / entry

## Inventory
- ROM: pages, mirrors, notable strings
- Disk: volume, files (name, size, type), boot hints

## Static findings
- Key routines / tables (address + role)
- BIOS/DOS calls observed
- Limitations (no bank coverage, etc.)

## Dynamic findings (if run)
- Breakpoints, bank writes, observed behavior

## Tool status
- triage / z80dasm / openmsx / … : ok | missing | failed

## Next steps
- Concrete follow-ups only
```

Also keep machine-readable `evidence.json` from triage when available.

## Rules of evidence

- Mapper from write-count heuristics is **not** ground truth; cross-check romdb
  or runtime bank writes when it matters.
- Distinguish file offset vs Z80 address vs banked page.
- Do not claim REA/Ghidra-via-REA support for Z80.
- Do not distribute copyrighted ROM bytes in chat; summarize and cite addresses.
- Prefer re-running `msx_triage.py` after the user swaps files.

## Optional outputs

If the user wants a living disassembly tree, create under a path they choose:

```text
msx-re/<name>/
  evidence.json
  report.md
  disasm/main.asm      # from z80dasm when available
  notes.md             # agent annotations
```
