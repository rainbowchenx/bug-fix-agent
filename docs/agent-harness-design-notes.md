# pi 的 Agent / Harness 设计分析

面向 agent 框架作者与 harness 设计者的可借鉴点整理。

**范围**：`packages/coding-agent`（面向用户的 agent）、`packages/agent`（turn loop）、`packages/ai`（provider 层）、`packages/durable`（持久化 harness）、`packages/tui`（终端渲染）。

**前提**：仓库里没有 benchmark 数据（`packages/evals` 只有文档类 eval 与 smoke），本文不主张任何"解决率更高"的量化结论。这里讨论的是**具体机制**，它们降低的是**已知失败模式的概率**，代码位置可逐一核对。

---

## 一、总体判断

pi 的设计取舍可以概括成一句话：

> 把 agent 的可靠性问题，尽量下沉成**协议、类型和状态机**问题，而不是靠 prompt 里多写几句"请注意"。

具体表现为三条主线：

1. **工具契约自带约束**——让模型在结构上难以产出无效编辑/无效读取。
2. **失败被分类，而不是被抛出**——每类错误都有明确的恢复路径或明确的终止理由。
3. **上下文是可增量修补的结构**——system prompt、工具集、压缩摘要都以"可 diff、可重放"的形式存在。

`durable` 是同一思路的极端形态：把"一次 run"建模成持久化任务树，让进程可在任意时刻死亡。

---

## 二、分层与职责边界

```
tui / telemetry / codemode / mcp     无业务含义的叶子
ai                                   provider（身份+认证+目录） / api（线协议） / Models（路由）
agent                                无状态的 turn loop，不认识任何 provider
coding-agent                         组装：CLI、会话、工具、扩展、压缩
durable                              持久化任务 harness（独立实验栈）
```

**可借鉴点 0：把"provider"和"wire API"拆成两个正交概念。**

`packages/ai` 里：

- **Provider**（`src/providers/*.ts`）负责身份、认证方式、模型目录。
- **API**（`src/api/*.ts`）负责线协议（`anthropic-messages`、`openai-completions`、`openai-responses`、`google-generative-ai`、`bedrock-converse-stream`…）。
- **`Models`** 是路由层，负责把请求交给拥有该模型的 provider 并解析认证。

多数 agent 框架把三者揉成一个 `LLMClient`，结果每接一个新网关就要复制一份实现。拆开后，OpenRouter / Groq / Cerebras / xAI 共用一个 `openai-completions` 实现，只在 `compat` 上打补丁（`packages/ai/README.md` 的 OpenAI Compatibility Settings 一节列了 20 多个兼容开关）。

**可借鉴点 0.1：入口按 bundle 成本切分，并用工具守住。**

根入口 `@earendil-works/pi-ai` 是"core only、无副作用"：不含生成目录、不含 provider 工厂、不含 OAuth。provider 在 `/providers/*`，API 在 `/api/*`，旧全局 API 在 `/compat`。

`scripts/check-entry-graphs.mjs` 为每个公开入口维护 **文件数预算 + forbid 列表**，比如 `./models` 最多 20 个文件且禁止到达 `providers/`、`models.generated.ts`。一条误加的 `export *` 会在 CI 失败，而不是等到用户抱怨启动慢。

> 借鉴：如果你的框架对外暴露多个入口，把"入口膨胀"变成可执行的断言，而不是 code review 里的口头约定。

---

## 三、工具设计：让错误在结构上难以发生

### 3.1 edit：多段精确替换，而不是行号或整文件重写

`packages/coding-agent/src/core/tools/edit.ts`

- 一次调用带 `edits[]`，每段 `oldText` **必须在原文中唯一且互不重叠**（`edit.ts:23-30`）。
- schema 描述里直接写清："每段都针对**原始文件**匹配，不是增量应用；不要产生重叠或嵌套编辑；相邻改动合并成一段"。
- 系统提示规则补了两条容易犯的错："不要用大段未改内容做锚点"、"同一文件多处改动用一次调用"（`edit.ts:43-51`）。

