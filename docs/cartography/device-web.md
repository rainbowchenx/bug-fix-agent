# 嵌入设备 web 系列（`device_web`）· 完整分析

样本：`camera/camera`（4.5 代）、`peitao`（5.x / Vue 2）、`transport`（5.x / Vue 3）。
三代同源，**架构换过一次**：4.5 用 single-spa，5.0 弃用改为双入口 + 框架 submodule。

- 契约枚举：`device_web`（`contracts/code_knowledge.py:CartographyProfile`）
- 现有判型：`agents/cartographer/detect.py` —— 根目录名正则，**对三个样本命中 0 次**
- 现有架构图：`agents/cartographer/architecture.py:_map_device_web()` —— 实测无产出

---

## 1. 逐仓走读

### 1.1 camera/camera（V4.5，2021）

| 项 | 值 |
|---|---|
| `package.json` name | `simple-single-spa-webpack-example`（与 hcp/hct 同名，同脚手架） |
| 依赖 | 44 deps / 58 devDeps；`vue 2.6` + `hui 2.15` + **`single-spa 3.8.1` + `single-spa-vue`** + `webpack 4` |
| `project_config.json` | `"version": "V4.5.0build210726"`，`"deviceType": 0`，**无 `standard` 字段** |
| `src/` 模块 | `Application` `Common` `Config` `Download` `IntelligentDisplay` `Playback` `Portal` `Preview` |
| 入口 | `src/index.js`、`src/root-application.js`（**0 字节空文件**）、`index.html`、`index.asp`、`dispatch.asp` |
| 独有 | `test/`、`karma.conf.js`、`tsconfig.json`、`VideoRecorder/`、`depends/`、`eventControl.js`、`.merge_file_a89760`（合并残留） |

**关键**：它用 single-spa，`src/<Module>/vue.app.js` 里 `import singleSpaVue` —— 与微前端的
结构几乎同形。**它是现有实现把它判成 `micro_frontend` 的原因**（见 §4 E1）。

`src/root-application.js` 是 **0 字节**：脚手架残留的空文件，说明 4.5 已经在往"不用 root config"
的方向走，只是没删干净。

### 1.2 peitao（5.x，Vue 2.7）

| 项 | 值 |
|---|---|
| `package.json` name | **`web5.0-framework`** |
| 依赖 | 30 deps / 73 devDeps；`vue 2.7.16` + `hui 2.42.6` + **`hui-mobile 2.3.0-alpha.28`** + `jquery 3.6` + `@huolala-tech/page-spy-browser` |
| `project_config.json` | `"version": "${version} build ${YYYYMMDD}"`，`"deviceType": 1`，`"standard": true`，`"pluginVersion": "V3.0.7.41"` |
| `src/` | `NotSupport` `common`（小写！） `view` `router` `store` + `main-pc.js` / `main-mobile.js` / `main-mixin.js` + `hui.js` / `hui-mobile.js` + `package-lib.json` |
| 构建 | `build/{config,fork,helper,loaders,plugins,projectConfig}`；`file-limit.js`、`.local.config.js` |
| 产物 | `dist/` **129 MB**，顶层仅 `doc/` + `index.asp` |

`src/common` 是小写，而 hcp/hct/hct 是 `src/Common` —— 同公司两套框架的命名习惯不同，
**路径软匹配不能假设大小写**。

### 1.3 transport（5.x，Vue 3）

| 项 | 值 |
|---|---|
| `package.json` name | **`web5.0-framework`**（与 peitao 同名） |
| 依赖 | **deps 只有 1 个**（`hui-intl 3.1.9`），devDeps 只有 1 个（`@device/pocket-mocker`） |
| `autoDependencies` | `{"hui-intl":"3.1.9", "@hc-ui/common":"3.0.2", "@hc-ui/device":"3.0.1", "@hc-ui/platform":"3.0.1"}` ← **依赖靠自定义字段自动注入** |
| `project_config.json` | `"version": "V5.6.0_R0107 build 251111"`，`"deviceType": 31`，`"standard": true`，`"supportBrowser": ["NONIE"]` |
| `src/` | `APP-pc.vue` / `APP-mobile.vue`、`Router/`、`Common/`、`BasicFramework/`(submodule)、`AccessControl` `FaceLibrary` `ParkingRecord` `Playback` `Portal` `Preview` `Radar` `RapidConfig` `SmartShow` `TagSearch` |
| 工具链 | `CLAUDE.md`(221 行) `ai.md`(52 行) `.trellis/` `.claude/` `.mcp.json` `publish.js` `mock_data/` `buildConfig/` |
| `.gitmodules` | 2 条：`src/BasicFramework`（框架）、`.trellis/spec/FrontendCommon`（规范）→ **都不是应用模块** |

