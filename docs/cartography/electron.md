# Electron 系列（`electron_node`）· 完整分析

样本：`bug-fix-demo-project/led` —— 一个**多仓容器**，内含一个 Electron 产品 + 一个外挂 Node 服务。
这是三类里唯一需要处理"一个工作目录里有多个仓、多种技术栈"的类型。

- 契约枚举：`electron_node`（`contracts/code_knowledge.py:CartographyProfile`）
- 现有判型：`agents/cartographer/detect.py` —— `deps` 含 `electron` / `electron-builder` / `electron-vite`
- 现有架构图：`agents/cartographer/architecture.py:_map_electron()`

**与另两类最大的不同**：这一类的判型**现阶段基本可用**（实测 `calibrationtool` → `electron_node` ✓），
问题集中在**架构图粒度**：进程边界抓错了文件、外挂服务完全不可见、跨进程调用链没建。

---

## 1. 逐仓走读

### 1.1 `led/` —— 容器，不是仓

```text
led/                             ← 无 package.json、无 .git
├── calibration-subsystem/       ← 独立仓（Koa 后端 + native addon）
└── calibrationtool/             ← 独立仓（Electron 产品）
```

两个子目录各自有 `.git`。`led` 本身只是把它们放在一起，
所以「一个工作目录 = 一个产品 = 一个仓」的假设在这里第一次失效。

### 1.2 `calibrationtool/` —— Electron 产品（前后端同仓分目录）

| 项 | 值 |
|---|---|
| 根 | 无 `package.json`，构建由 `scripts/build.js` 编排；有 `.git` |
| 子工程 | `electron/`（主进程 + 打包）、`web/`（渲染进程前端）、`common/type.ts`（共享类型） |
| `electron/package.json` | `name: calibrationtool`，`main: dist-electron/main/index.js` |
| Electron 版本 | `electron@19.1.9`（较旧），`electron-builder@23.6.0` |
| 主进程依赖 | `better-sqlite3@12.4.1`（native，需 `asar: false`）、`electron-log`、`electron-dl` |
| 构建 | `vite-plugin-electron@0.11.2` + `vite-plugin-electron-renderer@0.14.2` |
| `web/package.json` | `name: web`，`vue@3.3` + `vue-router` + `vue-i18n@11` + `playwright`(e2e) |
| 打包配置 | `electron/electron-builder.json5` |

`electron/` 内部再分四层：

```text
electron/
├── electron/                ← 主进程源码（注意：目录名与父级重复）
│   ├── main/                ← index.ts / registerHandle.ts / SQLChannel.ts / crashReporter.ts / AsynchronousDependency.ts
│   ├── preload/             ← index.ts（contextBridge 暴露 125 个方法）
│   ├── ipc/                 ← callbackKey.ts / callbackMain.ts / callbackPreload.ts / index.ts
│   ├── controller/          ← 11 个域：boxCalibration calibrationTask camera hasp luxMeter polling project projectDetail system temperatureRise thermometer
│   ├── service/             ← calibration / db / driver / listenDisk
│   ├── module/db/           ← better-sqlite3 封装
│   ├── config/  types/  utils/
├── driver/                  ← 设备驱动（不参与编译，随包分发）
│   ├── camera/              ← HIKVISIONDriver241021win10.exe / win7.exe / 260407win10&11.exe
│   └── thermometer/         ← CH341M64.sys / CH341PORTS.DLL / WIN 1X / WIN 9X
├── file/  config/
└── electron-builder.json5
```

### 1.3 `calibration-subsystem/` —— 外挂 Node 服务（**不是 Electron**）

