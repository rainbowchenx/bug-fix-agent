# bugfix-agent 平台包（Agent-2 → Agent-3）

上传到公司 agent 平台（支持 LangGraph）用。**不含 Agent-1**——Agent-1 是图外独立的一步，
它的产物 `defect-batch.json` 作为本图的输入。

```text
Agent-1（独立 CLI/包）          本平台包
export.csv ──> defect-batch.json ──> validate_batch ──> agent2 ──> validate_knowledge
                                                                        │
                                                          agent3 <──────┘
                                                            │
                                                    validate_report ──> analysis-report.json
```

## 平台要求对照

| 要求 | 本包 |
|---|---|
| zip 根目录有 `graph.py` | ✅ `graph.py` |
| 暴露 `build_graph()` / `graph` / `main()` 之一 | ✅ 三个都暴露 |
| `requirements.txt` | ✅ |
| `.env`（可选） | ✅ 由 `graph.py` import 时读取（真实环境变量优先，不会被覆盖） |
| 模型配置复用平台「模型管理」 | ✅ 平台注入 `OPENAI_*`，本包自动映射成 `ANTHROPIC_*`（含 `/openai/`→`/anthropic/` 路径翻转） |
| `langgraph.json` | ➖ 仅给 LangGraph Server 用，Nexas **不读** |
| `pyproject.toml` | ➖ Nexas **不读** |

## 调用方式：路径或直接 JSON

根 `graph.py` 不是父图的转发壳，而是一层**适配器**——Nexas 只会把用户输入的
**一个字符串**塞进 state，而父图要求完整的 `defect_batch` / `work_dir` 等字段。

两种写法都接受，**顺序是：先试内联 JSON，不成立再当路径**。

### 写法一：直接贴 JSON（推荐，Dify 直传用这个）

```
用户输入：
    {
      "defect_batch": "E:/work/defect-batch.json",
      "work_dir":     "E:/repos/transport",
      "cartography_profile": "device_web"
    }
```

Nexas 追加的平台说明（跨设备文件传递、安全策略等）会被忽略——本图从第一个
`{` 开始按括号配对截取，配对结束即停，后面的文字一律不读。所以「输入即 JSON」
在这里是安全的。

### 写法二：给参数文件的路径

```
用户输入：
    E:/work/task-params.json
```

参数文件内容与写法一相同。相对路径按**参数文件所在目录**解析；内联 JSON 没有
文件目录，相对路径按 **cwd**（= 「业务项目根」）解析。

### 为什么内联 JSON 现在可行

早先只支持路径，是因为担心 Nexas 追加的两千多字符说明会破坏 JSON 解析。
按括号配对截取之后这个担心不成立：解析器只读到第一个完整的顶层对象为止，
追加内容根本进不了 `json.loads`。

**注意**：Windows 路径在 JSON 里要么用正斜杠（`E:/work/x.json`），要么用
合法的 `\\` 转义。直接写 `E:\work\x.json` 是非法 JSON。

### 参数文件字段

| 字段 | 必需 | 说明 |
|---|---|---|
| `action` | 否 | 默认 `run`。填写 `resume` 时按下节指定首轮产物和票号。 |
| `defect_batch` | **是** | Agent-1 产物 JSON 的路径 |
| `work_dir` | 否 | 业务代码根；缺省用 runner 的 cwd（= Nexas 里配的「业务项目根」） |
| `product_line` | 否 | 提供时须和 `defect_batch.productLine` 一致 |
| `posture` | 否 | 提供 `alpha` / `beta` 时须和 `defect_batch.posture` 一致 |
| `cartography_profile` | 否 | `device_web` / `micro_frontend` / `electron_node`；**不给会明显降质** |
| `cartography_mode` | 否 | `sdk` / `heuristic` |
| `analyze_mode` | 否 | `sdk` / `heuristic` |
| `ticket_ids` | 否 | 字符串数组，只跑这些票 |
| `apply_fix` | 否 | 默认关（只出方案，不改码） |
| `artifact_dir` | 否 | 缺省 `run` 落 `<work_dir>/.bugfix-runs/<时间戳>`，成功后更新 `LATEST` 指针；`resume` 缺省读该指针 |
| `trace_mode` | 否 | `summary`（默认）、`detailed`（实时正文和工具）、`off` |
| `repair_skill` | 否 | 本次任务的用户修复 Skill 文件，或直接含有 `SKILL.md` 的目录。使用时需要 Agent3 SDK 模式和凭据。 |
| `project_integrations` | 否 | `true` 时启用完整项目 MCP 和已安装的 Claude Code 插件。默认 `false`。 |

所有路径字段支持相对路径，相对**参数文件所在目录**解析。文件支持 `//` 整行注释。

