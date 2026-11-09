# 仓型指纹（Cartography Profile Fingerprints）

Agent-2 第一步是**判仓型**：`micro_frontend` / `electron_node` / `device_web` / `unknown`。
这份文档记录每一类的**可验证代码特征**——不是印象，是能写进 `detect.py` 的判据。

状态：

| 类型 | 样本 | 判据成熟度 | 实现状态 |
|---|---|---|---|
| `micro_frontend` | hcp / hct（2 个真实仓） | ✅ 强/弱/反例齐备，含评分建议 | ⏳ 判据未落 `detect.py` |
| `electron_node` | 待补 | — | 现有 1 条（deps 含 electron） |
| `device_web` | 待补（**现状判据最弱、误伤最高**） | — | 现有 1 条（目录名正则） |

判据落码前先攒样本：只有一类样本时刻度阈值，必然过拟合这一类的目录命名习惯。

---

## 0. 现行实现与已确认缺陷

判型在 `bugfix_agent/agents/cartographer/detect.py:detect_cartography_profile()`，
架构图在 `agents/cartographer/architecture.py:_map_*()`。用真实微前端仓实测，
**判型对、架构图全空**——错在两个不同的地方。

### 判型侧（`detect.py`）

| # | 缺陷 | 后果 |
|---|---|---|
| D1 | 循环里 `profile = "electron_node"` 无条件赋值 | 多仓混合时结果取决于目录遍历顺序；`micro_frontend` / `device_web` 却有 `if profile == "unknown"` 保护，三者优先级不自洽 |
| D2 | 微前端只认 `single-spa` / `@single-spa/devtools` | qiankun / wujie / micro-app / Module Federation / iframe 主子应用全判 `unknown` |
| D3 | `device_web` 靠根目录名匹配 `bridge\|jsbridge\|device-web\|webview` | 微前端仓内 `src/CsEmbed`、`src/DevCall`、`src/MobileSureillance` 均命中 → 误伤；命名习惯一变就全错 |

### 架构图侧（`architecture.py`）

| # | 缺陷 | 后果（实测 hcp） |
|---|---|---|
| D4 | `discover_repo_roots()` 只扫根 + **深度 1** | submodule 在 `src/<App>`（深度 2）→ 55 个子应用全部不可见，`repoRoots` 只有 `['.']` |
| D5 | `SPA_APP = r"(?:^\|/)(?:apps?\|packages?\|micro)/([^/]+)/"` | 该仓用 `src/<App>/`，正则不匹配 → `modules` 只剩兜底 `[(mf, micro_frontend_root)]` |
| D6 | `_map_micro_frontend` 用 `if "registerApplication" in f` 判断 shell——`f` 是**文件路径** | 永远不成立。该字符串真实出现在文件**内容**里（`src/Common/libs/light-front/globalApi.js`、`build/helper/build.js`）→ `entryPoints` 恒为空 |
| D7 | `_list_src_rel(limit=400)` | 该仓 `src/` 下 10330 个源码文件，只看得到 3.9%，且截断按字母序（BI/AccessControl/Attendance…）→ 即使 D5 修好，55 个子应用仍只看得到前 ~7 个 |

实测复现（仓库根执行）：

```bash
python -c "
from bugfix_agent.agents.cartographer.detect import discover_repo_roots
from bugfix_agent.agents.cartographer.architecture import map_architecture
wd = r'E:\working_code_webfront\bug-fix-demo-project\hcp\hcp'
rr = discover_repo_roots(wd)
print(discover_repo_roots.__module__)
print([r.path for r in rr])
"
# 输出： repoRoots ['.']
#        summary  'Micro-frontend shell/app map (apps|packages heuristics)'
#        entries  []
#        modules  [('mf', 'micro_frontend_root')]
```

结论：**判型正确是运气**（根 `package.json` 恰好有 `single-spa`），架构图则完全没工作。

---

## 1. 微前端系列（`micro_frontend`）

### 1.1 样本

| 样本仓（不入库） | 形态 | 规模 |
|---|---|---|
| `bug-fix-demo-project/hcp/hcp` | 宿主壳 + 55 个 submodule 子应用 | `src/Common` 552 文件，`src/` 共 10330 源码文件 |
| `bug-fix-demo-project/hct/hct` | 同模板另一产品线，21 个 submodule | 额外依赖 `hui-mobile`，PC/H5 双栈更明显 |

**两个仓是同一模板的两条产品线**，不是两个独立项目：

```text
package.json   name 都叫 simple-single-spa-webpack-example，scripts 逐条相同
               dev:HCC / dev:HCT / dev:HCL / dev:HCP  ← 四个产品线开关
build/         完全相同，build/config/{HCC,HCL,HCP,HCT}/ 四份产品线配置
.gitmodules    不同：hcp 55 条（src/Person），hct 21 条（src/HCBPerson）
依赖           仅 light-front 版本不同（0.8.5 vs 1.0.4）
```

→ 同一缺陷可能在两仓都存在（共用 `Common`），也可能只在一条产品线。
**「仓」不是唯一身份，「产品线」是第二个维度**，不能假设一仓=一项目。

### 1.2 结构：三层嵌套