| 项 | 值 |
|---|---|
| `package.json` name | **`koa-template`** |
| 栈 | `koa@2.14` + `koa-router` + `koa-json` + `koa-pino-logger` + `serialport@13` |
| `main` | `dist/index.js` |
| 构建 | `vite build`，用 **`vite-plugin-electron` 当 Node 打包器**（`entry: ./src/index.ts`, `outDir: dist`） |
| native | `addon/` 内含 `.dll`（`AddonBase.dll`、`CASDK2*.dll`、`Ca410SDK.dll`）+ `addon/platforms/` |
| 依赖外置 | `excludeDependencies`: `sharp` / `unifyx` / `ref-napi` / `better-sqlite3` / `ffi-napi` / `http-server` / `serialport` |

**它是整套判据里最危险的反例**：见 §3.3 E1。

---

## 2. 结构与运行时

### 2.1 四层仓库结构

```text
led/                                  容器（无 package.json）
├── calibrationtool/                  Electron 产品（有 .git，无根 package.json）
│   ├── web/                          渲染进程（Vue3 SPA，可单独 npm run dev）
│   ├── electron/                     Electron 工程
│   │   ├── electron/                 主进程源码
│   │   ├── driver/                   设备驱动
│   │   └── electron-builder.json5    打包配置
│   ├── common/type.ts                主进程与渲染进程共享类型
│   └── scripts/build.js              统一编排：web 构建 → electron 构建 → 打 exe → 生成升级包
└── calibration-subsystem/            Koa 服务（独立仓，独立发版）
```

### 2.2 运行时调用链：四跳

```text
① 渲染进程  web/src/request/ipcRequest.ts
      window.electronAPI[config.url](...args)
                 │  （contextBridge 暴露的 125 个方法）
② preload   electron/electron/preload/index.ts
      contextBridge.exposeInMainWorld('electronAPI', electronAPI)
      ipcRenderer.invoke(channel, ...)
                 │
③ 主进程    electron/electron/ipc/callbackMain.ts → controller/<Domain>/
      controller/system、controller/calibrationTask ...
                 │
④ 外挂服务  electron/electron/service/calibration/index.ts
      fork(subsystemFilePath, [port, LEDToolDomain, logDirPath])
      → HTTP POST http://127.0.0.1:<port>/...
      → calibration-subsystem（koa）
```

**这才是这个产品的真实形态**：一个缺陷可能出现在这四跳的任何一跳，
而每一跳的代码在**不同目录、不同技术栈、甚至不同仓**。

### 2.3 进程边界

| 进程 | 代码位置 | 角色 |
|---|---|---|
| main | `electron/electron/main/` | 窗口、IPC 注册、SQLite、驱动、拉起子系统 |
| preload | `electron/electron/preload/index.ts` | 唯一桥接面（125 个方法，`contextBridge`） |
| renderer | `web/src/` | Vue 3 SPA；产物由 `mainWin.loadFile(indexHtml)` 加载 |
| 子进程 | `fork(subsystem/index.js)` | Koa 服务，打包含 `extraFiles: subsystem` |

窗口加载策略（`electron/electron/main/index.ts:103-108`）：

```ts
mainWin.loadFile(indexHtml)      // 生产：加载本地文件
mainWin.loadURL(devUrl)          // 开发：VITE_DEV_SERVER_URL
```

### 2.4 子服务生命周期（跨进程定位的关键）

```ts
// electron/electron/service/calibration/index.ts
private port: number | null = null      // dev 固定 4000；打包后 findPort(4000) 动态找端口
const subsystemFilePath = isPackaged()
  ? path.resolve(exePath(), '../subsystem/index.js')       // 与 exe 同级
  : path.resolve(__dirname, '../../subsystem/index.js')    // 开发期相对路径
this.server = fork(subsystemFilePath, [port, LEDToolDomain, logDirPath], { detached: true, stdio: 'pipe' })
await sleep(3000)                       // 固定等 3 秒
this.server.addListener('exit', (code) => { if (code && code > 1) this.start(true) })  // 自动重启
```

三个隐患值得记（都属于"这类产品的典型缺陷形态"）：