**为什么重要**：agent 编辑失败的头号原因是"定位漂移"。行号在多次编辑后失效；整文件重写会丢内容；而"唯一字符串匹配 + 互不重叠"把定位问题变成了**可验证的不变量**——匹配不上就报错，匹配上多处也报错，不会静默改错位置。

实现层的三个细节：

- `splitBom()` / `detectLineEnding()` / `restoreLineEndings()`（`edit.ts:190-197`）：保留 BOM 和原始行尾。否则一次编辑就把整个文件的 CRLF 改成 LF，diff 爆炸且可能破坏脚本。
- `prepareArguments()`（`edit.ts:103-134`）：接受模型常见的畸形输入——`edits` 传成 JSON 字符串、传单个对象而非数组、甚至传旧版的顶层 `oldText/newText`。**在 schema 校验之前做修复**，而不是直接判错重来。
- `constrainedSampling: { type: 'json_schema', strict: 'prefer' }`：provider 支持时用服务端 strict schema，不支持时优雅回退（`strict: 'require'` 才强制失败）。

**可借鉴**：
1. 编辑工具的参数设计要能表达"多处、非交互、基于原文"的意图。
2. 参数修复（`prepareArguments`）应该是一个独立的、可测试的环节，不要混在 execute 里。
3. 编码细节（BOM/行尾）不是小事，它决定了 diff 是否可读、review 是否可能。

### 3.2 read：截断必须自带下一步

`core/tools/read.ts`

- 双限截断（2000 行 / 50KB，先到者为准）。
- 截断后输出**可执行指令**而不是空话：

  ```
  [Showing lines 1-2000 of 5432. Use offset=2001 to continue.]
  ```

- 首行本身超限时，直接给出可复制执行的命令：

  ```
  [Line 200 is 120.0KB, exceeds 50.0KB limit. Use bash: sed -n '200p' file | head -c 51200]
  ```

  （`read.ts:179-193`）

**可借鉴**：截断的边界是 agent 最容易卡住的地方。把"如何取到剩余部分"直接编码进返回值，比在系统提示里写"如果文件很长请分页读取"有效得多——提示只在启动时被读一次，返回值会被模型立刻消费。

### 3.3 bash：模型看摘要，文件存全文

`core/tools/bash.ts`

模型侧输出截断到 50KB，但**完整输出写入临时文件**，路径随结果返回（`full_output_path`，`bash.ts:59-71`）。`OutputAccumulator`（`core/tools/output-accumulator.ts`）用流式 UTF-8 解码器只保留尾巴做展示，同时把全量落盘，内存有界。

**可借鉴**："丢弃"和"卸载"是两件事。多数工具在超限时直接截断并丢失信息；正确做法是**截断展示 + 保留句柄**，让模型能二次精确检索。

### 3.4 图片：按模型能力裁剪，而不是无条件塞入

`read.ts:132-152`：按 `ctx?.model?.inputLimits?.images?.resize` 做尺寸适配；非 vision 模型明确返回一句"[当前模型不支持图片，这张图会从请求中省略]"。

**可借鉴**：能力差异要在工具层处理，不要让 provider 层静默丢弃——静默丢弃会让模型困惑"为什么我看不到"。

### 3.5 工具暴露分级

`core/extensions/types.ts:516`：

```ts
type ToolExposure = "direct" | "model-only" | "codemode" | "deferred" | "hidden";
```

- `direct`：标准声明给模型。
- `deferred`：不在请求里声明，通过 `tool_search` 加载后声明（`extensions/tool-search/tool.ts`，BM25 排序，默认返回 8 条）。
- `codemode`：只能被 codemode 脚本调用，不进模型上下文。
- `hidden`：只能被其他工具间接调用。

加载动作会被记进 transcript（作为工具变更），所以 `/tree`、resume、fork 之后工具集自洽。

