# Tool commands

Detect before use: `command -v <tool>`. Paths below are examples.

## Triage (required)

```bash
python3 ~/msx-rea/skill/analyze-msx-media/scripts/msx_triage.py \
  /abs/path/game.rom --out /tmp/msx-triage-game
# or: msx-agents triage /abs/path/game.rom --out /tmp/msx-triage-game
```

Flags: `--json-only`, `--no-disasm`, `--load-base 0x4000`.

## z80dasm

```bash
z80dasm -l -g 0x4000 -o out.asm /abs/path/game.rom
z80dasm -l -g 0x8000 -o out.asm /abs/path/game.rom
```

## MDL (if jar present)

```bash
java -jar /path/to/mdl.jar -cpu z80msx -da code /abs/path/game.rom
```

## MSXFileForge CLI

```bash
msxforge rom /abs/path/game.rom
msxforge list /abs/path/disk.dsk
```

## openMSX

```bash
# Cart + probe script
openmsx -carta /abs/path/game.rom \
  -script ~/msx-rea/skill/analyze-msx-media/scripts/openmsx_boot_probe.tcl

# Disk
openmsx -diska /abs/path/disk.dsk

# Console helpers (inside openMSX): debug disasm, debug breakpoint create, reg, slotmap
```

Set `MSX_PROBE_INIT=0x4010` (example) before launch if the Tcl reads that env
via a wrapper; default script uses header parse from a sidecar or 0x4010.

## Emulicious

GUI: open ROM → Debugger. Optional VS Code extension `emulicious.emulicious-debugger`.
No stable headless CLI assumed — use only when the user can interact or Remote Debugging is on.

## romdb

Browser: `https://romdb.vampier.net/` — search by title/hash when heuristic mapper is uncertain.

## Ghidra Z80 (manual)

File → Import → raw binary → Language Z80 → base `0x4000` or `0x8000`.
Export via project-specific scripts (e.g. ExportZ80.java patterns); not automated here.