1. **固定 `sleep(3000)` 等服务就绪** —— 慢机器或冷启动必然偶发失败。
2. **端口 dev 固定 4000** —— 端口占用即启动失败，且多实例会互相踩。
3. **`code > 1` 才重启** —— 退出码 1 的崩溃不会被拉起。

### 2.5 「前后端分离」在这里已经退化

`web/src/request/index.ts` 留了一个模式开关：

```ts
const requestVersion = 'ipc' // ipc http

// import axiosRequest from './axiosRequest.ts'
import ipcRequest from './ipcRequest'

function getRequest() {
  if (requestVersion === 'ipc') {
    return ipcRequest
  }
  // return axiosRequest          ← http 分支被注释掉了
}
const request = getRequest()!    ← 断言非空
```

`axiosRequest.ts` 文件还在（5.6 KB），但 import 与 return 都被注释。
把开关改成 `'http'` 后 `getRequest()` 返回 `undefined`，`request!` 非空断言会在运行期炸。

→ **"web 可以脱离 Electron 独立跑"这个假设不成立**。判型时不要因为 `web/` 有
完整 vite 配置就当它是独立可部署的前端。

### 2.6 打包形态

`electron/electron-builder.json5`：

```json5
asar: false,                      // better-sqlite3 是 native，不能进 asar
appId: 'com.hikvision.calibrationtool',
files: ['dist-electron', 'SECRET', 'html'],
extraResources: [{ from: './prepareModules', to: './app' }],
extraFiles: ['addon', 'config', 'app.exe', 'file', '*.dll', 'subsystem', 'driver'],
win: { target: [{ target: 'nsis', arch: ['x64'] }] },
nsis: { oneClick: false, perMachine: true, ... }
```

`extraFiles` 里 `subsystem` / `driver` / `addon` / `*.dll` 都是**非 JS 资产**，
它们与 `fork()` 的路径假设一一对应。改判据或做定位时这条链不能断。

---

## 3. 判据

### 3.1 强判据（命中即定型）

| # | 判据 | 实测 | 说明 |
|---|---|---|---|
| V1 | `deps` 含 **`electron`**（精确包名） | `electron@19.1.9` | 现实现已有；**必须排除 `vite-plugin-electron`**（见 E1） |
| V2 | 存在 `electron-builder.json5` / `electron-builder.yml` / `package.json` 的 `build` 字段 | ✅ json5 | 桌面打包的确定信号 |
| V3 | `preload/` 下有 `contextBridge.exposeInMainWorld` | ✅ 125 个方法 | 桥接面是 Electron 独有结构 |
| V4 | `main` 字段指向 `dist-electron/**`（vite-plugin-electron 的产物约定） | ✅ | 比任意 `main` 值更精确 |
| V5 | 同时有 `vite-plugin-electron` + `vite-plugin-electron-renderer` | ✅ | renderer 插件是关键（纯 Node 打包不会装它） |

### 3.2 弱判据（需组合，≥2 条）

| # | 判据 | 说明 |
|---|---|---|
| X1 | `asar: false` + native 依赖（`better-sqlite3` / `serialport` / `ffi-napi`） | native 模块与 asar 互斥，是桌面应用的典型组合 |
| X2 | `extraFiles` 含非 JS 资产（`driver` / `addon` / `*.dll` / `subsystem`） | 说明产物要装在 Windows 机器上 |
| X3 | `driver/` 下有 `.sys` / `.inf` / 驱动安装 exe | 设备类桌面软件 |
| X4 | 主进程源码里出现 `fork(` / `spawn(` 指向本地服务目录 | 外挂 Node 服务 |
| X5 | IPC 通道命名 `<Domain>_<verb>`，且 `controller/` 下有同名域目录 | 代码组织约定（见 §5.1） |
| X6 | `web/` + `electron/` 并列，共享 `common/` | 前后端同仓分层 |

### 3.3 反例