字段拼错会直接报错（不会静默忽略），报错信息里列出无法识别的键。

### 导入反馈并续跑 Agent3

复制 [resume.example.json](resume.example.json)，填写 `defect_id` 为首轮已有尝试的票号。`artifact_dir` 可以省略，`resume` 默认读取 `<work_dir>/.bugfix-runs/LATEST` 指向的最近一次成功首跑。要续跑更早的批次可显式指定目录。续跑从首轮产物读取业务仓、缺陷批次和 Agent2 的知识，不需要再传 `defect_batch`。

**票级补充信息可以填表。** 首轮会在 `<artifact_dir>/defects/<票号>/feedback-form.md` 生成一份表单，用户在 `ANSWER` 标记之间填完保存即可。`resume` 省略 `feedback`、`feedback_file` 和 `revision_id` 时会自动导入已填写的表单。显式指定 `revision_id` 时使用已导入的反馈版本。表单支持 `observed` / `expected` / `steps` / `reject_hypothesis` / `acceptance` 等字段，以及回答 Agent 在 `rootCause.questions` 里提出的问题。

`feedback_file` 支持 [反馈 JSON](feedback.example.json) 或填写后的 `feedback-form.md`，相对路径以续跑参数文件所在目录为准。JSON 中的 `defectId` 须与 `defect_id` 一致。如果提供 `attemptId`，它必须指向该票最新尝试。省略 `feedback_file` 可使用已导入的反馈，此时也可用 `revision_id` 核对所用版本。续跑会更新首轮目录里的汇总报告并保留逐轮结果。

设置 `repair_skill` 后，Agent3 会把该文件正文放进独立的必用指令区，直接传给分析和实际修复的 SDK 会话。同名项目 Skill 继续单独加载，用户修复指导优先。无法读取、正文为空或选择启发式模式时会报错。保持 `apply_fix: false` 可先看修复方案，设为 `true` 才能通过证据门槛后生成隔离补丁。报告的 `skillDiscovery` 用 `source: user_repair` 标记此 Skill，实际是否遵循仍可用报告和轨迹复核。

`project_integrations: true` 适用于首跑和续跑的 SDK 会话。它加载工作根及发现的子仓中的全部 `.mcp.json` 服务，无须逐工具列白名单，并启用 Claude Code 用户、项目与本地配置以及同账号适用的已安装插件。插件目录从 `CLAUDE_CONFIG_DIR` 或用户的 `~/.claude` 找到。同名子仓 MCP 获得独立别名。Claude Code 自身的组织策略和服务认证仍生效。此开关会允许业务 MCP 和插件执行其自身操作，适用于信任这些配置的公司工作区。

### 输出

`graph.py` 把结果投影成客户端会读的字段：

| 字段 | 内容 |
|---|---|
| `summary` | 一行摘要（`状态：成功（stage=done）`） |
| `result` | 多行明细：票数、仓型、每票 outcome、产物目录 |
| `ok` | 布尔 |

产物本身（`analysis-report.json` / `code-knowledge.json` / 逐票快照）落在
`artifact_dir`。

#### 进 `output_files` 的三份产物

任务跑完会把下面三份（存在才发）复制到 Nexas 的数据目录并登记：

| 文件 | 去向 | 用途 |
|---|---|---|
| `analysis-report.md` | `outputs/` + `persist` | 人读的报告，**可下载** |
| `analysis-report.json` | `outputs/` + `persist` | 下游 Dify 节点读的结构化结果 |
| `code-knowledge.json` | `outputs/` + `persist` | 仓型知识，可继续传给后续任务 |

`outputs/` 是给下游节点消费的传递清单；`persist` 才把它登记成可下载的成果物。
报告同时走两条，因为下游要读、人也要下载。

前提是 Nexas 注入了 `NEXAS_TEMP_OUTPUT_DIR`（= `<数据目录>/outputs`）。本地直跑
没有这个变量，发布步骤自动跳过，不影响产物落在 `artifact_dir`。
Windows 上 `persist` 优先用 Git for Windows 的 Bash 执行 Nexas 文件脚本。常规安装可自动识别，自定义安装可把 `git.exe` 所在目录加入 Nexas runner 的 `PATH`。

设置 `"trace_mode": "detailed"` 后，任务日志实时显示模型可见正文、工具调用及结果预览、Agent2 补查和 Agent3 补救。宿主日志容量有限，达到上限后可在 `artifact_dir/logs/` 查看逐会话 JSONL。详细轨迹包含请求、未截断的模型可见正文和工具返回，以及结构化结果，可能含业务源码或附件数据。结果面板显示 Markdown 报告，超长时可从产物目录打开完整的 `analysis-report.md`。任务结束时还会打印本次的 token 用量与成本（`tok in=… out=… cache_read=… cost=$…`）。