**可借鉴**：工具数量是上下文预算与选择准确率的一对矛盾。与其二选一，不如引入"声明层 / 可发现层 / 程序调用层"三档，并按需提升。

### 3.6 嵌套工具调用

`core/nested-tool-calls.ts`

工具可以在执行过程中调 `ctx.executeTool()` 调别的工具（codemode 的核心用法）。pi 的处理：

- 嵌套调用走完整的工具管线（hooks、事件、校验），事件带 `parentToolCallId`；
- 记录有硬上限：`maxCalls: 256`、单次参数 8KB、总参数 32KB、错误文本 500 字符（`NESTED_CALL_LIMITS`）；
- 超限时标记 `complete: false`，而不是静默截断；
- 嵌套消耗的 usage 汇总到父调用的 tool result 上。

**可借鉴**：只要允许"工具调工具"，就必须同时定义**记录的形状和上限**，否则一次脚本调用就能把上下文撑爆。

---

## 四、失败分类：从"抛异常"到"有名有姓的恢复路径"

### 4.1 上下文溢出：20+ 家 provider 的真实措辞

`packages/ai/src/utils/overflow.ts`

`OVERFLOW_PATTERNS` 收录了各家的实际错误文本（Anthropic `prompt is too long`、OpenAI `exceeds the context window`、Google 的 token 数提示、xAI、Groq、OpenRouter、llama.cpp、LM Studio、MiniMax、Kimi、Mistral、z.ai、DashScope、Ollama……），并且有 `NON_OVERFLOW_PATTERNS` 排除误判——Bedrock 的 `ThrottlingException: Too many tokens, please wait` 长得像溢出，实际是限流。

**可借鉴**：多 provider 场景下，错误分类不是"锦上添花"，而是决定能否自动恢复的前提。把它做成一个集中、可穷举、可单测的表，比散落在各 adapter 的 `if (err.includes(...))` 可靠得多。

### 4.2 截断响应的工具调用一律作废

`packages/agent/src/agent-loop.ts:488-520`

关键洞察写在注释里：流式 tool call 的参数是"best-effort JSON salvage"解析出来的，一个被 output limit 截断的响应**可能产生语法合法但内容残缺的参数**。

pi 的选择是：全部不执行，逐个返回错误结果：

> `Tool call "edit" was not executed: the response hit the output token limit, so its arguments may be truncated. Re-issue the tool call with complete arguments.`

**可借鉴**：这是最容易被忽略的静默损坏来源。判定规则很简单——`stopReason === "length"` 时，本轮的 tool call 全部不可信。宁可让模型重发。

### 4.3 一次性的"截断但未达上限"救援

`overflow.ts:184`：

```ts
isRecoverableLength(message, desiredMaxOutput)
  = stopReason === "length" && desiredMaxOutput > 0 && usage.output < desiredMaxOutput
```

`stopReason === "length"` 但输出远没到 `max_tokens`，说明是上下文压力导致的截断，而不是模型主动停。`agent-session.ts:3068` 对它做**一次** compact-and-retry，并用 `_overflowRecoveryAttempted` 记录，保证不进入循环。

**可借鉴**：区分"合法结束"和"被环境压停"。并且救援必须**有次数上限**——恢复机制最常见的失败方式是自己变成死循环。

### 4.4 重试策略要区分"可重试"与"注定失败"

`packages/ai/src/utils/retry.ts`

- 可重试：`overloaded`、`rate limit`、`429/5xx`、`upstream returned error`、`socket hang up`、`terminated`、WebSocket 关闭、SDK 提前断流、各类网关转发失败。
- **明确不可重试**：`insufficient_quota`、`out of budget`、`billing`、`GoUsageLimitError`、`Monthly usage limit reached`、ChatGPT Business 的 workspace limit。

指数退避 `baseDelayMs * 2^(attempt-1)`，`maxAgentDelayMs` 封顶，`retryAssistantCall()` 统一包裹。

**可借鉴**：把"不可重试"当成一等公民显式列举。重试一个配额错误三次的代价不只是时间，还会把失败文本写进后续上下文。

