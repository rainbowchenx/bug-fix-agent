# LangGraph POC - BugFix Agent

这是将 BugFix Agent 改造为 LangGraph 的概念验证（POC）实现。

## 文件结构

```
src/langgraph-poc/
├── README.md          # 本文件
├── graph.ts           # LangGraph StateGraph定义
├── runner.ts          # 运行器和统一接口
└── example.ts         # 使用示例（待创建）
```

## 核心概念

### 状态（State）

LangGraph使用统一的状态对象在节点间流转：

```typescript
interface BugfixAgentState {
  // 输入
  runId: string;
  workDir: string;
  defects: Defect[];
  
  // 处理状态
  clusters: Cluster[];
  currentClusterIndex: number;
  rootCause?: RootCauseArtifact;
  solution?: SolutionArtifact;
  
  // 输出
  fixed: FixedCluster[];
  unfixed: UnfixedCluster[];
  report?: RunReport;
}
```

### 图结构（Graph）

工作流被建模为有向图（DAG），每个pipeline阶段是一个节点：

```
START → normalize → aggregate → prepare_cluster → ...
                                       ↓
                                    analyze
                                    ↙    ↘
                            unfixed?    fixable?
                                ↓         ↓
                          add_unfixed  implement
                                         ↓
                                    static_check
                                         ↓
                                      verify
                                    ↙      ↘
                              failed?    passed?
                                ↓          ↓
                            classify    review/deliver
```

### 节点（Nodes）

每个节点是一个纯函数，接收state，返回部分state的更新：

```typescript
const analyzeNode = async (state: BugfixAgentState) => {
  const result = await analyzeCluster({...});
  return {
    rootCause: result.rootCause,
    solution: result.solution
  };
};
```

### 条件边（Conditional Edges）

根据state决定下一个节点：

```typescript
workflow.addConditionalEdges(
  "analyze",
  (state) => {
    if (state.stopReason) return "add_unfixed";
    return "prepare_repo";
  },
  {
    "prepare_repo": "prepare_repo",
    "add_unfixed": "add_unfixed"
  }
);
```

## 与原始实现的对比

| 特性 | 原始实现（Claude SDK） | LangGraph POC |
|-----|---------------------|--------------|
| **流程控制** | while循环 + if分支 | 声明式图结构 |
| **状态管理** | 函数参数传递 + 文件系统 | 统一State对象 |
| **可视化** | 无，需读代码 | LangGraph Studio |
| **断点恢复** | 需自己实现 | 内建checkpointing |
| **并行执行** | 串行 | 可用ParallelNode |
| **监控追踪** | 自定义日志 | LangSmith集成 |

## 快速开始

### 1. 安装依赖

```bash
npm install @langchain/core @langchain/langgraph @langchain/anthropic
```

### 2. 使用LangGraph引擎

```typescript
import { runBugfixGraph } from "./langgraph-poc/graph.js";

const report = await runBugfixGraph({
  runId: "test-123",
  workDir: "/tmp/work",
  defects: [
    {
      id: "1",
      title: "Null pointer exception",
      repoUrl: "https://gitlab.com/org/repo.git"
    }
  ],
  options: {
    maxIterate: 3
  }
});

console.log(report);
```

### 3. 通过统一接口（兼容模式）

```typescript
import { runPipelineUnified } from "./langgraph-poc/runner.js";

// 使用LangGraph
const report1 = await runPipelineUnified(
  "/tmp/work",
  "run-1",
  { engine: "langgraph" }
);

// 使用原始Claude SDK（向后兼容）
const report2 = await runPipelineUnified(
  "/tmp/work",
  "run-2",
  { engine: "claude-sdk" }
);
```

### 4. HTTP API集成

修改 `src/http/app.ts`：

```typescript
app.post("/v1/runs", async (c) => {
  const body = await c.req.json();
  const request = parseCreateRunRequest(body);
  const runId = crypto.randomUUID();
  
  await initRun(request.workDir, runId, request);
  
  // 支持通过options.engine选择引擎
  const engine = request.options?.engine ?? "langgraph";
  enqueueRunUnified(request.workDir, runId, { engine });
  
  return c.json({ runId }, 202);
});
```

客户端请求：

```json
POST /v1/runs
{
  "workDir": "/tmp/batch/today",
  "defects": [...],
  "options": {
    "engine": "langgraph",
    "maxIterate": 3
  }
}
```

## 可视化调试

使用 LangGraph Studio（需安装）：

