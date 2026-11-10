# 嵌入设备 web 系列（`device_web`）· 完整分析

样本：`peitao`（5.x / Vue 2）、`transport`（5.x / Vue 3）。
两个仓 **`package.json` 的 `name` 都是 `web5.0-framework`**，是同一框架的两条产品线。

- 契约枚举：`device_web`（`contracts/bugfix_contracts/code_knowledge.py:CartographyProfile`）
- 判型：**不在 Agent-2**，由调用方传入 `--cartography-profile device_web`
  （旧实现靠根目录名正则，对两个样本命中 0 次；该分支已随"取消判型"删除）
- 架构图：`platform/bugfix_platform/agents/cartographer/architecture.py:_map_device_web()`，
  读双入口 + `service/device.js` + `jsWebControl` + `host-asp`，实测见 §5

---

## 0. 已排除的样本：`camera/camera` 不属于本类

最初把 `camera` 当作本类第三个样本（依据是它有 `src/*.asp`、`src/project_config.json`、
`Common/service/device.js`），**这是错的**。它属于微前端系列，理由见
[micro-frontend.md](micro-frontend.md) §1.3：

```text
camera   src/*/vue.app.js 存在 7 个，每个 import singleSpaVue 且 el: "#<module>"
         src/index.html 有 7 个 mount div，与 7 个模块一一对应
         build/helper/build.js:703  自动生成 autoloader.js
         build/helper/build.js:717  output.library = 'HCPModule_' + module
         build/helper/build.js:718  output.libraryTarget = 'umd'
```

这个误判留下的教训比结论本身更重要，写在 §3.3 E1：

> **`src/*.asp` 与 `src/project_config.json` 是「部署在设备上」的宿主标记，
> 与「应用架构类型」是两个正交的轴。** camera 与 peitao/transport 同属 deviceweb 产品线
> （git remote 都在 `.../DeviceWeb/deviceweb5.0/` 下），宿主相同，但架构一个是微前端、一个是单体双端。

---

## 1. 逐仓走读

### 1.1 peitao（5.x，Vue 2.7）

| 项 | 值 |
|---|---|
| `package.json` name | **`web5.0-framework`** |
| 依赖 | 30 deps / 73 devDeps；`vue 2.7.16` + `hui 2.42.6` + `hui-mobile 2.3.0-alpha.28` + `jquery 3.6` + `@huolala-tech/page-spy-browser` |
| `project_config.json` | `"version": "${version} build ${YYYYMMDD}"`，`"deviceType": 1`，`"standard": true`，`"pluginVersion": "V3.0.7.41"` |
| `src/` | `NotSupport` `common`（**小写**） `view` `router` `store` + `main-pc.js` / `main-mobile.js` / `main-mixin.js` + `hui.js` / `hui-mobile.js` + `package-lib.json` |
| 构建 | `build/{config,fork,helper,loaders,plugins,projectConfig}`；`file-limit.js`、`.local.config.js` |
| 产物 | `dist/` **129 MB**，顶层仅 `doc/` + `index.asp` |

`scripts` 里三套目标：

```text
dev:pc / dev:mobile / dev:app      build:pc / build:mobile / build:APP
dev    → NODE_ENV=pc|mobile → webpack-dev-server
```

### 1.2 transport（5.x，Vue 3）

| 项 | 值 |
|---|---|
| `package.json` name | **`web5.0-framework`**（与 peitao 同名） |
| 依赖 | **deps 只有 1 个**（`hui-intl 3.1.9`），devDeps 只有 1 个（`@device/pocket-mocker`） |
| `autoDependencies` | `{"hui-intl":"3.1.9", "@hc-ui/common":"3.0.2", "@hc-ui/device":"3.0.1", "@hc-ui/platform":"3.0.1"}` ← **依赖靠私有字段自动注入** |
| `project_config.json` | `"version": "V5.6.0_R0107 build 251111"`，`"deviceType": 31`，`"standard": true`，`"supportBrowser": ["NONIE"]` |
| `src/` | `APP-pc.vue` / `APP-mobile.vue`、`Router/{pc.js,mobile.js}`、`Common/`、`BasicFramework/`(submodule)、15 个业务模块目录 |
| 工具链 | `CLAUDE.md`(221 行) `ai.md`(52 行) `.trellis/` `.claude/` `.mcp.json` `publish.js` `mock_data/` `buildConfig/` |
| `.gitmodules` | 2 条：`src/BasicFramework`（框架）、`.trellis/spec/FrontendCommon`（规范）→ **都不是应用模块** |

`package.json` 几乎不列依赖是个陷阱：靠 `deps` 判断技术栈在这类仓会直接失明。
`BasicFramework` 的 gitlab 路径（`.../IPSC/Integration/DeviceWeb/deviceweb5.0/basicframeworkplus.git`）
里直接写着 **DeviceWeb**。

