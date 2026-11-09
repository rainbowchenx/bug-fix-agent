# 微前端系列（`micro_frontend`）· 完整分析

样本三个，**两种子形态**：

| 样本 | 子形态 | 模块来源 |
|---|---|---|
| `hcp/hcp`（55 模块）、`hct/hct`（21 模块） | 宿主 + **git submodule** 型 | `src/<App>` 是独立仓，可分别发版 |
| `camera/camera`（7 模块） | **同仓模块**型 | `src/<Module>` 是普通目录，一仓一发 |

hcp 与 hct 是同一模板的两条产品线；camera 是同一产品线的 4.5 代（V4.5.0，2021）。
三者共用同一套内部脚手架。

- 契约枚举：`micro_frontend`（`contracts/bugfix_contracts/code_knowledge.py:CartographyProfile`）
- 现有判型：`platform/bugfix_platform/agents/cartographer/detect.py` —— 只认 `single-spa` 依赖
- 现有架构图：`platform/bugfix_platform/agents/cartographer/architecture.py:_map_micro_frontend()` —— 实测无产出

---

## 1. 逐仓走读

### 1.1 hcp/hcp（主体样本）

| 项 | 值 |
|---|---|
| `package.json` name | `simple-single-spa-webpack-example`（脚手架原名，未改） |
| 依赖 | 130 deps / 65 devDeps；`vue 3.5` + `single-spa 5.5` + `single-spa-vue 1.5` + `light-front-vue 1.0` |
| `.gitmodules` | **55 个**子应用，全部在 `src/` 下 |
| `src/` 目录数 / 源码文件 | 88 / **10330** |
| 共享内核 | `src/Common`（552 文件） |
| 顶层 | `.editorconfig` `.gitignore` `.gitmodules` `README.md` `babel.config.js` `build/` `eslint.config.mjs` `init.js` `webpack.config.js` `src/` |

### 1.2 hct/hct（同模板，另一产品线）

| 项 | 值 | 与 hcp 的差异 |
|---|---|---|
| `package.json` name | 同上 | 相同 |
| 依赖 | 140 deps / 65 devDeps | 多 10 个：`hui-intl-x`、`hui-mobile 3.0.0-alpha.21`；`light-front` 版本 1.0.4 vs 0.8.5 |
| `.gitmodules` | **21 个** | 子应用前缀 `HCB`（`src/HCBPerson`），hcp 无前缀（`src/Person`） |
| `src/` 目录数 / 源码文件 | 33 / 4493 | 规模约为 hcp 的 43% |
| 额外配置 | `CLAUDE.md`、`AGENTS.md`、`.trellis/`、`.codegraph/`、`sbom-external.json` | hcp 无 |

**`scripts` 逐条相同**，包含产品线开关：

```text
dev:HCC / dev:HCT / dev:HCL / dev:HCP     ← 四个产品线，靠 env.currentProject 切换
build:main / build:common / build:components / build:delegate
build           node ./build/command/build/index.js --mode production --env.modules
```

`build/config/` 下有四份产品线配置：`HCC/ HCL/ HCP/ HCT/`。

**结论**：`仓` 不是唯一身份，`产品线` 是第二个维度。同一缺陷可能在两仓都存在（共用 `Common`），也可能只在一条产品线。

### 1.3 camera/camera（4.5 代，同仓模块型）

| 项 | 值 |
|---|---|
| `package.json` name | `simple-single-spa-webpack-example`（与 hcp/hct 同名，同脚手架） |
| 依赖 | 44 deps / 58 devDeps；`vue 2.6` + `hui 2.15` + **`single-spa 3.8.1` + `single-spa-vue`** + `webpack 4` |
| git remote | `.../IPSC/Integration/DeviceWeb/deviceweb5.0/basevideo/camera` |
| `project_config.json` | `"version": "V4.5.0build210726"`，`"deviceType": 0`，**无 `standard` 字段** |
| 模块（7 个） | `Application` `Common` `Config` `Download` `IntelligentDisplay` `Playback` `Portal` `Preview` |
| 独有 | `test/`（karma）、`tsconfig.json`、`VideoRecorder/`、`depends/`、`eventControl.js` |

**它为什么是微前端**（四条独立证据）：

```text
① src/index.html 有 7 个 mount div：#preview #playback #download #config #portal #application #intelligentDisplay
② 7 个模块目录各有 vue.app.js，且 el: "#<module>" 一一对应：
     src/Preview/vue.app.js:31           el: "#preview"
     src/Playback/vue.app.js:25          el: "#playback"
     src/Config/vue.app.js:34            el: "#config"
     ... 全部 import singleSpaVue
③ build/helper/build.js:703   自动生成模块入口
     fs.writeFileSync(pathName + '/autoloader.js', `export default import('./${fileName}');`)
④ build/helper/build.js:717-718  每模块产出独立 UMD
     copyOptions.output.library       = 'HCPModule_' + module
     copyOptions.output.libraryTarget = 'umd'
```