### 4.5 provider 流式错误的统一出口

`packages/ai` 的约定是：请求返回流之后**永不 throw**，错误以 `error` 事件 + 最终消息的 `stopReason/errorMessage` 表达。唯一同步 throw 的情况是直接调用 API 实现且缺少认证。

**可借鉴**：把"失败"编码进返回值而不是异常，会让上层循环（尤其是持久化/可恢复的循环）简单一个数量级——异常会穿透并丢失上下文。

---

## 五、上下文与 Prompt：可 diff 的结构，而不是一整块字符串

### 5.1 分节 system prompt + 增量 patch

`core/system-prompt.ts`

prompt 被拆成命名 section：`preamble / tools / rules / docs / project_context / skills / cwd / 自定义`。除 `preamble` 外每节用同名 XML 标签包裹。

`diffSystemPromptSections(previous, current)`（`system-prompt.ts:217`）只输出变化的 section，作为一条 `SystemMessage.sections` patch 追加进 transcript。

三个收益：

1. **中途切模型/加工具/加载 skill 不必重发整段 prompt**；
2. 只改一节不会击穿其余部分的 provider prompt cache；
3. `getCurrentSystemMessage()` 能从 transcript 重放出任意时刻的完整 prompt（`ai/src/utils/transcript.ts`），所以 fork / 回滚后状态自洽。

**可借鉴**：如果你的 agent 支持"运行中改变行为"（换模型、加工具、载技能），把 prompt 建模成 **{ key → text } 的集合 + 差分**，而不是一个字符串。

### 5.2 工具集也是 transcript 的一部分

工具变更以 `toolsAdded` / `toolsRemoved` 声明在 system message 上，`getCurrentTools()` 重放。回退到某个分支时，工具集自动跟着回退。

`resolveTranscript()`（`transcript.ts`）处理 provider 差异：支持会话中途 system message 的 provider 保留原样，不支持的用 `collapseSystemMessages()` 把后续 system message 折叠进开头。

**可借鉴**：凡是"会随时间变化、又必须能回滚"的状态，都放进 transcript，不要放在进程内存里。

### 5.3 skill：只声明元数据，正文按需读

`core/skills.ts:358-387`

系统提示里每个 skill 只放三行：

```xml
<skill>
  <name>…</name>
  <description>…</description>
  <location>…/SKILL.md</location>
</skill>
```

正文等模型判断匹配后用 `read` 加载。附带一句最容易出错的说明："skill 里的相对路径要基于 skill 目录解析"。`disable-model-invocation` 的 skill 不展示。

**可借鉴**：这是"能力数量"与"上下文成本"解耦的标准做法。注意两个工程细节：**必须给出绝对位置**（否则模型会相对 cwd 解析），**必须说明相对路径规则**。

### 5.4 压缩：结构化交接文档 + 增量更新

`core/compaction/compaction.ts:507`

摘要格式固定为六段：

```
## Goal
## Constraints & Preferences
## Progress (### Done / ### In Progress / ### Blocked)
## Key Decisions
## Next Steps
## Critical Context
```

第二次及以后的压缩走 `UPDATE_SUMMARIZATION_PROMPT`：**保留旧信息、追加新进度、把 In Progress 挪到 Done**，而不是重新总结。

其余四个决定质量的细节：

- **额外的机器可读清单**：`computeFileLists()` 维护"只读过 / 修改过"的文件集，以 `<read-files>` / `<modified-files>` 附在摘要后（`compaction/utils.ts:67-87`）。这决定了压缩后模型还知不知道"我改过哪些文件"。
- **序列化时去掉 thinking**：只保留 user 文本、assistant 文本、tool call、tool result（后者截到 2000 字符）。注释给出了理由——回放的 thinking 常常不在模型活跃上下文里（签名不匹配会被丢弃），塞进去可能让"摘要请求"比"被摘要的上下文"还大（`utils.ts:113-119`）。
- **不切断 turn**：`isSplitTurn` / `turnStartIndex` / `findTurnStartIndex`（`compaction.ts:480-500`）。切点落在 tool call 与 tool result 之间时，把整个 turn 挪进摘要，避免产生孤立的 tool result。
- **摘要请求不写缓存**：`cacheRetention: "none"`，一次性请求不污染 prompt cache。