### 1.3 两仓差异

| 维度 | peitao | transport |
|---|---|---|
| Vue | 2.7（Options API） | 3.x（`createApp`） |
| 框架来源 | `src/common/`（自带） | `src/BasicFramework/`（git submodule） |
| 依赖声明 | 常规 `dependencies` | `autoDependencies` 私有字段 |
| 路由 | `Router/{pc.js,mobile.js}` + 若干业务目录 | `Router/{pc.js,mobile.js}` |
| 额外入口 | `main-mixin.js` | 无 |
| 组件分端 | 单目录 + 运行时判端 | `Common/components/pc` / `/mobile` 分目录 |
| 构建配置 | `build/`（脚手架继承） | `buildConfig/`（4 个文件，runner 化） |

**结论**：`name` 相同、宿主相同、双入口相同，但内部组织差很多。
判据要用**结构**（双入口 / 无 vue.app.js），不能靠 `name` 或目录名。

---

## 2. 结构

```text
<repo>/
├── src/index.asp                ← 产物入口（设备 ASP 服务托管）；camera 也有，非本类独有
├── src/dispatch.asp             ← URL 转发页
├── src/index.html               ← 开发期占位
├── src/project_config.json      ← 设备配置（deviceType / pluginVersion / standard / theme / localService）
├── src/package-lib.json         ← 额外三方库白名单
├── src/main-pc.js               ← PC 入口（transport: Vue3 createApp）
├── src/mobile.js / main-mobile.js ← mobile 入口
├── src/main-mixin.js            ← 第三入口（仅 peitao）
├── src/APP-pc.vue / APP-mobile.vue  ← 两个根组件（仅 transport）
├── src/Router/{pc.js,mobile.js} ← 两套路由
├── src/Common/service/device.js ← 设备能力对象（PTZ / 雨刷 / 除冰 / 鱼眼 / 鹰眼 / IoT 网关）
├── src/Common/libs/jsWebControl/← 前端控件桥接层
└── build*/webpack.config.js
      filename: '../index.asp'   ← HtmlWebpackPlugin 直接产出 .asp
```

### 2.1 双端构建：一次只打一端

```js
// peitao/build/helper/build.js:60-78
function getWebpackEntry() {
  if (process.env.NODE_ENV === 'pc')     return { 'main-pc':     [ .../main-pc.js ] };
  if (process.env.NODE_ENV === 'mobile') return { 'main-mobile': [ .../main-mobile.js ] };
                                         return { 'main-mixin':  [ .../main-mixin.js ] };
}
```

PC 与 mobile 的入口、路由、组件树都不同 → **定位前必须先判端**。

### 2.2 与微前端最本质的区别

| | 微前端（hcp / camera） | 设备 web（peitao / transport） |
|---|---|---|
| 模块产物 | 每模块一个 UMD `HCPModule_<Module>` | **无**模块级产物 |
| 模块入口 | 每模块 `vue.app.js`（single-spa 生命周期） | 无 `vue.app.js`（全仓 0 个） |
| 构建单位 | 一次打一个模块 | 一次打一个端（pc / mobile） |
| 页内挂载点 | `index.html` 里 N 个 mount div | 单个 `#app` |
| 部署 | 模块可分别更新 | 整包烧进固件/升级包 |

---

## 3. 判据

### 3.1 强判据（命中即定型）

| # | 判据 | peitao | transport | 微前端 hcp/camera |
|---|---|---|---|---|
| **W1** | **`src/main-pc.js` + `src/main-mobile.js` 双入口** | ✅ | ✅ | ✗ / ✗ |
| **W2** | **全仓 `vue.app.js` 计数 = 0** | 0 | 0 | 55+ / 7 |
| **W3** | `deps` 无 `single-spa` / `qiankun` / `wujie` / `micro-app` | ✅ | ✅ | ✗ |
| W4 | `package.json` name = `web5.0-framework` | ✅ | ✅ | ✗ |

W1 + W2 是本次修正后最可靠的一对：**一个说明"怎么分端"，一个说明"没有模块级生命周期"**。
两者组合，微前端样本全部被排除。

### 3.2 弱判据（需组合，≥2 条）

| # | 判据 | 说明 |
|---|---|---|
| U1 | `src/package-lib.json` | 两个 5.x 都有，camera（4.5）无 |
| U2 | `deps` 含 `@hc-ui/device` / `@hc-ui/platform` 或 `autoDependencies` 字段 | 框架私有依赖声明 |
| U3 | devDep 含 `@device/*` scope | 内部工具域 |
| U4 | `Common/service/device.js` 含 `bSupportWiper` / `oFisheye` / `oEagleEye` / `oDeviceCapa` | 语义强但**极易被管理平台误伤**，见 E2 |
| U5 | 存在 `.dwt/`（`.dwt/cspace`、`.dwt/hirule`） | 内部工具链残留 |
| U6 | `project_config.json` 含 `"standard": true` | 5.0 标志（4.5 无）；仅作加分 |
| U7 | `Router/{pc.js,mobile.js}` 成对 | 分端路由 |