```bash
# 启动LangGraph Studio
langgraph dev

# 在浏览器中打开
# http://localhost:8123
```

在Studio中可以：
- 查看完整的图结构
- 单步执行节点
- 查看每个节点的输入输出state
- 设置断点
- 时间旅行调试

## 性能优势

### 1. 并行处理Clusters

原始实现串行处理：

```typescript
for (let i = 0; i < clusters.length; i++) {
  const outcome = await processCluster(clusters[i]);
  // ...
}
```

LangGraph可以并行：

```typescript
// 修改图结构，添加map_clusters节点
workflow.addNode("map_clusters", async (state) => {
  const results = await Promise.all(
    state.clusters.map(cluster => 
      processOneCluster({ ...state, currentCluster: cluster })
    )
  );
  return {
    fixed: results.flatMap(r => r.fixed ?? []),
    unfixed: results.flatMap(r => r.unfixed ?? [])
  };
});
```

### 2. 智能缓存

LangGraph可以缓存节点结果，避免重复执行：

```typescript
const graph = workflow.compile({
  checkpointer: new MemorySaver(),
  // 如果analyze结果相同，可以跳过
});
```

### 3. 增量恢复

如果某个cluster失败，可以从断点恢复：

```typescript
// 保存checkpoint
const checkpoint = await graph.getState(threadId);

// 失败后从checkpoint恢复
await graph.invoke(initialState, {
  configurable: { thread_id: threadId }
});
```

## Claude SDK集成保持

**关键设计**：LangGraph是编排层，Claude SDK是执行层

在每个需要LLM的节点中，仍然调用Claude Agent SDK：

```typescript
const analyzeNode = async (state: BugfixAgentState) => {
  // 方式1：继续使用Claude Agent SDK
  const { runAgentSession } = await import("../agent/sdk-runner.js");
  const result = await runAgentSession({
    cwd: state.repoPath!,
    prompt: buildAnalyzePrompt({...}),
    mode: "analyze",
    maxTurns: 25
  });
  
  // 或方式2：替换为LangChain的ChatAnthropic
  // const model = new ChatAnthropic({...});
  // const result = await model.invoke(prompt);
  
  return { rootCause, solution };
};
```

**优势**：
- 保留Claude Agent SDK的特殊能力（如`acceptEdits`自动应用编辑）
- 可以逐步迁移到LangChain工具生态
- 灵活选择最适合的工具

## 迁移路径

### 阶段0：当前POC（已完成）
- ✅ 核心StateGraph定义
- ✅ 所有节点实现
- ✅ Conditional edges逻辑
- ✅ 统一Runner接口

### 阶段1：功能验证
- [ ] 创建单元测试
- [ ] 创建集成测试
- [ ] 对比原始实现的输出质量
- [ ] 性能基准测试

### 阶段2：增强功能
- [ ] 添加checkpointing
- [ ] 实现并行cluster处理
- [ ] 集成LangSmith追踪
- [ ] 优化错误处理

### 阶段3：生产发布
- [ ] 更新文档
- [ ] 添加migration guide
- [ ] 默认使用LangGraph
- [ ] 逐步废弃Claude SDK直接调用模式

## 注意事项

1. **依赖版本**：确保使用最新版本的 `@langchain/langgraph` (>= 0.2.0)
2. **内存使用**：State对象会被持久化，注意控制大小
3. **错误处理**：每个节点应该捕获异常并设置`stopReason`
4. **测试覆盖**：重点测试conditional edges的所有分支

## 相关资源

- [LangGraph文档](https://langchain-ai.github.io/langgraph/)
- [LangGraph Studio](https://github.com/langchain-ai/langgraph-studio)
- [LangSmith](https://docs.smith.langchain.com/)
- [完整可行性分析](../../docs/langgraph-feasibility-analysis.md)

## FAQ

**Q: LangGraph会增加多少依赖？**

A: 主要是3个包：`@langchain/core`, `@langchain/langgraph`, `@langchain/anthropic`，总大小约10MB。

**Q: 能否保留Claude SDK？**

A: 可以。LangGraph只是编排层，每个节点内部仍然可以调用Claude SDK。

**Q: 性能会变差吗？**

A: 不会。LangGraph的状态管理开销很小，而且支持并行执行，整体性能会更好。

**Q: 需要改写所有测试吗？**

A: 不需要。HTTP API保持不变，集成测试无需修改。只需为新的节点添加单元测试。

**Q: 如何调试LangGraph？**

A: 使用LangGraph Studio可视化调试，或者添加日志输出每个节点的state变化。
