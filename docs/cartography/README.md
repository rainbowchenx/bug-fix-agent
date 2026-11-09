# 仓型分析 · 索引

Agent-2 第一步是**判仓型**，再按仓型画架构图、做路径软匹配。这份目录记录每一类的
**完整分析**——逐仓走读、结构证据、发现的疑点，判据只是其中一章。

| 文档 | 类型 | 样本 | 状态 |
|---|---|---|---|
| [micro-frontend.md](micro-frontend.md) | `micro_frontend` | hcp（55 子应用）、hct（21 子应用） | ✅ 完整 |
| [device-web.md](device-web.md) | `device_web` | camera（4.5 代）、peitao（5.x/Vue2）、transport（5.x/Vue3） | ✅ 完整 |
| [electron.md](electron.md) | `electron_node` | led（多仓容器：Electron 产品 + 外挂 Koa 服务） | ✅ 完整 |

**为什么按类型分文档**：每类的结构、入口约定、定位难点差异极大（微前端是"多子应用可独立部署"，设备 web 是"单包双端 + 设备能力对象"），混在一份里必然写成四不像。共性部分（实现缺陷、分析方法、评分机制）留在本文。

---

## 1. 分析一个仓的标准流程

每个类型都是按这套走的，后续 electron 沿用：

```text
① 判它"是什么"     package.json / .gitmodules / src 顶层 / 框架依赖
② 判它"怎么部署"   构建配置产物形态：几个包、入口扩展名、是否 UMD
③ 判它"怎么组装"   入口文件 → 注册机制 → 模块清单
④ 判它"怎么跨模块"  全局桥 / 模块导出 / 事件总线（定位失败的真因多在这里）
⑤ 判它"怎么分端"   PC / mobile / APP 是否有独立入口与独立组件树
⑥ 找出反例        同类里"看起来像但其实是另一类"的特征
⑦ 写复验命令      每条结论都要能一条命令重跑
```

第 ⑥ 步是重点：**判据的价值不在于能认出对的，而在于不会认错**。

---

## 2. 跨类型共性结论

### 2.1 框架名永远不是判据

五个真实仓的 `package.json` 里，**三个 `name` 都叫 `simple-single-spa-webpack-example`**
（hcp、hct、camera），因为同出一套内部脚手架。其中两个是微前端，一个是设备 web。

```text
                         single-spa   部署形态              真类
hcp/hcp                  ✓            N 个 UMD 子应用       micro_frontend
hct/hct                  ✓            N 个 UMD 子应用       micro_frontend
camera/camera            ✓            单包 index.asp        device_web
peitao                   ✗            单包 index.asp        device_web
transport                ✗            单包 index.asp        device_web
calibrationtool          ✗            exe + fork 子服务      electron_node
```

**分水岭是部署形态，不是框架**。补充两个同型陷阱：

- `vite-plugin-electron` ≠ Electron 应用（`calibration-subsystem` 只是拿它当 Node 打包器）
- `koa` 依赖 ≠ HTTP 服务端（`calibrationtool/electron` 有 `@types/koa` 但只做 HTTP 客户端，`new Koa` 出现 0 次）

### 2.2 "设备相关"的代码量不能区分任何一类

| 仓 | 真类 | 设备能力文件 | ISAPI 文件 |
|---|---|---|---|
| hcp/hcp | micro_frontend | **128** | **1205** |
| transport | device_web | 64 | 56 |
| camera/camera | device_web | 36 | 37 |
| peitao | device_web | 1 | 15 |

hcp 是**管理设备的平台**，调 ISAPI 比设备自身的界面还多。这条思路比框架名更容易踩坑，
因为它符合直觉。

### 2.3 现在的实现：三类中两类是错的

判型 `agents/cartographer/detect.py:detect_cartography_profile()`，
架构图 `agents/cartographer/architecture.py:_map_*()`。五个真实仓实测：

| 仓 | 真类 | 现有实现判成 | 架构图产出 |
|---|---|---|---|
| hcp/hcp | micro_frontend | ✅ `micro_frontend` | ❌ 空（只有兜底 `mf`） |
| hct/hct | micro_frontend | ✅ `micro_frontend` | ❌ 空 |
| camera/camera | device_web | ❌ **`micro_frontend`（错类）** | ❌ 空 |
| peitao | device_web | ❌ `unknown` | ❌ 空 |
| transport | device_web | ❌ `unknown` | ❌ 空 |
| calibrationtool | electron_node | ✅ `electron_node` | ⚠️ 有产出，但 3 处错（electron.md §6） |
| calibration-subsystem | Node 服务（非 electron） | ✅ `unknown` | — |
| led（容器） | 多仓容器 | ✅ `unknown` | ⚠️ 只给两个 `repo_root`，不递归子仓 |

微前端判对是**运气**（根 `package.json` 恰好有 `single-spa`），设备 web 三仓全错，
electron 判型可用但架构图粒度错。

### 2.4 实现缺陷清单（D1–D9）

判型侧：

