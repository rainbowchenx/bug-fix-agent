# 仓型分析 · 索引

Agent-2 **不再判仓型**：`cartographyProfile` 由调用方传入（`--cartography-profile` /
`options.cartographyProfile`）。这份目录是类型已知之后的**读码地图**——每类该先打开哪些
清单、缺陷沿哪条边跳。评测夹具在 `test/fixtures/repos/`（`pytest tests/platform/test_cartography_eval.py`）。

| 文档 | 类型 | 样本 | 状态 |
|---|---|---|---|
| [micro-frontend.md](micro-frontend.md) | `micro_frontend` | hcp（55 submodule）、hct（21 submodule）、camera（7 同仓模块） | ✅ 完整 |
| [device-web.md](device-web.md) | `device_web` | peitao（5.x/Vue2）、transport（5.x/Vue3） | ✅ 完整（camera 已排除，见 §2.5） |
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
                    single-spa  每模块 vue.app.js  双入口 main-pc/mobile  真类
hcp/hcp             ✓           55 个              ✗                    micro_frontend
hct/hct             ✓           21 个              ✗                    micro_frontend
camera/camera       ✓           7 个               ✗                    micro_frontend
peitao              ✗           0                   ✓                    device_web
transport           ✗           0                   ✓                    device_web
calibrationtool     ✗           0                   ✗（有 preload）      electron_node
```

**分水岭是「模块怎么切、产物怎么发」，不是框架名，也不是宿主**。补充三个同型陷阱：

- `vite-plugin-electron` ≠ Electron 应用（`calibration-subsystem` 只是拿它当 Node 打包器）
- `koa` 依赖 ≠ HTTP 服务端（`calibrationtool/electron` 有 `@types/koa` 但只做 HTTP 客户端，`new Koa` 出现 0 次）
- `src/*.asp` + `project_config.json` ≠ device_web（camera 两者都有，却是微前端，见 §2.5）

### 2.2 "设备相关"的代码量不能区分任何一类

| 仓 | 真类 | 设备能力文件 | ISAPI 文件 |
|---|---|---|---|
| hcp/hcp | micro_frontend | **128** | **1205** |
| transport | device_web | 64 | 56 |
| camera/camera | micro_frontend | 36 | 37 |
| peitao | device_web | 1 | 15 |

hcp 是**管理设备的平台**，调 ISAPI 比设备自身的界面还多。这条思路比框架名更容易踩坑，
因为它符合直觉。

### 2.3 实现现状：判型已取消

`detect_cartography_profile()` 现在**只收集技术栈线索，不再输出类型**，固定返回 `unknown`；
`cartographyProfile` 由调用方给定（`--cartography-profile` / `options.cartographyProfile`），
`architecture.py` 按给定类型定点读清单（catalog），`sdk/cartography.py` 也不允许 SDK 重新分类。

这个决定的直接后果：**下面 D1/D2/D3/D8/D9 那批"判型缺陷"整体作废**——不是修好了，
是那条路被删掉了。判据仍然有用，但它现在是**给人/上游填 profile 用的**，不是 Agent-2 的代码。

### 2.4 实现缺陷清单（D1–D13 的现状）

判型侧（已随"取消判型"整体消解）：

| # | 原缺陷 | 现状 |
|---|---|---|
| D1 | electron 分支无条件覆盖 | 消解：无分支 |
| D2 | 只认 `single-spa` | 消解：不探测 |
| D3 | `device_web` 靠根目录名正则 | 降级：只剩 `device-bridge-path` 一条 hint，不参与定型 |
| D8 | `BRIDGE` 正则五仓命中 0 次 | 消解：`_map_device_web` 改用 `jsWebControl` / `service/device.js` 实际路径 |
| D9 | `single-spa` 同时是两类特征 | 已撤销，见 §2.5 |

架构图侧（本次逐条复验）：

| # | 原缺陷 | 现状 |
|---|---|---|
| D5 | `SPA_APP` 正则不认 `src/<App>/` | ✅ 修：改读 `.gitmodules` + `index.html` mount div + `vue.app.js` |
| D6 | `if "registerApplication" in f`（f 是路径） | ✅ 修：不再靠字符串猜 shell |
| D7 | `_list_src_rel(limit=400)` | ✅ 修：`_walk_files` 默认 50k，且 src 优先排序 |
| D10 | `ELECTRON_MAIN` 可选前缀 | ✅ 修：主进程来自 `package.json:main` + `electron/electron/main/` |
| D11 | 多 root 重复产出 | ✅ 修：`_dedupe` / `_dedupe_modules` |
| D12 | renderer 取前 5 个业务页 | ✅ 修：显式 `web/src/main.ts`，并排除 `/views/` |
| D4/D13 | `discover_repo_roots` 只扫深度 1、不递归 | ✅ 本轮修（N4）：容器目录补扫描根 |
| **N1** | **多仓时路径坐标系错位** | ✅ 本轮修：候选存仓相对路径，打分用 workDir 相对路径 |
| **N2** | **`device.js` 只认 `src/{Common,common}/service/`** | ✅ 本轮修：补 `**/service/device.js`（peitao 在 `src/common/vue/service/`） |
| **N3** | **`root-application.js` 为空 → 无 entryPoint** | ✅ 本轮修：退回 `src/index.js/ts/html` 并写 note（camera） |

四条新缺陷（N1–N4）都是从真实仓跑出来的，不是读代码猜的：

```text
N1  electron 夹具 repoRoots=['electron','web']，候选路径是根相对，
    而 architecture.modules[].path 是 workDir 相对 → _under() 全部失效，
    web/src/** 一分不加，EL2 候选为空（pytest 红）
N2  peitao 的 device.js 在 src/common/vue/service/device.js（多一层 vue/）
    → modules 只有 host-asp，能力锚点丢失
N3  camera 的 src/root-application.js 是 0 字节 → entryPoints 为空，
    7 个模块没有任何装配点
N4  electron-container 的 calibrationtool 在 depth-2 才有 package.json
    → repoRoots 只有 ['calibration-subsystem']，match 从不扫 calibrationtool 那棵树
```

### 2.5 一次误判的复盘：宿主 ≠ 架构

最初把 `camera/camera` 归为 `device_web`，依据是三个"看起来很设备"的信号：

```text
src/*.asp           → 设备内置 ASP 服务托管页面
src/project_config.json → deviceType / pluginVersion / localService
Common/service/device.js → PTZ / 雨刷 / 鱼眼 设备能力对象
```

三条全对，结论却错。camera 的真实结构是：

```text
src/index.html   7 个 mount div
src/<Module>/vue.app.js   7 个，每个 import singleSpaVue，el 与 div 一一对应
build/helper/build.js:703  自动生成 autoloader.js
build/helper/build.js:717  output.library = 'HCPModule_' + module（UMD）
```

**它是微前端，只是部署在设备上。** 而 peitao/transport（真 device_web）同样有
`.asp` 与 `project_config.json` —— 这两个文件只能证明"跑在设备上"，不能证明"怎么切模块"。

修正后的判据把「宿主」和「架构」分开：

| 轴 | 取值 | 从哪看 | 进不进判型 |
|---|---|---|---|
| 架构 | 微前端 / 单体双端 / 桌面 | `vue.app.js` 计数、UMD 产物、双入口、preload | ✅ 判型依据 |
| 宿主 | 设备 ASP / Web 服务器 / exe | `*.asp`、`project_config.json`、`electron-builder` | ❌ 只记 `notes` |

**教训**：判类型要先问"代码怎么组织、产物怎么发"，再问"跑在哪"。
顺序反了就会像我这次一样，被三个正确的信号带到一个错误的结论。

### 2.6 五仓实测（类型由调用方给定后的产出）

`python -m pytest tests/platform/test_cartography_eval.py` 走夹具；真实仓手工跑：

```text
仓                 roots entries modules 角色                                    top1 候选                     耗时
hcp/hcp                1       1      58 micro_app,shared_kernel,shell          src/Person/exportData.js      3.3s
camera/camera          1       1       9 micro_app,shared_kernel,shell          src/Preview/components/index.js 0.3s
peitao                 1       4       2 device_capability,host                  src/common/vue/service/device.js 0.3s
transport              1       4       3 device_bridge,device_capability,host    src/Portal/view/login/mobile/Login.vue 0.2s
led                    2       4      28 driver_asset,ipc_domain,main,preload,renderer  calibrationtool/electron/electron/controller/boxCalibration/… 0.2s
```

对照改造前（`unknown` + 空架构图 / electron 三处错）：**5/5 有实质产出**，且四个类别
的 top1 候选都落在正确子树（hcp→`src/Person/`、camera→`src/Preview/`、
peitao→`device.js` 本身、led→`controller/boxCalibration/`）。

peitao 那条最值得看：`雨刷按钮灰掉` 的 top1 直接是 `src/common/vue/service/device.js` ——
设备能力对象，而不是某个 view。这正是 device-web.md §4.2 想要的定位锚点。

判型只需看两条结构特征就能全部分对（供调用方填 profile 用）：

```text
仓                 双入口  vue.app.js    profile
hcp/hcp             .          48          micro_frontend
hct/hct             .          22          micro_frontend
camera/camera       .           7          micro_frontend
peitao              Y           0          device_web
transport           Y           0          device_web
calibrationtool     .           0          electron_node（看 deps + preload）
```

注意 `vue.app.js` 计数与模块数不等（hcp 48 vs 55 个 submodule），因为部分 submodule
未 checkout —— 判型只需 `≥3`；**建 `modules[]` 必须用 `.gitmodules` / mount div**，
不能靠目录扫描。

## 3. 判据的统一约定（给填 profile 的人/上游）

Agent-2 已不判型，这一节留作**调用方填 `cartographyProfile` 时的判据规范**——
将来若要恢复自动判型，也按这套来落码，避免又写成一串 `if`：

```text
每个判据 = (名称, 分值, 检查函数, 证据文案)

命中 → 累加分数 + 记录证据（证据要能写进 code-knowledge 的 notes，
                        便于人工复核"为什么判成这样"）

阈值 ≥6  → 定型
冲突     → 按类间优先级仲裁，不按命中顺序
```

三条判据轴**互不重叠**，不需要"谁压过谁"：

```text
micro_frontend  src/*/vue.app.js ≥3（同仓或 submodule 皆可）+ 模块级 UMD 产物
device_web      main-pc.js + main-mobile.js 双入口，且全仓 vue.app.js = 0
electron_node   deps 精确含 electron（vite-plugin-electron 不算）+ preload/contextBridge
unknown         都未达阈值
```

**不做无条件覆盖**（修 D1），证据全部累加后一次性裁决。

> 「部署宿主」（设备 ASP / Web 服务器 / 桌面 exe）是**另一个轴**，记进
> `architecture.notes`，不参与判型。曾经的错误规则「`src/*.asp` 压过 micro_frontend」
> 已撤销——camera 同时有 `.asp` 与 `vue.app.js`，宿主机 ≠ 架构。

### 3.1 多仓容器（electron 引入的新场景）

`led` 没有 `package.json`，下挂两个独立仓（各有 `.git`）。这类目录的正确处理：

```text
led/                     容器 → 不判型，只枚举子仓
├── calibrationtool/     electron_node
└── calibration-subsystem/  unknown（Node 服务）
```

本轮补了容器扫描根：`work_dir` **自身不是仓**时，把"自己没有清单、但直接子目录里有
清单（≥2 个）"的目录也加成扫描根（`_add_container_roots`，N4）。单仓里的 `src/` 不会
被误加——因为那时 `work_dir` 本身是仓，函数直接返回。

实测 `led`：`repoRoots = ['calibration-subsystem', 'calibrationtool']`，
`boxCalibration` 缺陷的 top1 是 `calibrationtool/electron/electron/controller/boxCalibration/`。

仍缺：容器内**不是仓也没有嵌套清单的目录**看不出来；以及 `cartographyProfile` 单值装不下
"Electron 壳 + 远程微前端页面"（见 §5）。

---

## 4. 回归夹具

样本仓不入库（几百 MB，submodule URL 指向内部域名，含未脱敏业务信息）。
每类在 `test/fixtures/repos/<type>/` 下放人造微型夹具，只保留判据要素：

```text
test/fixtures/repos/
├── micro-frontend/            # submodule 型：.gitmodules + 3 个 src/<App> + mount div
├── micro-frontend-in-repo/    # 同仓模块型（camera）：空 root-application + 3 个 vue.app.js
├── device-web/                # index.asp + project_config.json + 双入口
├── device-web-host-mf/        # 反例：有 .asp + project_config，但模块有 vue.app.js
├── electron/                  # 双根（electron/ + web/）
├── electron-container/        # 容器：calibrationtool(depth-2 清单) + 独立服务
└── eval-cases.json            # 7 个 hit@3 用例，绑夹具 + 缺陷票 + 期望路径前缀
```

`device-web-host-mf/` 是最关键的一个：它把 README §2.5 的误判钉成永久回归测试
（宿主标记相同，架构不同 → 必须判 `micro_frontend`）。

`electron-container/` 钉住 N4：容器目录自身没有 `package.json`，
清单在 `calibrationtool/{electron,web}/` 这层。

跑法：

```bash
pytest tests/platform/test_cartography_eval.py -q      # 7 个 hit@3 用例
pytest tests/platform/test_cartography_architecture.py -q
```

---

## 5. 待决策

| # | 问题 | 状态 |
|---|---|---|
| 1 | `modules[]` 要不要按类型区分 | ✅ 已落：微前端出 `micro_app`（有独立部署边界），设备 web 不出模块清单（同仓模块是路由级） |
| 2 | 判型要不要留在 Agent-2 | ✅ 已决：**不留**。改为调用方传 `--cartography-profile`，`detect.py` 只收线索 |
| 3 | 阈值怎么定 | 降级为"给填 profile 的人的参考"，见各类型文档评分表 |
| 4 | `cartographyProfile` 单值装不下"壳 + 内容" | ⏳ 倾向 A（见 electron.md §7）：只描述被分析代码所在仓，容器记进 `architecture.notes` |
| 5 | 容器内"不是仓、也没有嵌套清单"的目录 | ⏳ 仍看不出来（N4 只覆盖"子目录有清单"的容器） |
| 6 | `micro-frontend-in-repo` 是否要补 `src/index.js` 夹具 | ⏳ 目前只靠 `src/index.html` 兜底，camera 真实形态的 JS 引导没夹具 |