**可借鉴**：压缩不是"总结一下"，而是一次**带 schema 的交接**。三个必须回答的问题：目标是什么、做到哪了、手里有哪些文件/命令/错误原文。后两条靠机器提取，不能指望模型自己记得。

### 5.5 会话是可分支的树

`core/session-manager.ts` + `docs/session-format.md`

每条 entry 有 `id` / `parentId`，同一个 JSONL 文件内形成树；`head` 标记决定活跃区间。

配套的 `branch-summarization.ts`：把被放弃的分支总结成一段上下文带回主线。

**可借鉴**："从 20 步前换个思路重来"应该是廉价操作。多数 agent 只能新建会话，代价是丢掉全部上下文；树形 session + 分支摘要让"试错"变成可承受的策略。

---

## 六、工具执行调度

`packages/agent/src/agent-loop.ts:520-530`

```ts
if (config.toolExecution === "sequential" || hasSequentialToolCall) {
  return executeToolCallsSequential(...);
}
return executeToolCallsParallel(...);
```

默认并行，但语义是精心定义的：

- **预检顺序执行**（解析、校验、`beforeToolCall` 钩子）——保证决策顺序确定；
- **执行并发**；
- **结果按 assistant 源顺序落盘**——持久化顺序与模型看到的顺序一致；
- 批内只要有任一工具声明 `executionMode: "sequential"`，**整批退化**为串行。

配套 `withFileMutationQueue(absolutePath, ...)`（`edit.ts:163`）：按路径排队，同一文件的并发编辑不会互相覆盖；并且 abort 检查放在每次 `await` 之后而不是 abort 事件里，避免"队列已释放但写入还在进行"。

**可借鉴**：
1. 并行与顺序的粒度是"批"，不是"工具"。用"任一 sequential → 整批 sequential"换确定性。
2. 预检和执行分离：预检可以顺序，副作用才需要并行。
3. 按资源（文件路径）加锁，而不是全局锁。

---

## 七、人在环：中途纠偏通道

`AgentSession` 提供两条队列（`core/agent-session.ts`，`steeringMode` / `followUpMode`）：

- `steer()`：插在当前 assistant turn 和它的 tool call 之后、下一次请求之前。
- `followUp()`：等当前 run 的全部待办做完再进来。

对应的 agent-core 语义（`packages/agent/README.md`）：steering 在当前轮工具全部完成后注入；follow-up 只在没有 tool call、也没有 steering 时才检查。

**可借鉴**：长任务失败的主因往往不是"单步错"，而是"错误方向跑了 20 步"。能中途插一句话的收益，通常大于任何单点 prompt 优化。设计时要把"立即打断"和"排在后面"区分开——两者混用会让用户不知道自己的输入去哪了。

---

## 八、扩展机制

`core/extensions/` + `src/extensions/index.ts`

- 扩展是 TypeScript 模块，用 `jiti` 直接加载，**不需要预编译**。
- 工厂函数注册 tool / command / shortcut / provider / hook / renderer / UI。
- 内置扩展（`codemode`、`tool-search`、`mcp`、`llama.cpp`）标记 `replaceable`：第三方扩展注册同名工具/命令时**接管**，而不是冲突报错。
- 生命周期约束写得很明确：不要在工厂里起进程/定时器，`session_start` 起、`session_shutdown` 关（`docs/extensions.md`）。

**可借鉴**：
1. 内置能力用"和第三方扩展同一套 API"实现，是保持扩展点真实的唯一方式。
2. `replaceable` 语义比"禁止重名"更友好——它允许用户用自己的实现替换内置行为。
3. 在文档里显式规定生命周期，比让作者从源码推断要省事得多。