| # | 缺陷 | 后果 |
|---|---|---|
| D1 | 循环里 `profile = "electron_node"` 无条件赋值 | 多仓混合时结果取决于目录遍历顺序；另两个分支却有 `if profile == "unknown"` 保护，优先级不自洽 |
| D2 | 微前端只认 `single-spa` / `@single-spa/devtools` | qiankun / wujie / micro-app / Module Federation 全判 `unknown` |
| D3 | `device_web` 靠根目录名匹配 `bridge\|jsbridge\|device-web\|webview` | 命名习惯一变就全错 |
| D8 | 该正则（含 `native-?api`）对 **5 个真实仓命中 0 次** | `device_web` 是死分支，生产上从未产生过这个分类 |
| D9 | `single-spa` 同时是微前端与设备 web（4.5 代）的特征 | 不按部署形态判断必然错类，camera 即证据 |

架构图侧：

| # | 缺陷 | 后果 |
|---|---|---|
| D4 | `discover_repo_roots()` 只扫根 + **深度 1** | submodule 在 `src/<App>`（深度 2）→ hcp 的 55 个子应用全部不可见，`repoRoots` 只有 `['.']` |
| D5 | `SPA_APP = r"(?:^\|/)(?:apps?\|packages?\|micro)/([^/]+)/"` | 该仓用 `src/<App>/`，0 匹配 |
| D6 | `_map_micro_frontend` 用 `if "registerApplication" in f` 判 shell，而 `f` 是**文件路径** | 永远不成立（该字符串在文件**内容**里）→ `entryPoints` 恒空 |
| D7 | `_list_src_rel(limit=400)` | hcp `src/` 下 10330 个源码文件，只看到 3.9%，且按字母序截断（BI/AccessControl/Attendance…） |
| D10 | `ELECTRON_MAIN` 正则里 `(?:electron/)?` 是**可选**前缀 | 任何 `main.ts` / `main.vue` 都命中 → `web/src/main.ts`（Vue 入口）被判成主进程 |
| D11 | `_map_*` 对每个 root 各扫一遍，不去重 | `roots=['.','electron','web']` 时 `electron/electron/main/*` 产出两次（`web:main:main` 重复） |
| D12 | `ELECTRON_RENDERER` 匹配 `src/(renderer\|pages\|views)` 后按遍历顺序取前 5 | renderer 入口变成 5 个随机业务页；真正的入口 `web/src/main.ts` 反被归入 main |
| D13 | `discover_repo_roots` 不递归、不读 `.gitmodules` | `led`（容器）只给两个 `repo_root`，子仓不被分类；hcp 的 55 个 submodule 全不可见（同 D4） |

---

## 3. 判据落码的统一约定

三类共用一套机制，避免又写成一串 `if`：

```text
每个判据 = (名称, 分值, 检查函数, 证据文案)

命中 → 累加分数 + 记录证据（证据要能写进 code-knowledge 的 notes，
                        便于人工复核"为什么判成这样"）

阈值 ≥6  → 定型
冲突     → 按类间优先级仲裁，不按命中顺序
```

类间优先级（由反例倒推）：

```text
device_web      有 src/*.asp 时压过 micro_frontend   ← camera 是判据
electron_node   deps 精确含 electron（vite-plugin-electron 不算）
micro_frontend  有 ≥3 个含 vue.app.js 的 src/ submodule
unknown         都未达阈值
```

**不做无条件覆盖**（修 D1），证据全部累加后一次性裁决。

### 3.1 多仓容器（electron 引入的新场景）

`led` 没有 `package.json`，下挂两个独立仓（各有 `.git`）。这类目录的正确处理：

```text
led/                     容器 → 不判型，只枚举子仓
├── calibrationtool/     electron_node
└── calibration-subsystem/  unknown（Node 服务）
```

现在的实现给两个 `repo_root` 就停了（D13）。多仓容器在工作目录层面很常见
（`--work-dir` 指向一个产品目录而不是单个仓），值得单独处理。

---

## 4. 回归夹具约定

样本仓不入库（几百 MB，submodule URL 指向内部域名，含未脱敏业务信息）。
每类在 `test/fixtures/repos/<type>/` 下放人造微型夹具，只保留判据要素：

```text
test/fixtures/repos/
├── micro-frontend/             # single-spa + 3 个 src/<App> + modules.js
├── device-web/                 # index.asp + project_config.json + 双入口
├── device-web-single-spa/      # 反例：有 single-spa 但有 .asp
└── electron/                   # 待补
```

`device-web-single-spa/` 是最关键的一个：它把"框架名不是判据"钉成永久回归测试。

---

## 5. 待决策

| # | 问题 | 倾向 |
|---|---|---|
| 1 | `CodeKnowledge` 要不要加 `modules[]`？ | 微前端**要**（定位必须落到子应用）；设备 web **不要**（同仓模块是路由级，无独立部署边界） |
| 2 | `CodeKnowledge` 要不要加 `productLine`？ | hcp/hct 同模板两条产品线，建议加；或由 `repoRoots` 名称承载 |
| 3 | 判据何时落 `detect.py`？ | 微前端 + 设备 web 共 5 仓已齐，可先落这两类；electron 待补 |
| 4 | 阈值怎么定？ | 见各类型文档的评分表；5 仓实测下来 `≥6`（微前端）与 `≥8`（设备 web）都能正确分离 |