### 3.3 反例

| # | 反例 | 实测证据 |
|---|---|---|
| **E1** | **`src/*.asp` + `src/project_config.json` 当判据** | `camera` 两者都有，但它是微前端（7 个 `vue.app.js` + UMD 模块产物）。这两个是**宿主标记**（跑在设备上），不是架构标记 |
| **E2** | **设备语义 / ISAPI 调用** | hcp（微前端）有 **128** 个设备能力文件、**1205** 个 ISAPI 文件——它是**管理设备的平台** |
| **E3** | 构建脚本里出现 `HCPModule_` / `autoloader.js` | `peitao/build/helper/build.js` 里也有 `HCPModule_`（脚手架继承，925 行 vs camera 780 行），但它的 `getWebpackEntry()` 只返回 `main-pc/mobile`，模块打包路径**从未被调用** |
| **E4** | `.gitmodules` 存在 | transport 有 2 条，内容是框架（`BasicFramework`）与规范（`.trellis/spec`），不是应用模块 |
| **E5** | `deps` 少就以为不是前端项目 | transport deps 只有 1 个 |
| **E6** | 目录名含 `bridge` / `webview` / `mobile` | 五仓的 `BRIDGE` 正则命中 **0 次**；真实桥接层叫 `Common/libs/jsWebControl/` |
| **E7** | `package.json` 的 `name` 作为仓身份 | peitao 与 transport 的 `name` **完全相同**（`web5.0-framework`）→ 不能用 name 区分仓，只能区分框架世代 |
| **E8** | `src/common` 与 `src/Common` 大小写统一 | peitao 用 `src/common`（小写），transport 用 `src/Common`。Windows 上不报错，CI 上才炸 |
| **E9** | `driver/`、`addon/`、`.dll` 等设备资产 | 这些是 electron 产品的典型资产（见 electron.md），设备 web 是纯前端包 |

E1 是本次修正的核心：**宿主与架构正交**。判定顺序应该是
「先判架构（微前端 / 单体双端 / 桌面），再看宿主要不要记进 notes」，而不是拿 `.asp` 当类型依据。

### 3.4 评分

| 分值 | 判据 |
|---|---|
| +5 | `src/main-pc.js` + `src/main-mobile.js` 双入口 |
| +5 | 全仓 `vue.app.js` 计数 = 0（且 `src/` 下有 ≥5 个业务模块目录） |
| +4 | `deps` 无 `single-spa` / `qiankun` / `wujie` / `micro-app` |
| +3 | `package.json` name = `web5.0-framework` |
| +2 | `package-lib.json` 存在 |
| +2 | `autoDependencies` 字段，或 deps 含 `@hc-ui/*` / `@device/*` |
| +1 | `Router/{pc.js,mobile.js}` 成对 |
| +1 | `.dwt/` 存在 |

`≥8` → `device_web`（peitao / transport 实测 ≥18）。
**不再有"压过微前端"的仲裁规则**——宿主标记不参与判型（E1）。

---

## 4. 对 Agent-2 的影响

### 4.1 PC / mobile 双栈必须先分叉

同一份业务代码，两端入口、路由、组件目录都不同。判端依据：
`NODE_ENV`（构建期）或 `sessionStorage.getItem('BrowserType')`（运行期，transport `main-pc.js` 首行写入）。

### 4.2 `device.js` 是设备能力缺陷的定位锚点

```js
this.m_oDeviceCapa = {
  oSnapParamCap: {}, oSettingBasicInfo: {}, customPreviewSplitCfg: {...},
  IoTGatewayCap: {}, bPTZ: false,        // 球机
  bSupportWiper: false,                  // 雨刷
  bSupportManualDeicing: false,          // 手动除冰
  oEagleEye: {...}, oFisheye: { bSupport: false, ... },
}
```

大量"某功能灰掉/不显示"型缺陷的根因是**能力判定字段为 false**，而不是界面代码。
→ `specAtlas` 应把 `device.js` 标为高价值定位点（优先级高于普通 view 文件）。

### 4.3 产物入口不是 html

入口是 `index.asp`（`HtmlWebpackPlugin` 的 `filename: '../index.asp'`）。
任何基于 `index.html` 的入口启发式在此失效。**但注意**：camera 也这样，所以这只能说明"跑在设备上"。

### 4.4 不需要 `modules[]`