`build/helper/build.js:getModules()` 的默认构建清单是 `['root-application', 'Portal']`，
即「一个宿主 + 一个模块」，与 hcp 的 `getWebpackEntry()` 语义相同。

**与 hcp 的差别只有两点**：模块是同仓目录而非 submodule；`src/root-application.js` 是
**0 字节空文件**（脚手架残留，宿主逻辑已迁到设备侧）。

---

## 2. 结构

```text
hcp/hcp/                              ← 宿主壳（shell / root config）
├── src/root-application.js           ← 真入口：按 nature=h5 分流
│     if (nature === 'h5') import('@/Common/mobile/init');
│     else                 import('@/Common/init/[project]/index');
├── src/index.js                      ← 文件头注释写着"这个文件已经废弃了，在 common/init 中"
├── src/Common/                       ← 共享内核（552 文件）
│   ├── init/{hcp,hcc}/               ← 产品线专属启动逻辑
│   ├── service/utils/regist.app.js   ← 统一注册器（app.use 批量注入）
│   ├── service/utils/utils.js        ← loadModuleExports()（跨模块取值）
│   └── libs/light-front/globalApi.js ← 内含 registerApplication 调用
├── src/<App>/                        ← 55 个 git submodule，每个是独立仓
│   ├── autoloader.js                 ← export default () => import('./vue.app.js')
│   ├── vue.app.js                    ← createApp + registApp(app) + 挂 router/store
│   ├── exportComponents.js           ← 向其他子应用暴露 Vue 组件
│   ├── exportData.js                 ← 向其他子应用暴露数据/方法
│   └── .claude/ .trellis/ openspec/ .codegraph/   ← 子仓自带的 AI 配置
├── build/config/modules.js           ← 子应用构建清单
└── build/helper/build.js:264         ← getWebpackEntry()：单次只打一个子应用
        output.libraryTarget = 'umd'
        output.library       = `HCPModule_${app}`
```

### 2.0 两种子形态

```text
submodule 型（hcp / hct）                同仓模块型（camera）
src/<App>/  ← 独立 git 仓，可单独发版     src/<Module>/  ← 普通目录，随仓一起发
src/<App>/.claude  .trellis  openspec     （无）
.gitmodules 55 / 21 条                    无 .gitmodules
```

两者**构建契约完全一致**：`autoloader.js` → `vue.app.js` → UMD `HCPModule_<Module>`。
所以判据可以用同一套；差异只体现在"模块清单从哪来"（`.gitmodules` vs 目录扫描）。

### 2.1 三个层次，对应三种定位粒度

| 层 | 位置 | 定位粒度 |
|---|---|---|
| 宿主壳 | `src/root-application.js`、`src/Common/init/` | 壳级缺陷（路由、登录、i18n 初始化） |
| 共享内核 | `src/Common/` | 跨应用缺陷（工具函数、HTTP、权限、组件库） |
| 子应用 | `src/<App>/` | 业务缺陷主体；**缺陷单的 `testModule` 直接对应这里** |

### 2.2 构建清单长什么样

`build/config/modules.js`：

```js
Portal: ["vue.app.js", "exportComponents.js", "exportData.js"],
// 多数模块是三件套；部分带 "./mobile/vue.app.js"（H5 独立入口）
// CsEmbed: []  ← 空数组：嵌进来的独立应用，不走这套入口
```

`getWebpackEntry()` 一次只打一个子应用（`process.env.currentApp || 'Common'`），
产物是可独立部署的 UMD。

---

## 3. 判据

### 3.1 强判据（命中即定型）

| # | 判据 | hcp | hct | 说明 |
|---|---|---|---|---|
| S1 | `deps` 含 `single-spa` + `single-spa-vue` | ✅ | ✅ | 现实现只有这条；不覆盖 qiankun/MF（D2） |
| S2 | **`.gitmodules` 中 ≥3 条 submodule path 落在 `src/`，且每个含 `vue.app.js`** | 55 | 21 | 零成本，对框架方案不敏感。**必须加 `vue.app.js` 限定**，否则会误伤设备 web 的框架 submodule（见 device-web.md E4） |
| S3 | `build/config/modules.js` 存在，值为「模块名 → 入口文件数组」 | ✅ | ✅ | 比依赖名更能区分"微前端壳"与"普通多页应用" |
| S4 | 子目录 `autoloader.js` 内容为 `export default () => import('./vue.app.js')` | ✅ | ✅ | 多子应用同时出现即强 |

**优先用 S2**：读一个文本文件即可，不依赖 `node_modules` 是否安装。