## 模型配置

平台「模型管理」里绑定的模型会被自动使用。

Nexas 的 LangGraph 执行器注入的是 **`OPENAI_*`**（`OPENAI_API_KEY` /
`OPENAI_BASE_URL` / `OPENAI_MODEL`），而 Claude Agent SDK 只认
**`ANTHROPIC_*`**。本包在 `sdk/model_env.py` 里做了一层映射：

| 平台注入 | 映射成 | 处理 |
|---|---|---|
| `OPENAI_API_KEY` | `ANTHROPIC_AUTH_TOKEN` | 原样 |
| `OPENAI_BASE_URL` | `ANTHROPIC_BASE_URL` | **`/openai/` → `/anthropic/`** |
| `OPENAI_MODEL` | `ANTHROPIC_MODEL` | 原样 |

### 路径翻转的原因

同一个网关通常同时开两套协议（Nexas 客户端自己的 `q()` 函数就这么做）。
`OPENAI_BASE_URL` 指向的是 OpenAI 协议端点，直接喂给 SDK 会 404：

```
http://lanz.hikvision.com/v3/openai/model
                                 ↓ 翻转
http://lanz.hikvision.com/v3/anthropic/model
```

找不到 `/openai/` 时原样返回 —— 宁可让网关报 404 暴露配置问题，
也不瞎拼一个不存在的路径。

### 优先级

**原生 `ANTHROPIC_*` 永远优先。** 有值就不映射，本地开发用 `.env` 里
自己的凭据不会受平台影响。只补缺失的项。

映射通过 `ClaudeAgentOptions.env` 按次注入，**不写 `os.environ`**：

```python
process_env = {**inherited_env, ..., **self._options.env, ...}
```

所以一次 run 换了 key 不会影响下一次，多票串行也不会互相干扰。

### 缓存

Agent-2 的调查缓存 key 算的是**映射后**的模型/网关，换模型不会误命中旧缓存。

## 依赖清单的特殊性

Nexas 装依赖的方式是：先过滤掉 base venv 已有的 `langgraph` / `langchain-core` /
`langgraph-checkpoint-sqlite` / `python-dotenv`，再对剩下的执行
`pip install --no-deps`。

**`--no-deps` 不解析依赖树** —— 每个包的全部传递依赖都必须单独列在
`requirements.txt` 里，漏一个就是运行时 `ImportError`。

而且装失败**只 warn 不阻塞**，所以表现往往是"导入成功、运行不工作"。

### `claude-agent-sdk` 为什么不走 pip

它的 wheel 有 179 MB（解压后 357 MB，其中 356 MB 是 `_bundled/claude.exe`），
但在内网 Artifactory 上**需要认证**：

```
HTTP/1.1 401 WWW-Authenticate: Basic realm="Artifactory Realm"
```

pip 在无人值守环境拿不到凭据 → 整批装依赖失败 → 其余 19 个包也一起没装上。

所以改成**代码随包分发**：

| 内容 | 大小 | 来源 |
|---|---|---|
| `claude_agent_sdk/`（纯 Python） | 0.5 MB | 打包时 vendor 进 zip |
| `claude.exe` | 356 MB | **不打包**，运行时用宿主 Nexas 自带的那份 |

这让 zip 只从 202 KB 涨到 368 KB。

### `claude.exe` 怎么找到

`bugfix_platform/sdk/claude_cli.py` 按序尝试：

1. `BUGFIX_CLAUDE_CLI` 环境变量（手工指定）
2. `PATH` 里的 `claude.exe`；若是 npm 的 `claude.CMD` 垫片，解析它内容里引用的真实 exe
3. SDK 包内的 `_bundled/`（我们不带，通常命中不了）
4. 顺父进程链找到宿主应用（`Nexas OS.exe` 等），取它旁边的
   `resources/code-sprite-cli/claude.exe`

找到后通过 `ClaudeAgentOptions(cli_path=...)` 显式传给 SDK —— 比改 `PATH` 可靠，
因为在 runner 的 spec 加载路径下 `os.environ` 可能已被别处快照覆盖。

## 依赖

```text
pydantic>=2.7
langgraph>=1.0
claude-agent-sdk>=0.1
```

**不需要** `openpyxl`（那是 Agent-1 的 ingest 用）。`claude-agent-sdk` 现在装进依赖：
`mode` 自动跟随时有凭据就会走 sdk，不装就永远退化 heuristic。

### 怎么确认 LLM 到底跑没跑