设备 web 的产物是**一个包**（peitao `dist/` 129 MB，顶层仅 `index.asp` + `doc/`）。
同仓内的业务模块目录（peitao 5 个 / transport 15 个）是**同一 SPA 内的路由模块**，
没有独立部署边界 → 定位粒度到模块目录即可，不需要子应用清单。

---

## 5. 实现的产出（实测）

```text
peitao     4 entries  src/main-pc.js  src/main-mobile.js  src/router/{pc,mobile}.js
           2 modules  device.js(device_capability)  host-asp(host)
transport  4 entries  src/main-pc.js  src/main-mobile.js  src/Router/{pc,mobile}.js
           3 modules  device.js  jsWebControl(device_bridge)  host-asp
```

`peitao` 的 `device.js` 在 `src/common/vue/service/device.js` —— 比 transport 多一层 `vue/`。
本轮补了 `**/service/device.js` 兜底（N2），否则两个能力对象都抓不到：

```text
雨刷按钮灰掉无法使用  →  top1 = src/common/vue/service/device.js
```

这条正是 §4.2 想要的：能力类缺陷先看能力对象，而不是 view。

`jsWebControl` 只有 transport 有（5.0 新版桥接层）；peitao 走 `common/vue/` 那套。
所以桥接层不能按固定路径找，得按"实际存在的那个"记。

`host-asp` 的 note 固定写 `host=device-asp — not an architecture type`，
提醒它只是宿主标记（README §2.5）。

---

## 6. 复验命令

```bash
cd E:/working_code_webfront/bug-fix-demo-project

# W1：双入口（微前端应为 0）
for r in peitao transport camera/camera hcp/hcp; do
  printf "%-14s main-pc+mobile=%s\n" "$r" \
    "$([ -f $r/src/main-pc.js ] && [ -f $r/src/main-mobile.js ] && echo Y || echo .)"
done

# W2：vue.app.js 计数（设备 web 应为 0）
for r in peitao transport camera/camera hcp/hcp; do
  printf "%-14s vue.app.js=%s\n" "$r" "$(find $r/src -name vue.app.js | wc -l)"
done

# W3：无 single-spa
for r in peitao transport camera/camera; do
  printf "%-14s " "$r"
  python -c "
import json;d=json.load(open(r'$r/package.json'))
print('single-spa:', 'single-spa' in (d.get('dependencies') or {}))"
done

# E1：宿主标记（两个都命中，故不能作判据）
for r in peitao transport camera/camera; do
  printf "%-14s asp=%s project_config=%s\n" "$r" \
    "$(find $r/src -maxdepth 1 -name '*.asp' | wc -l)" \
    "$([ -f $r/src/project_config.json ] && echo Y || echo .)"
done

# E3：peitao 的构建脚本里也有 HCPModule_，但未被调用
grep -n "HCPModule_" peitao/build/helper/build.js
sed -n '60,78p' peitao/build/helper/build.js     # getWebpackEntry 只返回 main-pc/mobile

# E7：两仓 name 相同
python -c "
import json
for r in ('peitao','transport'):
    print(r, json.load(open(r+'/package.json'))['name'])"

# E5：transport 的依赖注入
python -c "import json;print(json.load(open('transport/package.json'))['autoDependencies'])"
```

---

## 7. 回归夹具（建议，未做）

```text
test/fixtures/repos/device-web/
├── package.json                  # name: web5.0-framework + autoDependencies
├── src/
│   ├── index.asp  dispatch.asp
│   ├── project_config.json       # deviceType / pluginVersion / standard
│   ├── package-lib.json
│   ├── main-pc.js  main-mobile.js
│   ├── APP-pc.vue  APP-mobile.vue
│   ├── Router/{pc.js,mobile.js}
│   └── Common/service/device.js  # bSupportWiper / oFisheye / oDeviceCapa
└── build/projectConfig/webpack.config.js   # filename: '../index.asp'
```

**必须同时存在**一个"宿主相同但架构不同"的反例夹具，否则 E1 会复发：

```text
test/fixtures/repos/device-web-host-micro-frontend/    ← 用 camera 抽出来
├── src/index.asp                   # 宿主标记：与 device-web 完全相同
├── src/project_config.json         # 同上
├── src/index.html                  # 但这里有多个 mount div
├── src/<Module>/vue.app.js         # 且每模块有 single-spa 生命周期
└── package.json                    # single-spa + single-spa-vue
```

这个夹具要断言：**判 `micro_frontend`，不是 `device_web`**。
它钉住的正是本次误判。

---

## 8. 待补

- [ ] 更早世代样本（4.5 之外的 3.x / 4.x），确认"双入口"是不是 5.0 才开始
- [ ] mobile 端独立仓的样本（若存在），验证单端仓怎么判
- [ ] `web5.0-framework` 之外的其他设备 web 框架（若有）