**`package.json` 几乎不列依赖**是个陷阱：靠 `deps` 判断技术栈在这类仓会直接失明。
`autoDependencies` 是这套框架的私有字段。另外 `BasicFramework` 的 gitlab 路径
（`.../IPSC/Integration/DeviceWeb/deviceweb5.0/basicframeworkplus.git`）里直接写着 **DeviceWeb**。

---

## 2. 结构

```text
<repo>/
├── src/index.asp                ← 构建产物入口**是 .asp 而不是 .html**
├── src/dispatch.asp             ← URL 转发/跳转页
├── src/index.html               ← 开发期占位，产物不用它
├── src/project_config.json      ← 设备配置（deviceType / pluginVersion / standard / theme / localService），随产物下发
├── src/package-lib.json         ← 额外三方库白名单（peitao: ip6/ipaddr/jquery-qrcode/node-forge；transport: layDate）
├── src/main-pc.js               ← 5.0 PC 入口（Vue3: createApp）
├── src/main-mobile.js           ← 5.0 mobile 入口
├── src/main-mixin.js            ← 第三种入口（peitao 默认分支）
├── src/APP-pc.vue / APP-mobile.vue   ← 两个根组件
├── src/Router/{pc,mobile}/      ← 两套路由
├── src/Common/service/device.js ← 设备能力对象（PTZ / 雨刷 / 除冰 / 鱼眼 / 鹰眼 / IoT 网关）
├── src/Common/libs/jsWebControl/← 真正的前端控件桥接层
└── build/projectConfig/webpack.config.js
      filename: '../index.asp'                      ← HtmlWebpackPlugin 直接产出 .asp
      template: <root>/index.asp
      copy: dispatch.asp → ./dispatch.asp
```

### 2.1 为什么是 `.asp`

页面由**设备内置 HTTP 服务**托管，`.asp` 是该服务的页面入口扩展名。构建直接把 HTML 模板
输出成 `.asp`：

```js
// peitao/build/projectConfig/webpack.config.js:40-41
filename: '../index.asp',
template: path.join(PROJECT_ROOT_PATH, 'index.asp'),
```

→ 任何"从 `index.html` 追入口"的启发式在这类仓全部失效。

### 2.2 双端构建：一次只打一端

```js
// peitao/build/helper/build.js:60-78
function getWebpackEntry() {
  if (process.env.NODE_ENV === 'pc')     return { 'main-pc':     [ .../main-pc.js ] };
  if (process.env.NODE_ENV === 'mobile') return { 'main-mobile': [ .../main-mobile.js ] };
                                         return { 'main-mixin':  [ .../main-mixin.js ] };
}
```

对应 `scripts`：`dev:pc` / `dev:mobile` / `dev:APP`（`NODE_ENV=mobile` + 端口/名称参数）。
**PC 与 mobile 的入口、路由、组件树都不同**（`Common/components/pc` vs `/mobile`）。

### 2.3 与微前端最本质的区别：产物形态

| | 微前端（hcp） | 设备 web（peitao） |
|---|---|---|
| 产物 | N 个可独立部署的 UMD（`HCPModule_<App>`） | **一个包**（`dist/index.asp` + assets） |
| 仓内模块 | 独立 git 仓 submodule，可单独发版 | 同一 SPA 内的路由模块 |
| 构建单位 | 一次打一个子应用 | 一次打一个端（pc/mobile） |
| 部署 | 主应用 + 子应用分别上线 | 整包烧进设备固件/升级包 |

`src/AccessControl`、`src/Portal` 在设备 web 里**不是**可独立部署的子应用。

---

## 3. 判据

### 3.1 强判据（命中即定型）