---

## 九、durable harness：把可靠性做成状态机

这一节的参考价值对 **harness 设计者** 最高。

### 9.1 三层职责

```
Harness       会话句柄、提交入口、inbox、用量、任务图
  └ TaskScheduler   谁该跑、跑到哪、谁拥有谁
      └ Session     唯一变更线 + 事务 + 文档缓存
          └ Storage memory / SQLite / JSONL / IndexedDB
```

### 9.2 唯一变更线

`session.ts`：所有 commit 和需要一致性的读都 `#enqueue` 到同一条 promise 链上。Storage 不需要自己的互斥；所有"决策"都在线上串行发生。

**可借鉴**：分布式/持久化系统里，"让所有状态转换通过一条线"能消掉大量竞态。代价是线上不能做慢操作——所以规则必须显式写出来（见 9.7）。

### 9.3 Effect sandwich

```
commit 意图（写 checkpoint）
执行外部副作用（网络、进程）
commit 结果或下一 phase
```

崩溃发生在第二步之后，重开时该 phase 会重跑。所以副作用必须满足三者之一：**幂等**、**可轮询的句柄**、**显式记为 interrupted**。

pi 的实现里，deferred 模型响应就有一个专门的 `poll` phase（`harness/generation.ts`）；工具执行前先 commit `{ phase: "execute", arguments, replay: "safe" | "unsafe" }`（`harness/tool.ts`），重开时只有 `replay === "safe"` 才重跑，否则返回"可能已部分执行"。

**可借鉴**：这是让 agent 可恢复的**唯一**通用解。任何"调用外部世界"的地方都要先问：这一步崩了，重来时我怎么知道它做没做过？

### 9.4 "没有持久进展"是一种故障

`harness/scheduler.ts` 的 `#decide` 规则：

```
1. 终态/waiting/sleeping → 停
2. Session 正在关闭 → 停
3. 有 abort mark → 结束
4. phase 抛异常 → 写 faulted
5. checkpoint 变了 → 刷新 registry，必要时 handover
6. checkpoint 没变 → 写 faulted（"没有持久进展"）
```

规则 6 值得单独抄下来：它把"handler 忘了 commit"从静默死循环变成可观测的故障。

**可借鉴**：给状态机加一条"每步必须推进"的断言。

### 9.5 所有权树 + 有界索引

任务和会话构成一棵树：task 的父是 owner task 或 conversation。向上走判断取消是否传播，向下走判断 owner 何时能终结（`completing` → 等 owned work 结束 → `terminal`）。

关键工程细节（`scheduler.ts:244`）：**索引只保留活工作周围的链路**，超出范围就丢弃，需要时从 storage 重建。所以内存随"活跃工作"而非"历史总量"增长。

**可借鉴**：取消/等待这类关系容易做成全量图。做成"只保留热区"的有界索引，能同时解决内存和恢复两个问题。

### 9.6 重启上限与 park

`restartLimit`（默认 5）：连续被崩溃切断且状态未变的任务会被 park（`task_parked`），需要显式 `retryTask()` 才继续。

**可借鉴**：恢复机制必须能识别"毒任务"。无限重启一个必然崩溃的任务，比直接失败更糟。

### 9.7 失败语义的集中定义

- **任何 Storage 错误都终结 Session**（`GuardedStorage`，`session.ts:961`）。不重试、不降级，宿主必须重开。理由：一次失败的 commit 后，"到底提交没提交"是未知的。
- 重试是 Storage 自己的责任（瞬时错误在方法内部重试）。
- 不可恢复的失败通过 `SessionFailed` 广播给所有在途调用。

**可借鉴**："一类错误一个策略"要写在文档里（pi 的 `spec.md §10.1`），而不是让每个调用点自己判断。

### 9.8 关闭协议

