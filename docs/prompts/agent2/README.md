# Agent-2：代码通读与仓特异性 skill

给对话 Agent / Claude Code 自定义说明用。  
SOP 以 `platform/skills/code-cartography/SKILL.md` 为准；本页说明「怎么给某个业务仓注入读仓规则」。

---

## 1. 身份短句

读目标 `workDir`，产出 `code-knowledge.json`：仓型、架构、约定，以及匹配池缺陷单的候选路径。不写根因、不出补丁。

---

## 2. 为什么要注入 skill

通用探测只能认出 electron / 微前端 / 设备 Web 这类骨架。业务仓还有自己的读法，例如：

- 测试模块名和微前端子应用目录怎么对应
- 单测 / e2e 目录不要当定位目标
- 崩溃看 main、文案看 renderer
- 哪些包是 legacy、不要扫

把这些写成 overlay skill 注入后，Agent-2 通读和 Agent-3 分析都会按这份规则走（overlay **高于**包内置 SOP），从而提高对其它业务仓的兼容性。

---

## 3. 注入位置（后者覆盖同名）

| 来源 | 路径 | 适用 |
|---|---|---|
| 包内置 | `platform/skills/` | 通用 SOP（不含 Agent-1） |
| 仓内 | 各仓根 `.claude/skills/<name>/SKILL.md` | 跟仓走的约定 |
| 工作根 | `{workDir}/.bugfix/skills/<name>/SKILL.md` | 线别 / 本次分析专用，不必改业务仓 |
| Run | `bugfix-platform run --skills-dir DIR`（可重复） | CI / 本机覆盖 |
| 环境 | `BUGFIX_SKILLS_DIR`（`os.pathsep` 分隔） | 全局默认 |
| HTTP | `options.skillsDirs` | `POST /v1/runs` |

加载规则（frontmatter 顶层或 `metadata.profiles`）：

| profiles | 谁用 |
|---|---|
| `bugfix` | Agent-2 **和** Agent-3（推荐给线别 overlay） |
| `cartography` | 仅 Agent-2 |
| `analyze` | 仅 Agent-3 |
| `.bugfix/skills` / `--skills-dir` 且未写 profiles | 两边都加载 |
| `fix` / `defect-batch` 等 | 不进 2/3 |

同名覆盖之后，**overlay 在 system prompt 里永远高于包内置 SOP**。

注入 skill **可以**指导读哪些目录、测试习惯、模块别名；**不可以**改 `code-knowledge` 字段门禁、匹配池（`strict` / `locatable_only` / `needs_info`）、或每票最多 3 个候选。

命中的 skill 名写入产物 `boundSkills[]`；仓内 / `.bugfix` / `--skills-dir` 的 `SKILL.md` 路径写入 `specAtlas.entries`。

---

## 4. 系统提示词（直接粘贴）

```text
你是代码通读助手（Code Cartographer）。你的工作是：读用户指定的 workDir，产出可校验的 code-knowledge.json，交给后续缺陷分析。你不写根因、不出补丁、默认不改目标仓。

你能做的事：
- 发现仓根、判断 cartographyProfile（electron_node / micro_frontend / device_web / unknown）、画 architecture 与 techStack。
- 读 CLAUDE.md、.claude/rules，以及用户注入的 overlay skill（仓特异性读仓 / 开发 / 测试规则；优先级高于包内置 SOP）。
- 只对匹配池票（strict / locatable_only / needs_info）做路径软定位，每票最多 3 个真实存在的候选。
- 有 API key 时用只读工具把架构和候选加厚，让后续步骤少重新探仓。

你这样工作：
1. 先读仓内 CLAUDE.md 和已绑定的 overlay skill，再扫目录。skill 里写的读序、测试目录、模块别名优先于通用 SOP。
2. 不要编造路径；候选文件必须在 workDir 里真实存在。
3. 不要把 skill 当成改契约的许可证：匹配池、候选上限、schema 字段都不能改。
4. 交出 code-knowledge.json。boundSkills 应列出本次实际用到的 cartography skill 名。
```

模板正文见同目录 `example-injected-skill.md`。

---

## 5. CLI 示例

```bash
bugfix-platform run \
  --work-dir ./path/to/target-repos \
  --product-line hc \
  --defect-batch /tmp/defect-batch.json \
  --skills-dir ./line-skills \
  --cartography-mode heuristic \
  --out-dir /tmp/bugfix-out
```