| # | 判据 | 设备 web | 微前端 | 说明 |
|---|---|---|---|---|
| T1 | **`src/*.asp` 存在**（`index.asp` / `dispatch.asp`） | 3/3 | **0/2** | 五仓完美分离，最高优先级 |
| T2 | **`src/project_config.json` 存在**且含 `deviceType` / `pluginVersion` | 3/3 | **0/2** | 设备配置随产物下发 |
| T3 | HtmlWebpackPlugin 的 `filename` 以 `.asp` 结尾 | ✅ | ✗ | 比 T1 更强：证明 ASP 是**构建产出**而非历史遗留 |
| T4 | deps 含 `@hc-ui/device`，或 `name` 为 `web5.0-framework` | transport ✅ / peitao ✅ | ✗ | 内部包名，仓特异 |

### 3.2 弱判据（需组合，≥2 条）

| # | 判据 | 说明 |
|---|---|---|
| U1 | 同时存在 `src/main-pc.js` + `src/main-mobile.js` | 5.0 双目标（4.5 无，故非强判据） |
| U2 | `src/package-lib.json` | 4.5 无 |
| U3 | `Common/service/device.js` 含 `bSupportWiper` / `oFisheye` / `oEagleEye` / `oDeviceCapa` | 语义强但**极易被管理平台误伤**，见 E2 |
| U4 | devDep 含 `@device/*` scope | 内部工具域 |
| U5 | 存在 `.dwt/`（`.dwt/cspace`、`.dwt/hirule`） | 内部工具链残留目录 |
| U6 | `project_config.json` 含 `"standard": true` | 5.0 标志；4.5 无（样本少，仅加分） |
| U7 | `package.json` 有 `autoDependencies` 字段 | 框架私有的依赖注入机制 |

### 3.3 反例

| # | 反例 | 实测证据 |
|---|---|---|
| **E1** | **`single-spa` + 子模块 `vue.app.js`** | `camera` 是设备 web，却有 `single-spa@3.8.1`、`src/<Module>/vue.app.js`、`root-application.js` → 被现有实现判成 `micro_frontend` |
| **E2** | **设备语义 / ISAPI 调用** | hcp（微前端）有 **128** 个设备能力文件、**1205** 个 ISAPI 文件——它是**管理设备的平台**。设备语义无法区分类别 |
| **E3** | `root-application.js` 存在 | hcp ✓、hct ✓、camera ✓ —— 跨两类，无区分力 |
| **E4** | `.gitmodules` 存在 | transport 也有，但内容是框架（`BasicFramework`）与规范（`.trellis/spec`），不是应用模块 |
| **E5** | 文件存在 ≠ 有内容 | `camera/src/root-application.js` 是 **0 字节**空文件 |
| **E6** | 桥接层目录名 | 真实桥接层叫 `Common/libs/jsWebControl/`，**不匹配** `bridge` / `jsbridge` / `webview` / `native-api` 任何正则 |
| **E7** | `deps` 少就以为不是前端项目 | transport deps 只有 1 个，靠 `autoDependencies` 注入 |

E1 是这套判据最贵的一课：**单看框架名（single-spa / Vue / webpack）永远分不开微前端与设备 web**，
因为两者共用同一套内部脚手架（三个仓 `package.json` 的 `name` 都叫 `simple-single-spa-webpack-example`）。
真正的分水岭是**部署形态**：谁托管产物、产物入口是什么扩展名。

### 3.4 评分

| 分值 | 判据 |
|---|---|
| +5 | `src/*.asp` 存在 |
| +4 | HtmlWebpackPlugin `filename` 以 `.asp` 结尾 |
| +4 | `src/project_config.json` 含 `deviceType` / `pluginVersion` |
| +3 | `main-pc.js` + `main-mobile.js` 双入口 |
| +2 | deps 含 `@hc-ui/device` 或 `@device/*`，或 `name` 为 `web5.0-framework` |
| +2 | `Common/service/device.js` 含 `bSupportWiper` / `oFisheye` / `oEagleEye` |
| +1 | `.dwt/` 或 `package-lib.json` 或 `autoDependencies` 存在 |

`≥8` → `device_web`（peitao / transport ≥13，camera 5+4+4=13）。

**冲突仲裁**：`device_web` 命中 T1 时**压过** `micro_frontend` —— camera 就是判据。

---

## 4. 对 Agent-2 的影响

### 4.1 PC / mobile 双栈必须先分叉

同一份业务代码，两端入口、路由、组件目录都不同。**先判端，否则在两套相似代码间乱跳**。
判端依据：`NODE_ENV`（构建期）或 `sessionStorage.getItem('BrowserType')`（运行期，
transport `main-pc.js` 首行写入）。

