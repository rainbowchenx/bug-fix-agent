---
name: electron-process-boundary
description: Use for Electron bugs that cross main, preload, and renderer.
profiles: electron
---

# Electron Process Boundary

## 适用
Electron 主进程 / preload / 渲染进程之间的崩溃或 IPC 错误。

## 不适用
纯浏览器 Vue 页面、无 Electron 依赖的 Node 库。

## 步骤
1. 确认栈属于 main、preload 还是 renderer。
2. IPC 通道名与参数在两侧对齐。
3. 不要在 renderer 里直接碰 Node API，除非 preload 明确暴露。

## 反例
在渲染进程 `require('fs')` 修一个其实是主进程路径错误。

## 案例
`ipcMain.handle('save')` 与 `ipcRenderer.invoke('save-file')` 名称不一致：统一通道名，而不是关掉 contextIsolation。