```text
hcp/hcp/                              ← 宿主壳（shell / root config）
├── src/root-application.js           ← 真入口：按 nature=h5 分流 mobile / PC
│     if (nature === 'h5') import('@/Common/mobile/init');
│     else                 import('@/Common/init/[project]/index');
├── src/Common/                       ← 共享内核（552 文件）
│   ├── init/{hcp,hcc}/               ← 产品线专属启动
│   └── service/utils/regist.app.js   ← 统一注册器（app.use 批量注入）
├── src/<App>/                        ← 55 个 git submodule，每个是独立仓
│   ├── autoloader.js                 ← export default () => import('./vue.app.js')
│   ├── vue.app.js                    ← createApp + registApp(app)
│   ├── exportComponents.js           ← 向其他子应用暴露 Vue 组件
│   └── exportData.js                 ← 向其他子应用暴露数据/方法
├── build/config/modules.js           ← 子应用构建清单
└── build/helper/build.js             ← getWebpackEntry()：单次只打一个子应用，UMD 输出
```

子应用产出的入口清单长这样（`build/config/modules.js`）：

```js
Portal: ["vue.app.js", "exportComponents.js", "exportData.js"],
// 多数模块是这三件套；带 mobile/vue.app.js 的额外有移动端入口
```

### 1.3 强判据（命中即定型）

| # | 判据 | 观测值 | 备注 |
|---|---|---|---|
| S1 | `deps` 含 `single-spa` + `single-spa-vue` | ✅ / ✅ | 现 `detect.py` 只有这一条；只覆盖一种方案（见 D2） |
| S2 | **`.gitmodules` 中 ≥3 条 submodule path 落在 `src/`** | 55 / 21 | 单条即几乎确定，**零成本**（读一个文本文件），且对 qiankun/MF 同样成立 |
| S3 | `build/config/modules.js` 存在，值为「模块名 → 入口文件数组」 | ✅ / ✅ | 比依赖名更能区分「微前端壳」与「普通多页应用」 |
| S4 | 子目录存在 `autoloader.js` 且内容为 `export default () => import('./vue.app.js')` | ✅ / ✅ | 多子应用同时出现即强 |

**优先用 S2**：`.gitmodules` + `src/` 前缀的组合对框架方案不敏感，比解析依赖更快，也不受 `node_modules` 未安装影响。

### 1.4 弱判据（需组合，≥2 条）

| # | 判据 | 说明 |
|---|---|---|
| W1 | 子目录成对出现 `exportComponents.js` + `exportData.js` | 子应用对外接口约定 |
| W2 | 存在统一注册器（批量 `app.use`），子应用不自建 app | 宿主注入依赖的标志 |
| W3 | webpack `libraryTarget: 'umd'` + `library: <PRODUCT>Module_<App>` | 产物命名约定 |
| W4 | 构建脚本按 env 变量选入口（`getWebpackEntry()` / `getCurrentApp()`） | 单次只打一个子应用 |
| W5 | 依赖内部框架 `light-front` / `light-front-vue` / `hybrid-webframework` | 仓特异性极强，本仓群独有 |

### 1.5 反例（**不可**作为微前端判据）

| # | 反例 | 为什么危险 |
|---|---|---|
| E1 | `vue` + `vue-router` + `webpack` | 普通 Vue SPA 全有 |
| E2 | `element-plus` / `hui-intl` | 公司通用 UI 库，三类仓都可能用 |
| E3 | **子目录里有 `package.json`** | `src/CsEmbed/package.json`（`name: web-server`，`vue-cli-service`）是嵌进微前端的独立应用。子目录有 package.json ≠ 微前端 |
| E4 | `hybrid-webframework` | hcp 用它只取 `DebugTool`；嵌入设备 web 也可能用同名桥 → **跨类歧义，不能单独作为任何一类的判据** |
| E5 | `single-spa` 仅在 `devDependencies` | 有些仓装了但未用 |
| E6 | 目录名含 `bridge` / `webview` / `mobile` | hcp 内 `CsEmbed`、`DevCall`、`MobileSureillance` 均命中 → 正是 D3 误伤来源 |

### 1.6 评分建议（落码时用，取代 if 链）

| 分值 | 判据 |
|---|---|
| +5 | `.gitmodules` 中 `src/` 下 submodule ≥3 |
| +4 | deps 含 `single-spa` / `qiankun` / `wujie` / `micro-app` / `@module-federation/*` |
| +3 | `build/config/modules.js` 式模块清单存在 |
| +2 | 子目录成对出现 `exportComponents.js` + `exportData.js` |
| +2 | 依赖 `light-front` / `light-front-vue`（内部框架，仓特异） |
| +1 | UMD library 命名 `<X>Module_<App>` |

`≥6` → `micro_frontend`（hcp/hct 实测 5+4+3+2+2 = 16）。
同时 **D3 降级**：目录名类判据只在 `micro_frontend` 与 `electron_node` 都未命中时才生效；
**D1 修正**：改为累加分数，不做无条件覆盖。

### 1.7 对 Agent-2 的四个真实影响

比"判型"本身更要紧——判对了也不代表能定位。