| # | 反例 | 实测证据 |
|---|---|---|
| **E1** | **`vite-plugin-electron` 存在就当 electron 应用** | `calibration-subsystem` 依赖里有 `vite-plugin-electron@0.29.0`，但它只是拿它**当 Node 打包器**（`entry: ./src/index.ts` → `outDir: dist`）。它 **没有 `electron` 依赖、没有 preload、没有 BrowserWindow**，是纯 Koa 服务 |
| **E2** | `deps` 里有 `koa` 就以为有 HTTP 服务端 | `calibrationtool/electron` 的 devDeps 有 `@types/koa`，但主进程里 `new Koa` 出现 **0 次**（实测 grep）→ 它只是 HTTP **客户端** |
| **E3** | 含 `web/` 目录就当独立前端 | `web` 的 http 模式已注释，`getRequest()` 在 http 分支返回 `undefined`（§2.5） |
| **E4** | 有 `.git` 就是一个产品 | `led` 无 `.git`，`calibrationtool` 有 `.git` 但无根 `package.json`，其下 `electron/` `web/` 各有 `package.json` |
| **E5** | 目录名 `main`/`background` 就是主进程 | `web/src/main.ts`（Vue 入口）、`web/src/components/Message/main.vue` 都被现有正则判成主进程（§6） |
| **E6** | 目录名 `views` 就是 renderer | `web/src/views/**` 有几百个业务页面，现有实现随机取前 5 个当 renderer 入口 |

### 3.4 评分

| 分值 | 判据 |
|---|---|
| +5 | `deps` 精确含 `electron` |
| +4 | `electron-builder.json5` / `.yml` 或 `package.json.build` |
| +4 | `preload/` 下有 `contextBridge.exposeInMainWorld` |
| +3 | `main` 指向 `dist-electron/**` |
| +3 | `vite-plugin-electron` **+** `vite-plugin-electron-renderer` 同时存在 |
| +2 | `asar: false` 且含 native 依赖 |
| +1 | `extraFiles` 含 `driver` / `addon` / `*.dll` |
| +1 | `controller/` 与 IPC `<Domain>_` 前缀对应 |

`≥8` → `electron_node`（`calibrationtool` 实测 5+4+4+3+3+2+1+1 = 23；
`calibration-subsystem` 仅 0 分，正确落 `unknown`）。

---

## 4. 与另两类的交集：容器 vs 内容

这是 electron 引入的**新问题**，前两类没有。

| 场景 | 该判哪类？ |
|---|---|
| Electron 壳 + 本地 Vue SPA（本样本） | `electron_node`（壳 = 被分析代码本身） |
| Electron 壳 + 远程微前端页面 | 壳是 `electron_node`，页面是 `micro_frontend` |
| Electron 壳 + 设备 web 页面 | 壳是 `electron_node`，内容是 `device_web` |
| 微前端里的某个 Electron 子应用 | 同上反向 |

契约 `cartographyProfile` 是**单值**，装不下"壳 + 内容"。两条路：

- **A（推荐）**：`cartographyProfile` 只描述**被分析代码所在仓**；内容跑在别处时，
  在 `architecture.notes` 里记 `container=electron`。
- **B**：契约加 `container` 字段，与 `cartographyProfile` 正交。

本样本落在 A：`web/` 与主进程同仓，`electron_node` 一个值足够。

---

## 5. 对 Agent-2 的影响

### 5.1 IPC 通道名 ↔ controller 目录名，是最强的定位锚点

实测 125 个通道，前缀分布：

```text
ProjectDetail      28      CalibrationTask   23
System             17      Project           15
BoxManage          12      Camera             7
Hasp                7      LuxMeter           6
TemperatureRise     5      Thermometer        2
CameraPolling       1      LuxMeterPolling    1      ScreenPolling  1
```

而 `controller/` 下恰好有 11 个同名域目录：
`boxCalibration calibrationTask camera hasp luxMeter polling project projectDetail system temperatureRise thermometer`

