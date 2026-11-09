---
name: vue-debug
description: Use for Vue/Vite UI bugs — reactivity, lifecycle, router, and template errors.
profiles: node-web
---

# Vue Debug

- Check template null access, `v-if` vs `v-show`, and async setup timing.
- Inspect composables and Pinia/Vuex stores for shared state races.
- Prefer fixing the data flow over silencing template errors.
- For Vite apps, consider HMR-only issues vs true runtime bugs.

## 适用
Vue/Vite 页面崩溃、渲染空白、响应式不更新。

## 不适用
纯 Node 库、Electron 主进程崩溃。

## 步骤
1. 从页面路由或组件名定位 SFC。
2. 检查 `v-if` 空值与 async setup。
3. 只改数据流，不关模板告警。

## 反例
用 `v-show` 掩盖空引用，而不是修数据。

## 案例
登录页 `user.name` 在 user 未加载时抛错：在模板加 `v-if="user"`，而不是 `user!.name`。