### 3.2 弱判据（需组合，≥2 条）

| # | 判据 | 说明 |
|---|---|---|
| W1 | 子目录成对出现 `exportComponents.js` + `exportData.js` | 子应用对外接口约定 |
| W2 | 存在统一注册器（批量 `app.use`），子应用不自建 app | 宿主注入依赖 |
| W3 | webpack `libraryTarget: 'umd'` + `library: <PRODUCT>Module_<App>` | 产物命名约定 |
| W4 | 构建脚本按 env 变量选入口（`getWebpackEntry()` / `getCurrentApp()`） | 单次只打一个子应用 |
| W5 | 依赖内部框架 `light-front` / `light-front-vue` | 仓特异，本仓群独有 |

### 3.3 反例

| # | 反例 | 为什么 |
|---|---|---|
| E1 | `vue` + `vue-router` + `webpack` | 普通 Vue SPA 全有 |
| E2 | `element-plus` / `hui-intl` | 公司通用 UI 库，三类仓都可能用 |
| E3 | 子目录里有 `package.json` | `src/CsEmbed/package.json`（`name: web-server`，`vue-cli-service`）是嵌进微前端的独立应用。**子目录有 package.json ≠ 微前端** |
| E4 | `hybrid-webframework` | hcp 用它只取 `DebugTool`；设备 web 也可能用同名桥 → 跨类歧义 |
| E5 | `single-spa` 仅在 `devDependencies` | 装了但未用 |
| E6 | 目录名含 `bridge` / `webview` / `mobile` | `CsEmbed`、`DevCall`、`MobileSureillance` 都属这类命名，无区分力 |
| E7 | `.gitmodules` 存在 | 设备 web 也可能有（框架 submodule），必须配合 S2 的 `vue.app.js` 限定 |
| E8 | `root-application.js` 存在 | hcp/hct/camera 都有；camera 那份还是 **0 字节**空文件 |
| **E9** | **`src/*.asp` / `src/project_config.json`** | camera（微前端）与 peitao/transport（设备 web）**都有** —— 这是「部署在设备上」的宿主标记，**与应用架构正交**。曾据此把 camera 误判成 device_web |
| E10 | `package.json` 的 `name` | hcp/hct/camera 三个仓都叫 `simple-single-spa-webpack-example`；peitao/transport 都叫 `web5.0-framework` → name 只标脚手架世代，不标仓身份 |

### 3.4 评分

| 分值 | 判据 |
|---|---|
| +5 | `src/*/vue.app.js` 计数 ≥3 且每模块 `import singleSpaVue`（两种子形态通用） |
| +4 | `.gitmodules` 中 `src/` 下含 `vue.app.js` 的 submodule ≥3（仅 submodule 型） |
| +4 | deps 含 `single-spa` / `qiankun` / `wujie` / `micro-app` / `@module-federation/*` |
| +3 | `build/config/modules.js` 式模块清单存在 |
| +2 | 子目录成对出现 `exportComponents.js` + `exportData.js` |
| +2 | deps 含 `light-front` / `light-front-vue` |
| +1 | UMD library 命名 `<X>Module_<App>` |

`≥6` → `micro_frontend`（hcp / hct 实测 16+；camera 实测 5+4+3+2+2 = 16）。
**宿主标记不计分**（E9）：`src/*.asp`、`src/project_config.json` 不进判据表。

---

## 4. 对 Agent-2 的影响

### 4.1 定位粒度必须落到子应用

`defectCodeMatches[]` 现在是仓内路径。这类仓的正确粒度：

```text
仓 hcp/hcp  →  子应用 src/Anpr  →  src/Anpr/view/x.vue
```

缺陷单的 `testModule` 与子应用名高度相关（`报警推送` ↔ `src/Event`、`人员管理` ↔ `src/Person`）。
→ `specAtlas` 需显式记录 `modules[]`：子应用名 / 路径 / 入口文件 / 是否已 checkout。

### 4.2 跨子应用耦合是主要根因

实测 `loadModuleExports(...)` 调用分布：

```text
loadModuleExports('Person'       )  106 次
loadModuleExports('Resource'     )   46 次
loadModuleExports('Map'          )   12 次
loadModuleExports('VehicleManage')    8 次
loadModuleExports('Attendance'   )    6 次
loadModuleExports('FocSign'      )    5 次
```

`Person` 被 106 处跨模块引用 → **现象在 A 子应用、根因在 B 子应用是常态**。
单文件定位几乎注定失败。

→ 建议把 `loadModuleExports('X','exportData','fn')` 建成跨模块引用图，作为 `match.py` 的加边依据。

### 4.3 一个仓里两种形态：PC + H5