```text
缺陷描述里的功能点  →  IPC 通道前缀  →  controller/<domain>/  →  service/
"盒子校准失败"         BoxManage_*      controller/boxCalibration/
"温度标定无进度"       CalibrationTask_* controller/calibrationTask/
```

→ 建议 `specAtlas` 里建 **通道前缀 → controller 目录 → service 目录** 的三级映射表。
这是 electron 类仓里最省力的定位跳板，比全文 grep 通道名可靠得多。

### 5.2 外挂 Node 服务：跨仓定位

`fork(subsystemFilePath)` 意味着一个缺陷可能：
- 现象在渲染进程（Vue 页面）
- 原因在主进程（IPC 处理/端口/启动等待）
- 实现却在**另一个仓**（`calibration-subsystem` 的 `src/controllers/`）

现有 `code-knowledge.defectCodeMatches[]` 只在单个 `work_dir` 内找路径，
**跨仓这一跳会断**。需要在 `repoRoots` 之外记录"子服务依赖"：
`{ from: calibrationtool, to: calibration-subsystem, via: fork, entry: subsystem/index.js }`。

### 5.3 renderer 入口判定要用 `main` 字段与 loadFile，不要用目录名

真实 renderer 入口是：

```text
web/src/main.ts        ← createApp(App)
web/index.html         ← Vite 的 HTML 入口
mainWin.loadFile(indexHtml)   ← 主进程里显式加载的文件
```

`web/src/views/**` 是业务页面，不是入口。用"目录含 views 就当 renderer"必然抓错。

### 5.4 驱动与 native 资产

`driver/`（HIKVISION 相机驱动 exe ×3、CH341 串口 `.sys`/`.DLL`、`WIN 1X`/`WIN 9X`）
与 `addon/`（`CASDK2*.dll`、`Ca410SDK.dll`）不参与编译，但它们是
"设备连不上/驱动装不上"这类缺陷的**唯一现场**。
→ `architecture.modules` 应保留这些资产目录，role 记为 `driver_asset`，不要当噪声过滤掉。

---

## 6. 现有实现的产出（实测）

`calibrationtool`（判型正确，架构图有问题）：

```text
profile  : electron_node        ✅
roots    : ['.', 'electron', 'web']
modules  : 24 个，去重后 23（`web:main:main` 重复）
role     : main 12 / renderer 10 / preload 2
```

三个具体错误：

| 错误 | 证据 | 根因 |
|---|---|---|
| `web/src/main.ts` 被判成**主进程** | `["web/src/main.ts", "web/src/components/Message/main.vue"]` 出现在 role=main | `ELECTRON_MAIN` 正则 `(?:^|/)(?:electron/)?(?:main\|background)(?:[/.-]\|\.(?:ts\|js...)$)` 里 `(?:electron/)?` 是**可选**的，任何 `main.ts` 都命中 |
| renderer 是 5 个随机业务页 | `web/src/views/boxManagement/components/*.vue` | `ELECTRON_RENDERER` 匹配 `src/(renderer\|pages\|views)`，命中后按遍历顺序取前 5 |
| 同一路径产出两次 | `web:main:main` ×2 | `roots` 含 `.` 与 `electron`，`electron/electron/main/*` 被两个根各扫一次 |

`calibration-subsystem` → `unknown`（✅ 正确，但理由不对：它是靠"没有 electron 依赖"侥幸躲过，
而不是靠识别出"这是 Node 服务"）。

`led` → `unknown`（✅ 中立），但 `modules` 只有两个 `repo_root`，
**子仓没有被递归分类** —— 这是多仓容器场景的缺口。

---

## 7. 复验命令

