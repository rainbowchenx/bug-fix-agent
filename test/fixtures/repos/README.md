# Agent-2 读码评测夹具

真实产品仓不入库。这里是只保留结构要素的微型仓，用来回归「类型已知之后怎么读」。

生成（改结构时重跑）::

    python test/fixtures/repos/_generate.py

评测入口：`pytest tests/platform/test_cartography_eval.py -q`

| 夹具 | 当作 | 钉住什么 |
|---|---|---|
| `micro-frontend/` | `micro_frontend` | gitmodules + `vue.app.js` 子应用清单；Common 不是微应用 |
| `micro-frontend-in-repo/` | `micro_frontend` | mount div × `vue.app.js`；即使有 `.asp` 也不当 device_web |
| `device-web/` | `device_web` | 双入口 + `device.js` + `jsWebControl` |
| `device-web-host-mf/` | 输入 `micro_frontend` | 宿主标记（asp / project_config）不改类型 |
| `electron/` | `electron_node` | `web/src/main.ts` 是 renderer；IPC → controller |
| `electron-container/` | `electron_node` | 只画 Electron 产品；Koa + `vite-plugin-electron` 不当 Electron |

`eval-cases.json` 是匹配 hit@k 的金标票。跑评测不走 SDK。