- 产物 `code-knowledge.secondaryHints` 里有一条 `enrich=<sdk|heuristic|sdk_fallback>; <原因>`
- 产物 `analysis-report` 每票 `localization.notes` 里有 `analyze=<同上>`
- 日志里有 `[agent2] enrich=...` / `[agent3] analyze=...`

SDK 会话还会带账单和终止原因（来自 `ResultMessage`）：

```text
enrich=sdk; turns=17; reason=completed; cost=$0.42
enrich=sdk; turns=24; reason=max_turns; cost=$1.10
enrich=sdk_fallback; no Anthropic credentials in env ...
enrich=heuristic                       # 没凭据/显式 heuristic，不产生费用
```

`reason=max_turns` 说明回合用尽。触顶会尝试从会话文本 / 再问一轮 salvage 收 JSON；仍没有则**保留启发式 baseline**，`partial=true`，`source` 仍是 `sdk`（不是 `sdk_fallback`）。

Agent-2 默认把匹配池票都送进 enrich（启发式 medium 也过，标 `heuristicUnverified` 并降权），按**进 prompt 的票数**定预算：`max_turns = BASE + PER × n`（默认 `6 + 7×n`，n≤16）。`BUGFIX_CARTOGRAPHY_MAX_TURNS` 设成正整数则改为绝对上限；`0`/`unlimited` 不限制。

CodeGraph（`@colbymchenry/codegraph`）默认开启：workDir 已有 `.codegraph/` 则挂 MCP；没有则 `codegraph init -y` 再建。`BUGFIX_CODEGRAPH=0` 关掉；`BUGFIX_CODEGRAPH_INIT=0` 只用不自动建。

LangGraph 运行输入可通过 `agent3_mcp_tools` 声明本次授权的业务 MCP 工具，例如 `["mcp__business_docs__search"]`。Agent 3 从 `work_dir` 和已发现业务仓根的 `.mcp.json` 读取对应服务器定义。当前运行只授权列出的工具，服务器名须在这些仓根中唯一。stdio 服务器从其配置所在的仓根启动，改码时使用对应的隔离副本。`BUGFIX_CODEGRAPH=0` 只关闭 CodeGraph，业务 MCP 授权和 Skill 注入照常生效。批准工具前请确认自己信任该仓内的服务器命令或地址。

`enrich=sdk_fallback` 只表示 LLM 没跑成：缺凭据 / 没装 `claude-agent-sdk` / 进程崩溃 / 成功结束但 JSON 不合契约。

## 用 LangGraph Server / CLI 直接调用（不走 Nexas）

`langgraph.json` 把图 id `three_agent` 映射到父图，供 `langgraph dev` / Studio 使用。
那条路径下输入是完整 state：

```json
{
  "work_dir": "/repos",
  "product_line": "PJ14PD20260423284",
  "posture": "beta",
  "defect_batch": "<defect-batch.json 的内容或路径>",
  "open_mr": false,
  "apply_fix": false
}
```

`defect_batch` 必填——`source` 字段已废弃。约束：`skip_agent2` 必须同时 `skip_agent3`。

省略 `artifact_dir` 时，`run` 在 `work_dir/.bugfix-runs/<时间戳>` 下创建本次产物目录。成功后更新 `work_dir/.bugfix-runs/LATEST`，供省略 `artifact_dir` 的 `resume` 使用。生产部署可显式指向可写的持久化目录以保留报告、逐票快照和反馈表。

## 目录

```text
bugfix-agent-platform.zip
├── graph.py                    平台入口（build_graph / graph / main）
├── langgraph.json              three_agent -> ./graph.py:graph
├── requirements.txt            pydantic + langgraph
├── .env / .env.example         模式开关留空，跟平台模型管理走
├── README.md                   本文件
├── bugfix_contracts/           共享契约（与 Agent-1 同一份 schema）
├── bugfix_platform/            agents / workflow / sdk（不含 Agent-1、不含 http/cli）
└── skills/                     平台分析向 skill（Agent-2/3；不含 defect-batch-prepare）
```

## 显式不含的东西

| 不含 | 原因 |
|---|---|
| `bugfix_agent1/` | Agent-1 的 ingest / defect_batch |
| `bugfix_platform/http/` | 平台自带 Server，`serve` 子命令用不上 |
| `bugfix_platform/cli.py` | 平台走图，不走 CLI |
| `defect-batch-prepare` skill | Agent-1 的 skill，与图无关 |
| `docs/` `tests/` `test/` | 不参与运行 |

## 注意

- **不要**在 `graph.py` 或 `langgraph_app.py` 里挂 `InMemorySaver`——持久化由平台负责
- 改了 `platform/bugfix_platform/workflow/graph.py` 后必须重新打包，平台不会自动跟随

## 重新打包

```bash
python packaging/build.py platform
```