```bash
cd E:/working_code_webfront/bug-fix-demo-project/led

# 仓库结构：容器 + 两个独立仓
find . -maxdepth 3 \( -name package.json -o -name .git \) -not -path "*/node_modules/*"

# V1：精确包名，注意 calibration-subsystem 只有 vite-plugin-electron
python -c "
import json
for p in ('calibrationtool/electron','calibration-subsystem'):
    d=json.load(open(p+'/package.json'))
    deps={**(d.get('dependencies') or {}),**(d.get('devDependencies') or {})}
    print(p, '| electron:', 'electron' in deps, '| vite-plugin-electron:', 'vite-plugin-electron' in deps)
"

# V3：桥接面
grep -n "contextBridge.exposeInMainWorld" calibrationtool/electron/electron/preload/index.ts

# V4：main 字段
python -c "import json;print(json.load(open('calibrationtool/electron/package.json'))['main'])"

# X2/X3：打包资产
sed -n '15,45p' calibrationtool/electron/electron-builder.json5
ls calibrationtool/electron/driver/thermometer | head

# X4：外挂服务拉起
grep -n "fork(\|subsystemFilePath =" calibrationtool/electron/electron/service/calibration/index.ts

# X5：通道前缀 ↔ controller 目录
ls calibrationtool/electron/electron/controller
python -c "
import re,pathlib,collections
t=pathlib.Path('calibrationtool/electron/electron/preload/index.ts').read_text(encoding='utf-8')
m=re.findall(r\"'([A-Za-z]+)_[A-Za-z0-9_]+'\", t)
print(collections.Counter(m).most_common())
"

# E1：vite-plugin-electron 只是打包器
sed -n '55,75p' calibration-subsystem/vite.config.ts

# E2：主进程没有 koa 服务端
grep -rn "new Koa" calibrationtool/electron/electron | wc -l      # 0

# E3：http 模式已注释
cat calibrationtool/web/src/request/index.ts

# E5/E6：现有实现的三处错误（在 bugfix-agent 仓根执行）
python -c "
from collections import Counter
from bugfix_agent.agents.cartographer.detect import discover_repo_roots
from bugfix_agent.agents.cartographer.architecture import map_architecture
wd=r'E:\working_code_webfront\bug-fix-demo-project\led\calibrationtool'
s,ep,mods=map_architecture(wd,discover_repo_roots(wd),'electron_node')
print(len(mods), Counter(m.role for m in mods))
print({k:v for k,v in Counter(m.id for m in mods).items() if v>1})
print([m.path for m in mods if m.role=='main' and m.path.startswith('web/')])"
```

---

## 8. 回归夹具（建议，未做）

多仓场景要两个夹具，否则测不出"容器 vs 内容"：

```text
test/fixtures/repos/electron/
├── package.json                  # electron + electron-builder + vite-plugin-electron(-renderer)
├── electron-builder.json5        # asar:false / extraFiles: subsystem, driver
├── electron/
│   ├── main/index.ts             # BrowserWindow + loadFile + fork(subsystem)
│   ├── preload/index.ts          # contextBridge.exposeInMainWorld
│   ├── ipc/callbackMain.ts
│   └── controller/system/index.ts
└── web/
    ├── package.json              # vue3 only，无 electron
    ├── src/main.ts               # ← 必须判 renderer，不能判 main
    └── src/request/index.ts      # ipc/http 开关

test/fixtures/repos/electron-multi-repo/     ← 容器夹具
├── tool/                         # 上面那套（含 .git）
└── subsystem/                    # koa + vite-plugin-electron（无 electron 依赖）
    └── package.json              # ← 必须判 unknown，不能判 electron_node
```

第二个夹具直接钉住 E1：**有 `vite-plugin-electron` 不等于 Electron 应用**。

---

## 9. 待补

- [ ] 多仓容器的递归分类（`led` → 两个子仓各自判型）
- [ ] "远端内容"场景样本（Electron 加载远程微前端/设备 web 页面）
- [ ] Tauri / NW.js 反例样本，避免把"桌面壳"等同于 Electron
- [ ] `asar: true` 场景（无 native 依赖）样本，验证 X1 不是必需条件