`close()` 的顺序是：**先 seal admission** → 通知 close listener → 等已接纳的 commit 落盘 → join 所有 invocation → 关闭 Storage。关闭期间不写 task outcome，而是把被停下的任务**直接写成 `pending` 落盘**（`writeAtClose()`，`session.ts:559`）。

**可借鉴**：优雅关闭最难的是"在途工作的归属"。pi 的答案很干脆——不假装完成，退回 pending，下次重开自然重跑。

### 9.9 生命周期交给宿主

`onWake` / `Wake { active, at? }`：harness 不假设自己有定时器。宿主可以把它映射到 Durable Object alarm、cron、或进程内 timer；在 Cloudflare Workers 这种不能持有定时器的环境里，默认就不持有。

**可借鉴**：把"什么时候需要有人叫醒我"抽象成一个可查询的值，而不是内部 `setTimeout`。这让同一套 harness 能跑在长驻进程和无状态函数两种环境。

### 9.10 内存缓存的有界与可弃

Session 的文档缓存按"最后一次读写的保留期"淘汰，被 watch / documentState 观察的文档永不淘汰。淘汰作为任务排在变更线上，保证"没有事务持有正在离开的 tracker"。宿主拒绝后台定时器时（Workers），退化为"每次 commit 结束时清理过期项"。

**可借鉴**：缓存淘汰策略要能在"没有时钟"的环境下退化，而不是依赖 `setTimeout` 一定可用。

---

## 十、成本与缓存（间接影响长任务完成率）

`core/cache-warmer.ts`

- 用会话自身的使用数据估计"60 分钟内是否会有下一次请求"（`IDLE_CONTINUATION_PROBABILITY = 0.15`）；
- 只有当**期望节省 ≥ $0.05** 时才发一次单 token 刷新请求，续上 prompt cache；
- `isReplayable()` 专门处理特例：Anthropic 的 budget-based thinking 会把 `max_tokens` 编进 cache key，这类模型**不刷新**——否则刷新请求本身会打出另一个 cache entry，反而更贵。

配合 5.1 的 section diff，长会话的 cache 命中率能维持住。

**可借鉴**：缓存策略要**按 provider 特性分叉**，并且要有"值不值得刷"的显式判据，而不是无脑续期。

---

## 十一、可观测性

- Session 事件覆盖 `message_update`、`tool_execution_*`、`queue_update`、`compaction_*`、`auto_retry_*`、`summarization_retry_*`。`agent_end` 表示一次低层 run 结束，`agent_settled` 才表示"不会再有自动续跑"（`docs/sdk.md`）。
- telemetry 是**显式传入的 span**，不是全局 current-span，且明确不记录 prompt / 生成文本 / 工具参数（`packages/ai/README.md` Telemetry 一节）。
- durable 的每个 phase 都开一个 `pi.durable.phase` span，属性含 `task.id`、`phase`、`resumed`、`outcome`。

**可借鉴**：
1. "run 结束"和"真的不会再有动作"要分成两个事件，否则宿主无法判断何时可以回收资源。
2. 遥测的默认策略应该是"记录形状，不记录内容"——避免把用户代码写进日志。

---

## 十二、值得抄的清单（按投入产出排序）

