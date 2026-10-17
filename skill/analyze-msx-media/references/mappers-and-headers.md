# MSX headers and mappers

## Cartridge `AB` header (16 bytes at file start when present)

| Offset | Field | Notes |
|--------|-------|-------|
| +0 | `'A''B'` | Signature |
| +2 | INIT | Word; `0` = none. BIOS CALLs this |
| +4 | STATEMENT | Word or 0 |
| +6 | DEVICE | Word or 0 |
| +8 | TEXT | Word or 0 (BASIC text pointer) |
| +10.. | reserved / unused | Often zeros |

Common load bases:

- **0x4000** — page 1 cart (most games)
- **0x8000** — page 2 (16K page2 / some utilities)

16K ROM with TEXT/INIT in `0x8000..0xBFFF` often maps as page 2 (openMSX `PAGE2`).

## Mapper write targets (heuristic / openMSX-style)

Count `LD (nn),A` (`0x32` + le16) in the image when size > 64 KiB:

| Addresses | Suggests |
|-----------|----------|
| 0x5000, 0x7000, 0x9000, 0xB000 | Konami SCC |
| 0x4000, 0x8000, 0xA000 | Konami (no SCC) |
| 0x6000, 0x6800, 0x7000, 0x7800 | ASCII 8K |
| 0x6000, 0x7000, 0x77FF | ASCII 16K |

Shared addresses (0x6000/0x7000) score multiple types; take the max count.
Fails on exotic/custom mappers — verify with romdb or runtime writes.

Size ≤ 64 KiB: usually mirrored/plain (`NORMAL` / `MIRRORED`), not banked.

## Disk geometry (`.dsk`)

Typical single-sided 360K: 80 tracks × 9 sectors × 512 = 368640 bytes.
FAT12 media descriptor often `0xF9`/`0xF8`. Directory starts after reserved + FATs.

File types in directory attribute / extension: `.BAS`, `.COM`, `.BIN` (BLOAD), etc.

## Useful BIOS / system addresses (Z80)

| Addr | Name | Role |
|------|------|------|
| 0x0000 | CHKRAM / start | Reset |
| 0x000C | RDSLT | Read from slot |
| 0x0014 | WRSLT | Write to slot |
| 0x0024 | ENASLT | Enable slot |
| 0x0047 | FILVRM | Fill VRAM |
| 0x005C | LDIRVM | Block to VRAM |
| 0x0093 | WRTVDP | Write VDP reg |
| 0x013E | GTSTCK | Joystick |
| 0x0141 | GTTRIG | Trigger |

MSX-DOS / BDOS via `0x0005` when DOS is present; cart code often uses BIOS only.
