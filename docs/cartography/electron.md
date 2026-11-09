# Electron 系列（`electron_node`）· 待补样本

样本：**无**。本文只记录现状与待采集清单，不提前编判据。

- 契约枚举：`electron_node`（`contracts/code_knowledge.py:CartographyProfile`）
- 现有判型：`agents/cartographer/detect.py` —— `deps` 含 `electron` / `electron-builder` / `electron-vite`
- 现有架构图：`agents/cartographer/architecture.py:_map_electron()`

---

## 1. 现有实现

```python
# detect.py
if "electron" in deps or "electron-builder" in deps or "electron-vite" in deps:
    profile = "electron_node"          # ← 无条件赋值，会覆盖其他分支（README D1）
    frameworks.add("electron")
    hints.append(f"{rr.path}:electron")
```

这条判据本身是三类里**最可靠**的：`electron` 出现在主依赖里，几乎不存在同名误判。
它的风险不在准不准，而在**优先级**——`profile = "electron_node"` 是无条件赋值，
多仓混合时结果取决于目录遍历顺序，而另两个分支都有 `if profile == "unknown"` 保护。

```python
# architecture.py:_map_electron()
modules.append(ArchModule(id=f"{repo_path}:electron", path=repo_path or ".", role="electron_app"))
```

架构图只产出一个 `electron_app` 节点，**没有任何进程边界信息**——而 Electron 的价值恰恰在边界。

---

## 2. 待采集清单

每个仓按 README §1 的七步流程走，重点：

### 2.1 进程边界（Electron 的定位核心）

- [ ] 主进程入口（`package.json` 的 `main`、`electron/main.ts`、`background.js`）
- [ ] 预加载脚本（`preload.ts` / `preload.js`）位置与数量
- [ ] 渲染进程入口（`index.html`、`renderer/`）
- [ ] 是否有多窗口（`BrowserWindow` 数量与用途）
- [ ] 是否有 utility process / worker

### 2.2 安全配置（影响缺陷归类）

- [ ] `nodeIntegration` / `contextIsolation` / `sandbox` 取值
- [ ] `contextBridge.exposeInMainWorld` 暴露了哪些 API（对应"桥接层"在微前端/设备 web 里的角色）

### 2.3 IPC 通道

- [ ] `ipcMain.handle` / `ipcRenderer.invoke` 的通道命名约定
- [ ] 通道清单 → 类似微前端的 `loadModuleExports` 图（跨进程耦合是主要根因）

### 2.4 构建与打包

- [ ] 打包器（electron-builder / electron-forge / electron-vite）
- [ ] 产物形态（asar / 目录 / 安装包），是否有自动更新（`electron-updater`）
- [ ] 是否有 `native` 模块（`.node`），影响跨平台与升级

### 2.5 反例（必须主动去找）

- [ ] 仅有 `electron` 出现在 `devDependencies` 但未使用的仓
- [ ] **套壳 Electron 的微前端**：Electron 壳加载远程/本地微前端页面（此时"部署形态"该判哪类？）
- [ ] Tauri / NW.js 等其他桌面壳，避免把"桌面应用"等同于 Electron
- [ ] 纯 Web 项目但依赖里带 `electron`（例如仅用于截图/e2e 的 devDep）

第 2 项是本类最可能出现的混淆，与 device-web.md 的 E1（camera 用 single-spa 却是设备 web）
是同一类错误的镜像：**壳（容器）与内容（应用）是两个维度**。

---

## 3. 与另两类的交叉风险

| 交叉场景 | 需要判什么 |
|---|---|
| Electron 壳 + 微前端页面 | 壳是 Electron，页面是 micro_frontend —— 契约只能填一个值，需明确填哪个（倾向填壳，并在 `notes` 记录内层） |
| Electron 壳 + 设备 web 页面 | 同上 |
| 微前端子应用跑在 Electron 里 | 同上 |

这个"容器 vs 内容"的问题在看完 electron 样本后需要单独决策，可能要在契约里
加一个 `container` 字段，或约定 `cartographyProfile` 只描述**被分析代码本身**。

---

## 4. 状态

```text
样本数        0
判据成熟度    —
落码状态      现有 1 条可用，但优先级需按 README §3 的仲裁表修正
```
