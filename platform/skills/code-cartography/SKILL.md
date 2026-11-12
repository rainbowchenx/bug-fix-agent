---
name: code-cartography
description: Agent-2 Code Cartographer SOP — read CLAUDE.md, detect cartography profile, map architecture, match defects to code paths into code-knowledge. Use when preparing or enriching code-knowledge for Agent-3; never freestyle schema fields or invent paths.
profiles: cartography
---

# Code Cartography（Agent-2）

SOP for building `code-knowledge`. Prefer the Python entrypoint; use this skill to guide Claude Code / SDK sessions.

`cartographyProfile` is **caller-supplied** (`--cartography-profile` / `options.cartographyProfile`). Do not infer electron / micro-frontend / device-web from deps or folder names.

## Do / Don't

| Do | Don't |
|---|---|
| Read target `CLAUDE.md` / `.claude` first | Invent file paths that do not exist |
| Call `run_cartographer` with caller `cartography_profile` | Dump full ticket observed/expected/steps into matching queries; do not guess the profile |
| Cap candidates at **3** per defect; **0 is valid (do not pad)** | Exceed cap, pad to 3, cite route tables/shells, or invent paths |
| Follow profile biases (electron / micro_frontend / device_web) | Write `CODEBASE_MAP.md` or edit target repo by default |
| SDK: thicken architecture + weak path matches only | Follow imports/call-flow per ticket (that is Agent-3); mutate the repo |

## Input contract

Read `docs/contracts/v0.1/defect-batch-guide.md` before matching. Default match pool: `strict` / `locatable_only` / `needs_info`. Do not treat other pools as fixable.

## Pipeline

```text
workDir + defect-batch + cartographyProfile
  → discover repoRoots
  → record techStack hints (do not guess profile)
  → map architecture by the given profile (catalog files, not path regex)
  → match tickets using architecture indexes + title tokens
    (do not fill tickets with architecture entryPoints when no path token hit)
  → optional SDK enrich (Read/Glob/Grep + read-only Bash;
     prompt only weak/empty/false-medium tickets, cap 8;
     max_turns = base + per_ticket × weak_count, default 6+3×n)
  → on max_turns: salvage JSON from the stream / one resume turn; keep baseline
  → validate_code_knowledge → code-knowledge.json
```

### Code entrypoint

```python
from bugfix_contracts.defect_batch import load_defect_batch
from bugfix_platform import run_cartographer

batch = load_defect_batch("./defect-batch.json")
knowledge = run_cartographer(
    work_dir="./repos",
    defect_batch=batch,
    cartography_profile="micro_frontend",  # caller-supplied
    cartography_mode="heuristic",  # or "sdk"
)
```

## Confidence

| Situation | Level |
|---|---|
| No candidates | `low`（词表不重合时另标 `gap=no_path_token_overlap`） |
| Single path/grep hit | `medium` |
| ≥2 path hits, or CodeGraph hit | `high`（启发式；**SDK 覆盖进来的票最多 `medium`**） |
| Missing titleTag/testModule/intent (A1) | ≤ `medium` |

## Profile biases

- **electron_node**: follow `package.json.main` / `loadFile` / `contextBridge`; IPC prefix → `controller/<domain>/`; UI copy → `web/src` renderer boot, not `views/`
- **micro_frontend**: read `.gitmodules` / mount divs / `vue.app.js` as the module list; `testModule` → `src/<App>/` first; PC vs H5 from `root-application.js`
- **device_web**: split PC/mobile entries first; capability defects → `Common/service/device.js` before views; real bridge is `jsWebControl`

## Output contract

See `docs/contracts/v0.1/code-knowledge.md` (Pydantic SSOT: `contracts/bugfix_contracts/code_knowledge.py`). Input artifact: `docs/contracts/v0.1/defect-batch-guide.md`.

## Injected repo skills

Users may overlay **repo-specific** skills (read order, test vs src layout, module aliases, product-line naming). Same dirs feed Agent-2 and Agent-3. Merge order (later same-name wins); overlay always outranks package SOP in the session prompt:

1. Package builtins
2. Each repo root `.claude/skills`
3. `workDir/.bugfix/skills`
4. `--skills-dir` / `options.skillsDirs` / `BUGFIX_SKILLS_DIR`

Load if frontmatter `profiles` contains `cartography` (this agent), `analyze` (Agent-3), or `bugfix` (both). Unlabelled skills under `.bugfix/skills` or `--skills-dir` also load for both. Overlay skills **guide** matching bias and directory habits; they do **not** change schema gates, match-pool, or the 3-candidate cap.

Template: `docs/prompts/agent2/example-injected-skill.md`.

## Related package skills

- `electron-process-boundary` — electron process roles
- `monorepo-workspace` — multi-root layout
- `hierarchical-localization` — localization hierarchy when matching UI defects