**① 定位粒度必须落到子应用，不能停在仓级**

`defectCodeMatches[]` 现在是仓内路径。这类仓的正确粒度是
`仓 hcp/hcp → 子应用 src/Anpr → src/Anpr/view/x.vue`。
缺陷单的 `testModule` 与子应用名高度相关（`报警推送` ↔ `src/Event`、`人员管理` ↔ `src/Person`）。
→ `specAtlas` 需显式记录 `modules[]`：子应用名 / 路径 / 入口文件 / 是否已 checkout。

**② 跨子应用耦合是主要根因**

实测 `loadModuleExports(...)` 调用分布：

```text
loadModuleExports('Person'       )  106 次
loadModuleExports('Resource'     )   46 次
loadModuleExports('Map'          )   12 次
loadModuleExports('VehicleManage')    8 次
loadModuleExports('Attendance'   )    6 次
```

`Person` 被 106 处跨模块引用 → **现象在 A 子应用、根因在 B 子应用**是常态，单文件定位几乎注定失败。
→ 建议把 `loadModuleExports('X','exportData','fn')` 建成跨模块引用图，作为 `match.py` 的加边依据。

**③ 一个仓里两种形态：PC + H5**

```js
// src/root-application.js
if (nature === 'h5') { import('@/Common/mobile/init'); }
else                 { import('@/Common/init/[project]/index'); }
```

hct 另带 `hui-mobile@3.0.0-alpha.21`，`src/*/mobile/vue.app.js` 是独立入口。
→ 定位前须先判 PC / H5，否则会在两套相似但不同的代码间乱跳。

**④ `@/` 别名不是单层映射**

`build/config/{HCP,HCT,HCL,HCC}/config.js` 里 `@/Common/*` 与其他 `@/*` 走**不同输出路径**。
→ 任何"`@` = `src`"的推断在此会偏差。

### 1.8 复验命令

```bash
cd E:/working_code_webfront/bug-fix-demo-project/hcp/hcp

# S2：子应用清单与数量
grep -c '^\[submodule' .gitmodules
grep -A1 '^\[submodule' .gitmodules | grep 'path =' | head

# S3：子应用构建清单
head -40 build/config/modules.js

# S4：子应用入口约定
cat src/Anpr/autoloader.js
head -20 src/Anpr/vue.app.js

# 跨模块耦合强度
grep -rn "loadModuleExports(" src --include="*.js" --include="*.vue" \
  | grep -o "loadModuleExports('[A-Za-z]*'" | sort | uniq -c | sort -rn

# D4/D5/D6/D7 复现
cd E:/working_code_webfront/ai/bug-fix-agent && python -c "
from bugfix_agent.agents.cartographer.detect import discover_repo_roots
from bugfix_agent.agents.cartographer.architecture import map_architecture
wd = r'E:\working_code_webfront\bug-fix-demo-project\hcp\hcp'
print(map_architecture(wd, discover_repo_roots(wd), 'micro_frontend'))"
```

### 1.9 回归夹具（建议，未做）

两个样本仓几百 MB 且 submodule URL 指向内部域名，**不入库**。
建议把人造微型夹具入库（约 20 文件），只保留判据要素：

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

用途：让 D4~D7 的修复有测试保护，且新增 electron / device_web 夹具时同构。

---

## 2. Electron 系列（`electron_node`）

现状判据：`deps` 含 `electron` / `electron-builder` / `electron-vite`。

待补样本后填写：主/预加载/渲染进程边界、IPC 通道命名、`nodeIntegration` / `contextIsolation` 配置、
打包器与产物结构。**已知风险**：D1（无条件覆盖）会与微前端判据互相压制。

---

## 3. 嵌入设备 web 系列（`device_web`）

现状判据：**只有**根目录名正则 `bridge|jsbridge|device-web|webview`。三类中判据最弱、误伤最高（见 D3 / E6）。

待补样本后填写：JSBridge 协议层位置、宿主容器特征、`window.xxxBridge` 注入点、
离线/低性能约束痕迹。**至少需要一个反例样本**证明它不会被误判成微前端。

---

## 4. 待决策

| # | 问题 | 倾向 |
|---|---|---|
| 1 | `CodeKnowledge` 要不要加 `modules[]`（子应用清单）与 `productLine`？ | 需要，定位必需；现在只有 `cartographyProfile` |
| 2 | hcp / hct 算同类还是两类？ | 同类（均 `micro_frontend`），产品线差异由 `modules[]` 表达 |
| 3 | 评分判据何时落 `detect.py`？ | 三类样本齐了再落，否则阈值过拟合单一类 |
| 4 | 夹具放 `test/fixtures/repos/` 是否与现有 `test/fixtures/defect-batch/` 并列？ | 是，同构命名 |

### 已挂账的实现修复（与判据无关，纯 bug）

- D4 `discover_repo_roots` 深度 1 → 需支持 submodule（读 `.gitmodules` 而非靠目录扫描）
- D5 `SPA_APP` 正则不认 `src/<App>/`
- D6 shell 判定读路径而非文件内容
- D7 `_list_src_rel` 400 上限对 10k+ 文件仓截断且偏字母序