### 4.2 `device.js` 是设备能力缺陷的定位锚点

`Common/service/device.js` 维护 `oDeviceCapa` 能力对象：

```js
this.m_oDeviceCapa = {
  oSnapParamCap: {}, oSettingBasicInfo: {}, customPreviewSplitCfg: {...},
  IoTGatewayCap: {}, bPTZ: false,        // 球机
  bSupportWiper: false,                  // 雨刷
  bSupportManualDeicing: false,          // 手动除冰
  bLaserDecingMutex: false,
  oEagleEye: {...},                      // 鹰眼
  oFisheye: { bSupport: false, ... },    // 鱼眼
  ...
}
```

大量"某功能灰掉/不显示"型缺陷的根因是**能力判定字段为 false**，而不是界面代码。
→ `specAtlas` 应把 `device.js` 标为高价值定位点（优先级高于普通 view 文件）。

### 4.3 产物入口不是 html

入口是 `index.asp`，由 `build/projectConfig/webpack.config.js` 生成。
`index.html` 只在开发期存在。

### 4.4 不需要 `modules[]`

微前端产物是 N 个可独立部署的 UMD；设备 web 产物是**一个包**。
同仓内的 `src/AccessControl`、`src/Portal` 是**同一 SPA 内的路由模块**，
定位粒度到模块即可，不需要子应用清单（与微前端相反）。

### 4.5 大小写不一致

peitao 用 `src/common`（小写），camera / transport 用 `src/Common`。
路径软匹配不能假设大小写，Windows 上尤其隐蔽（文件系统不区分，CI 上才炸）。

---

## 5. 现有实现的产出（实测）

```text
peitao     profile unknown         modules [('.', 'repo_root')]
transport  profile unknown         modules [('.', 'repo_root')]
camera     profile micro_frontend  modules [('mf', 'micro_frontend_root')]   ← 错类
```

两个根因：

1. `BRIDGE` 正则（`bridge|jsbridge|device-web|webview|native-?api`）对五个真实仓
   **命中 0 次** → `device_web` 是死分支（D8）。
2. camera 因 `single-spa` 被判 `micro_frontend`（D9）——正好暴露"框架名当判据"的荒谬。

---

## 6. 复验命令

```bash
cd E:/working_code_webfront/bug-fix-demo-project

# T1 / T2：五仓对比，微前端应全为 0
for r in hcp/hcp hct/hct peitao transport camera/camera; do
  printf "%-14s asp=%s cfg=%s\n" "$r" \
    "$(find $r/src -maxdepth 1 -name '*.asp' | wc -l)" \
    "$([ -f $r/src/project_config.json ] && echo Y || echo .)"
done

# T3：.asp 是构建产出
grep -n "filename\|template\|dispatch.asp" peitao/build/projectConfig/webpack.config.js

# U1：双端入口按 NODE_ENV 分叉
sed -n '60,78p' peitao/build/helper/build.js

# E1：camera 是设备 web，却在用 single-spa
grep -rn "single-spa-vue" camera/camera/src --include="*.js" | head
head -c 200 camera/camera/src/project_config.json

# E2：设备语义无区分力（微前端的 ISAPI 文件比设备 web 还多）
for r in hcp/hcp transport camera/camera; do
  printf "%-14s ISAPI=%s\n" "$r" \
    "$(grep -rl ISAPI $r/src --include='*.js' --include='*.vue' | wc -l)"
done

# E5：空文件陷阱
wc -c camera/camera/src/root-application.js     # 0

# E6：真实桥接层不匹配 BRIDGE 正则
ls camera/camera/src/Common/vue/libs/jsWebControl/

# E7：deps 失明
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
│   └── Common/service/device.js  # bSupportWiper / oFisheye / oDeviceCapa
└── build/projectConfig/webpack.config.js   # filename: '../index.asp'

test/fixtures/repos/device-web-single-spa/     ← 反例夹具，防回归
├── package.json                  # single-spa + single-spa-vue
├── src/root-application.js       # 0 字节，复刻 E5
├── src/<Module>/vue.app.js       # import singleSpaVue
└── src/index.asp                 # 有 .asp → 必须判 device_web 而非 micro_frontend
```

第二个夹具是本类型最有价值的产出：把 E1 钉成永久的回归测试，
确保"看到 single-spa 就判微前端"这类错误不会复活。