| # | 做法 | 位置 | 解决什么 |
|---|---|---|---|
| 1 | 编辑工具用"唯一、非重叠的原文匹配"，并显式告知匹配语义 | `tools/edit.ts` | 编辑定位漂移、静默改错位置 |
| 2 | 截断输出自带"如何继续"的可执行指令 | `tools/read.ts` | 大文件读取卡死 |
| 3 | 超限输出落盘并返回路径 | `tools/bash.ts` | 信息丢失 |
| 4 | 截断响应的 tool call 全部作废并说明原因 | `agent-loop.ts` | 半截参数导致的静默损坏 |
| 5 | 溢出错误按 provider 措辞分类，并排除误判 | `ai/utils/overflow.ts` | 能否自动压缩恢复 |
| 6 | 重试白名单 + 明确的不可重试清单 | `ai/utils/retry.ts` | 无效重试、污染上下文 |
| 7 | 压缩用固定 schema，第二次起用增量更新 | `compaction/compaction.ts` | 长任务丢失目标与状态 |
| 8 | 压缩摘要附机器提取的文件清单 | `compaction/utils.ts` | 压缩后不知道改过哪些文件 |
| 9 | system prompt 分节 + 差分 patch | `system-prompt.ts` | 改一处打穿整个 prompt cache |
| 10 | 工具集与 prompt 变更记入 transcript | `ai/utils/transcript.ts` | 回滚 / fork 后状态不一致 |
| 11 | 工具暴露三档（直接 / 可发现 / 程序调用） | `extensions/types.ts` | 工具数量与上下文预算的矛盾 |
| 12 | 批级并行 + 任一 sequential 则整批串行 | `agent-loop.ts` | 并发正确性与速度 |
| 13 | 按路径加锁的写队列 | `tools/file-mutation-queue.ts` | 同文件并发写互相覆盖 |
| 14 | steering / followUp 双队列 | `core/agent-session.ts` | 长任务方向错误 |
| 15 | 树形 session + 分支摘要 | `session-manager.ts` | 试错成本过高 |
| 16 | durable：effect sandwich + checkpoint 推进断言 | `durable/harness/*` | 进程崩溃后的可恢复性 |
| 17 | durable：有界所有权索引 | `scheduler.ts:231-252` | 内存随历史无限增长 |
| 18 | durable：restart limit + park | `scheduler.ts` | 毒任务无限重启 |
| 19 | durable：close 时把在途任务退回 pending | `session.ts:559` | 关闭语义含糊 |
| 20 | durable：Wake 抽象交给宿主 | `harness/types.ts` | 同一 harness 跨运行环境 |

---

## 十三、不建议照搬的部分

诚实地说，pi 有几处取舍是有代价的，复制前要评估：

1. **核心刻意最小**：没有 subagent、没有 plan mode（README 明说）。这些都要靠扩展补。如果你的产品需要多 agent 协作，直接照搬会缺一大块，而自己写扩展的成本不低。
2. **`compat` 入口是技术债**：`ai/src/compat.ts` 的注释明确写着等 coding-agent 的 `ModelManager` 迁移完成就删。新代码应该用 `createModels()` + provider 工厂，但现有文件混用两种 import 风格，读代码时需要留意。
3. **durable 是 experimental**：API 不保证稳定，且和 coding-agent 是两套互不依赖的实现。想同时得到"durable 的可恢复性"和"coding-agent 的成熟度"是不存在的，需要自己接。
4. **强单线程语义**：唯一变更线 + 同步 commit listener 让很多问题消失，但也意味着线上不能做慢操作。`spec.md §12` 用一整节列"API footguns"（长事务、commit 内读、detached draft…），说明这套模型的认知负担不低。
5. **错误分类依赖字符串匹配**：20+ 条正则维护成本高，provider 改文案就会漏判。它是"目前最优可行"而非"优雅解"。
6. **工具截断阈值是经验值**：2000 行 / 50KB / 8 条搜索结果 / 256 个嵌套调用，都是拍出来的数字，换领域需要重新标定。

---

## 十四、如果只记三条

1. **让错误在结构上难以发生，而不是在提示里提醒。** 编辑用唯一原文匹配、截断给下一步、并行按资源加锁——这些都是类型和协议层面的约束。
2. **把失败分类成有名字的路径。** 溢出、限流、配额、截断、崩溃各有各的处理，并且每种都有明确的上限和终止条件。
3. **上下文是结构，不是字符串。** 分节 prompt、可回溯的工具集、带 schema 的压缩摘要、树形 session——四项共同保证"长任务不会越跑越糊涂"。

至于 durable：如果目标环境会崩溃、会驱逐、会重启，那 effect sandwich + checkpoint 驱动是目前唯一可靠的通用方案，代价是你必须为每个副作用回答"重来时我怎么知道它做没做过"。
