# msx-rea

MSX ROM/DISK 리버싱 툴킷 (REA 스타일). Agent Skill + MCP 서버로 Cursor, Codex, Gemini 등 여러 LLM 클라이언트에서 같은 분석 파이프라인을 씁니다.

**홈 디렉터리:** `~/msx-rea`

---

## 디렉터리 구조

```text
msx-rea/
  README.md
  bin/msx-agents                 # CLI (setup / doctor / triage / mcp / clients)
  lib/msx_mcp_server.py          # MCP stdio 서버
  skill/analyze-msx-media/       # Agent Skill
    SKILL.md
    scripts/msx_triage.py
    scripts/openmsx_boot_probe.tcl
    references/
```

호환용 링크:

- `~/.local/bin/msx-agents` → `~/msx-rea/bin/msx-agents`
- `~/.local/share/msx-agents` → `~/msx-rea`

---

## 1. 설치 / 멀티 LLM 등록

```bash
export PATH="$HOME/.local/bin:$PATH"

# 감지된 모든 에이전트에 skill 심볼릭 링크 + MCP 등록
msx-agents setup --all-detected -y

# 특정 클라이언트만
msx-agents setup --client cursor -y
msx-agents setup --client cursor --client codex -y

# skill만 설치 (MCP 설정 파일은 건드리지 않음)
msx-agents setup --all-detected --skill-only -y

# 적용 전 계획만 보기
msx-agents setup --all-detected --dry-run
```

지원 클라이언트 id: `universal`, `cursor`, `claude_code`, `claude_desktop`, `codex`, `gemini_cli`, `antigravity`, `opencode`, `copilot`, `windsurf`, `factory`

```bash
msx-agents clients    # 지원/감지 목록
msx-agents doctor     # skill 링크 · MCP 등록 · 외부 도구 상태
```

등록 후 **Cursor / Codex / Gemini 등을 재시작**해야 MCP·skill이 로드됩니다.

---

## 2. CLI로 ROM/DISK 분석 (트라이아지)

```bash
msx-agents triage /절대경로/game.rom --out /tmp/msx-out
msx-agents triage /절대경로/disk.dsk --out /tmp/msx-out --no-disasm
msx-agents triage /절대경로/game.rom --out /tmp/msx-out --json-only
```

| 옵션 | 설명 |
|------|------|
| `--out DIR` | `evidence.json`, `report.md` 출력 디렉터리 (필수) |
| `--no-disasm` | `z80dasm` 호출 생략 |
| `--json-only` | 터미널에는 JSON만 출력 (파일은 둘 다 기록) |

직접 스크립트 호출도 동일합니다.

```bash
python3 ~/msx-rea/skill/analyze-msx-media/scripts/msx_triage.py \
  /절대경로/game.rom --out /tmp/msx-out
```

트라이아지 결과:

- `AB` 헤더 (INIT/STATEMENT/DEVICE/TEXT)
- 매퍼 휴리스틱 (Konami / SCC / ASCII8/16 등, confidence 표시)
- 로드 베이스·엔트리
- 디스크면 FAT12 루트 목록
- `z80dasm`이 PATH에 있으면 디스어셈 (`disasm_main.asm`)

---

## 3. LLM / MCP에서 쓰기

MCP 서버 이름: `msx-agents`  
수동 기동:

```bash
msx-agents mcp
# 또는
python3 ~/msx-rea/lib/msx_mcp_server.py
```

### MCP 도구

| 도구 | 역할 |
|------|------|
| `msx_doctor` | 설치·도구 상태 점검 |
| `msx_triage` | ROM/DISK 트라이아지 → Evidence JSON + report |
| `msx_read_evidence` | 기존 `--out` 디렉터리의 evidence 다시 읽기 |

에이전트에게 예:

> `msx_triage`로 `/path/to/game.rom` 분석해줘. out은 `/tmp/msx-out`.

Skill 이름: `analyze-msx-media` (채팅에서 `/analyze-msx-media` 또는 자동 선택).  
상세 워크플로·매퍼/BIOS 참고: `skill/analyze-msx-media/SKILL.md`

---

## 4. 동적 분석 (openMSX)

트라이아지에서 얻은 INIT 주소로 프로브:

```bash
export MSX_PROBE_INIT=0x4010          # Evidence의 entry
export MSX_PROBE_OUT=/tmp/msx-probe.log
openmsx -carta /절대경로/game.rom \
  -script ~/msx-rea/skill/analyze-msx-media/scripts/openmsx_boot_probe.tcl
```

정적 디스어셈 (별도 설치):

```bash
# 예: sudo apt install z80dasm
z80dasm -l -g 0x4000 -o out.asm /절대경로/game.rom
```

---

## 5. 권장 파이프라인

1. `msx-agents triage … --out /tmp/msx-out`
2. `report.md` / `evidence.json` 확인 (매퍼는 heuristic이면 romdb·런타임으로 검증)
3. 필요 시 `z80dasm` 또는 openMSX 프로브
4. LLM에는 Evidence 주소·문자열만 인용 (ROM 바이트 전체 배포 금지)

---

## 6. doctor가 missing으로 보는 도구

| 도구 | 용도 | 비고 |
|------|------|------|
| `openmsx` | 동적 디버그 | 있으면 좋음 |
| `z80dasm` | 정적 디스어셈 | 선택 |
| `msxforge` | ROM/디스크 CLI | 선택 |
| `java` | MDL 등 | 선택 |

없어도 트라이아지·MCP·skill은 동작합니다.

---

## 7. 문제 해결

| 증상 | 조치 |
|------|------|
| `msx-agents: command not found` | `export PATH="$HOME/.local/bin:$PATH"` 후 `msx-agents setup -y` |
| Cursor에 MCP 안 보임 | `msx-agents setup --client cursor -y` 후 Cursor 재시작 |
| skill 안 잡힘 | `msx-agents doctor`로 심볼릭 링크 확인, 새 채팅 시작 |
| 매퍼가 이상함 | heuristic 한계 — romdb 또는 openMSX 뱅크 write 로그로 확인 |