```js
// src/root-application.js
if (nature === 'h5') { import('@/Common/mobile/init'); }
else                 { import('@/Common/init/[project]/index'); }
```

hct 另带 `hui-mobile@3.0.0-alpha.21`，`src/*/mobile/vue.app.js` 是独立入口。
→ 定位前须先判 PC / H5，否则在两套相似但不同的代码间乱跳。

### 4.4 同仓模块型：`index.html` 的 mount div 就是模块清单

camera 没有 `.gitmodules`，模块清单藏在 `src/index.html`：

```html
<div id="preview"></div>      <div id="playback"></div>
<div id="download"></div>     <div id="config"></div>
<div id="portal"></div>       <div id="application"></div>
<div id="intelligentDisplay"></div>
```

每个 div 与 `src/<Module>/vue.app.js` 的 `el: "#<module>"` 一一对应。
→ 同仓模块型的 `modules[]` 从「`index.html` 的 mount div」+「`src/*/vue.app.js`」
两个来源交叉得到，比目录扫描可靠（目录里还有 `Common` 这种非模块目录）。

### 4.5 `@/` 别名不是单层映射

`build/config/{HCP,HCT,HCL,HCC}/config.js` 里 `@/Common/*` 与其他 `@/*` 走**不同输出路径**：

```js
} else if (pathArray[0] === '@' && pathArray[1] === 'Common') {  // Common 下的文件直接放 Common
} else if (pathArray[0].indexOf('@') === 0) {                    // 其他按 Map 路径分目录
```

→ 任何 "`@` = `src`" 的推断在此会偏差。

---

## 5. 现有实现的产出（实测）

```text
hcp/hcp         repoRoots ['.']   entryPoints []   modules [('mf','micro_frontend_root')]
camera/camera   repoRoots ['.']   profile micro_frontend（判对，但只靠 single-spa 依赖）
                entryPoints []    modules [('mf','micro_frontend_root')]
```

三个仓的架构图**都是空的**。camera 判型对是运气——它恰好有 `single-spa` 依赖，
而真正普适的判据（`src/*/vue.app.js` 计数、mount div、UMD 模块产物）一个都没用上。

四个原因（详见 README D4–D7）：子应用在深度 2 扫不到、`SPA_APP` 正则不认 `src/<App>/`、
shell 判定读的是路径而非内容、`limit=400` 只覆盖 3.9% 文件且按字母序截断。

---

## 6. 复验命令

```bash
cd E:/working_code_webfront/bug-fix-demo-project/hcp/hcp

# S2：子应用清单与数量
grep -c '^\[submodule' .gitmodules
grep -A1 '^\[submodule' .gitmodules | grep 'path =' | head

# S3：子应用构建清单
head -40 build/config/modules.js

# S4：子应用入口约定
cat src/Anpr/autoloader.js

# S5：camera 的同仓模块型（在 camera/camera 下执行）
cd ../../camera/camera
find src -name vue.app.js | wc -l                      # 7
grep -o 'id="[a-zA-Z]*"' src/index.html | sort -u       # 7 个 mount div
grep -rn 'el: "#' src/*/vue.app.js                      # 与 div 一一对应
grep -n "HCPModule_\|autoloader.js" build/helper/build.js   # 703 / 717 行

# W3：UMD 产物命名
grep -n "libraryTarget\|library:" build/helper/build.js

# 4.2：跨模块耦合强度
grep -rn "loadModuleExports(" src --include="*.js" --include="*.vue" \
  | grep -o "loadModuleExports('[A-Za-z]*'" | sort | uniq -c | sort -rn

# 4.3：PC / H5 分流
head -12 src/root-application.js

# 5：现有实现产出（在 bugfix-agent 仓根执行）
python -c "
from bugfix_platform.agents.cartographer.detect import discover_repo_roots
from bugfix_platform.agents.cartographer.architecture import map_architecture
wd = r'E:\working_code_webfront\bug-fix-demo-project\hcp\hcp'
print(map_architecture(wd, discover_repo_roots(wd), 'micro_frontend'))"
```

---

## 7. 回归夹具（建议，未做）

样本仓不入库（几百 MB + submodule URL 指向内部域名）。人造微型夹具只保留判据要素：

```text
test/fixtures/repos/micro-frontend/
├── package.json                 # single-spa + single-spa-vue + light-front-vue
├── .gitmodules                  # 3 条 src/<App> submodule
├── build/config/modules.js      # 两模块 × 三入口
└── src/
    ├── root-application.js      # nature=h5 分流
    ├── Common/service/utils/regist.app.js
    ├── AppA/{autoloader,vue.app,exportComponents,exportData}.js
    └── AppB/{autoloader,vue.app,exportComponents,exportData}.js
```

用途：让 D4–D7 的修复有测试保护，也与 device-web 夹具同构。
