"""Regenerate miniature cartography fixtures (no real product repos).

Run from repo root::

    python test/fixtures/repos/_generate.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _w(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace("\r\n", "\n"), encoding="utf-8")


def _plant_git(base: Path, *, head: str = "a" * 40) -> None:
    """Fake ``.git`` so ``discover_repo_roots`` treats the fixture as a real repo.

    Nested ``.git`` cannot be committed into this monorepo; regenerate (or the
    pytest session fixture) must re-plant these markers after clone.
    """
    _w(base / ".git/HEAD", "ref: refs/heads/main\n")
    _w(base / ".git/refs/heads/main", head[:40] + "\n")


def _vue_app(module: str, el: str) -> str:
    return (
        "import singleSpaVue from 'single-spa-vue';\n"
        f"// {module} mount\n"
        f'export const el = "#{el}";\n'
        "export default { el };\n"
    )


def write_micro_frontend() -> None:
    base = ROOT / "micro-frontend"
    _plant_git(base)
    _w(
        base / "package.json",
        json.dumps(
            {
                "name": "simple-single-spa-webpack-example",
                "dependencies": {
                    "vue": "3.5.0",
                    "single-spa": "5.5.0",
                    "single-spa-vue": "1.5.0",
                },
            },
            indent=2,
        )
        + "\n",
    )
    _w(
        base / ".gitmodules",
        """[submodule "src/Person"]
	path = src/Person
	url = git@example.com:Person.git
[submodule "src/AppA"]
	path = src/AppA
	url = git@example.com:AppA.git
[submodule "src/AppB"]
	path = src/AppB
	url = git@example.com:AppB.git
""",
    )
    _w(
        base / "build/config/modules.js",
        """module.exports = {
  Portal: ["vue.app.js", "exportComponents.js", "exportData.js"],
  Person: ["vue.app.js", "exportComponents.js", "exportData.js"],
  AppA: ["vue.app.js", "exportComponents.js", "exportData.js"],
  AppB: ["./mobile/vue.app.js"],
  CsEmbed: [],
};
""",
    )
    _w(
        base / "src/root-application.js",
        """if (nature === 'h5') {
  import('@/Common/mobile/init');
} else {
  import('@/Common/init/hcp/index');
}
""",
    )
    _w(
        base / "src/index.html",
        """<!doctype html>
<div id="person"></div>
<div id="appa"></div>
<div id="appb"></div>
""",
    )
    _w(
        base / "src/Common/service/utils/utils.js",
        "export function loadModuleExports(name) { return name; }\nloadModuleExports('Person');\n",
    )
    _w(base / "src/Common/person-utils.js", "export const personHelper = 1;\n")
    _w(base / "src/Common/mobile/init.js", "export const h5Init = 1;\n")
    _w(base / "src/Common/init/hcp/index.js", "export const pcInit = 1;\n")
    for name, el in (("Person", "person"), ("AppA", "appa"), ("AppB", "appb")):
        _w(base / f"src/{name}/vue.app.js", _vue_app(name, el))
        _w(base / f"src/{name}/autoloader.js", f"export default () => import('./vue.app.js');\n")
        _w(base / f"src/{name}/exportComponents.js", "export default {};\n")
        _w(base / f"src/{name}/exportData.js", "export default {};\n")
    _w(base / "src/Person/view/index.vue", "<template><div>Person</div></template>\n")
    _w(base / "src/AppB/mobile/vue.app.js", _vue_app("AppBMobile", "appb-mobile"))
    _w(
        base / "src/VehicleManage/person-list.vue",
        "<template><div>decoy person list</div></template>\n",
    )


def write_micro_frontend_in_repo() -> None:
    base = ROOT / "micro-frontend-in-repo"
    _plant_git(base)
    _w(
        base / "package.json",
        json.dumps(
            {
                "name": "simple-single-spa-webpack-example",
                "dependencies": {"vue": "2.6.14", "single-spa": "3.8.1", "single-spa-vue": "1.0.0"},
            },
            indent=2,
        )
        + "\n",
    )
    _w(base / "src/index.asp", "<%@ language=\"javascript\" %>\n")
    _w(
        base / "src/project_config.json",
        json.dumps({"version": "V4.5.0", "deviceType": 0}, indent=2) + "\n",
    )
    _w(
        base / "src/index.html",
        """<!doctype html>
<div id="preview"></div>
<div id="playback"></div>
<div id="portal"></div>
""",
    )
    _w(base / "src/root-application.js", "")  # empty shell leftover
    for name, el in (("Preview", "preview"), ("Playback", "playback"), ("Portal", "portal")):
        _w(base / f"src/{name}/vue.app.js", _vue_app(name, el))
        _w(base / f"src/{name}/autoloader.js", "export default () => import('./vue.app.js');\n")
    _w(base / "src/Common/service/device.js", "export const hostOnly = true;\n")
    _w(base / "src/Preview/view/player.vue", "<template><div>preview</div></template>\n")


def write_device_web() -> None:
    base = ROOT / "device-web"
    _plant_git(base)
    _w(
        base / "package.json",
        json.dumps(
            {
                "name": "web5.0-framework",
                "dependencies": {},
                "autoDependencies": {"hui-intl": "3.1.9"},
            },
            indent=2,
        )
        + "\n",
    )
    _w(base / "src/index.asp", "<%@ language=\"javascript\" %>\n")
    _w(base / "src/dispatch.asp", "<%@ language=\"javascript\" %>\n")
    _w(
        base / "src/project_config.json",
        json.dumps({"deviceType": 1, "standard": True, "pluginVersion": "V3.0.7.41"}, indent=2)
        + "\n",
    )
    _w(base / "src/main-pc.js", "sessionStorage.setItem('BrowserType', 'pc');\n")
    _w(base / "src/main-mobile.js", "sessionStorage.setItem('BrowserType', 'mobile');\n")
    _w(base / "src/APP-pc.vue", "<template><div>pc</div></template>\n")
    _w(base / "src/APP-mobile.vue", "<template><div>mobile</div></template>\n")
    _w(base / "src/Router/pc.js", "export default [];\n")
    _w(base / "src/Router/mobile.js", "export default [];\n")
    _w(
        base / "src/Common/service/device.js",
        """export const m_oDeviceCapa = {
  bPTZ: false,
  bSupportWiper: false,
  bSupportManualDeicing: false,
  oFisheye: { bSupport: false },
};
""",
    )
    _w(base / "src/Common/libs/jsWebControl/index.js", "export function connect() {}\n")
    _w(base / "src/view/WiperButton.vue", "<template><button>雨刷</button></template>\n")
    _w(base / "src/view/Preview.vue", "<template><div>preview</div></template>\n")
    _w(
        base / "build/projectConfig/webpack.config.js",
        "module.exports = { filename: '../index.asp' };\n",
    )


def write_device_web_host_mf() -> None:
    """Host markers of device-web, architecture of micro-frontend (camera trap)."""
    base = ROOT / "device-web-host-mf"
    _plant_git(base)
    _w(
        base / "package.json",
        json.dumps(
            {
                "name": "simple-single-spa-webpack-example",
                "dependencies": {"single-spa": "3.8.1", "single-spa-vue": "1.0.0"},
            },
            indent=2,
        )
        + "\n",
    )
    _w(base / "src/index.asp", "<%@ language=\"javascript\" %>\n")
    _w(base / "src/project_config.json", json.dumps({"deviceType": 0}, indent=2) + "\n")
    _w(
        base / "src/index.html",
        """<!doctype html>
<div id="preview"></div>
<div id="playback"></div>
<div id="config"></div>
""",
    )
    for name, el in (("Preview", "preview"), ("Playback", "playback"), ("Config", "config")):
        _w(base / f"src/{name}/vue.app.js", _vue_app(name, el))
    _w(base / "src/Common/service/device.js", "export const capa = {};\n")


def _write_electron_product(base: Path) -> None:
    _plant_git(base, head="a" * 40)
    _w(
        base / "electron/package.json",
        json.dumps(
            {
                "name": "calibrationtool",
                "main": "dist-electron/main/index.js",
                "dependencies": {"electron": "19.1.9", "electron-builder": "23.6.0"},
            },
            indent=2,
        )
        + "\n",
    )
    _w(
        base / "electron/electron-builder.json5",
        "{ appId: 'com.example.calibrationtool', extraFiles: ['driver', 'subsystem'] }\n",
    )
    _w(
        base / "electron/electron/main/index.ts",
        "mainWin.loadFile(indexHtml);\nmainWin.loadURL(devUrl);\n",
    )
    _w(
        base / "electron/electron/preload/index.ts",
        """import { contextBridge } from 'electron';
contextBridge.exposeInMainWorld('electronAPI', {
  BoxManage_start: () => {},
  CalibrationTask_run: () => {},
});
""",
    )
    _w(
        base / "electron/electron/controller/boxCalibration/index.ts",
        "export function startBoxCalibration() {}\n",
    )
    _w(
        base / "electron/electron/controller/calibrationTask/index.ts",
        "export function runCalibrationTask() {}\n",
    )
    _w(
        base / "electron/electron/service/calibration/index.ts",
        "const subsystemFilePath = 'subsystem/index.js';\nfork(subsystemFilePath, [port]);\n",
    )
    _w(base / "electron/driver/camera/dummy.txt", "native driver placeholder\n")
    _w(
        base / "web/package.json",
        json.dumps({"name": "web", "dependencies": {"vue": "3.3.0"}}, indent=2) + "\n",
    )
    _w(base / "web/src/main.ts", "import { createApp } from 'vue';\ncreateApp({}).mount('#app');\n")
    _w(base / "web/src/request/ipcRequest.ts", "window.electronAPI[config.url](...args);\n")
    _w(
        base / "web/src/views/boxManagement/components/Panel.vue",
        "<template><div>decoy view</div></template>\n",
    )
    _w(
        base / "web/src/components/Message/main.vue",
        "<template><div>decoy main.vue</div></template>\n",
    )
    _w(base / "common/type.ts", "export type Shared = { id: string };\n")
    _w(base / "scripts/build.js", "// web then electron\n")


def write_electron() -> None:
    _write_electron_product(ROOT / "electron")


def write_electron_container() -> None:
    base = ROOT / "electron-container"
    _write_electron_product(base / "calibrationtool")
    sub = base / "calibration-subsystem"
    _w(
        sub / "package.json",
        json.dumps(
            {
                "name": "koa-template",
                "main": "dist/index.js",
                "dependencies": {"koa": "2.14.0", "vite-plugin-electron": "0.11.2"},
            },
            indent=2,
        )
        + "\n",
    )
    _plant_git(sub, head="b" * 40)
    _w(sub / "src/index.ts", "import Koa from 'koa';\nnew Koa().listen(4000);\n")
    _w(
        sub / "vite.config.ts",
        "export default { plugins: [{ name: 'vite-plugin-electron', entry: './src/index.ts' }] };\n",
    )


def write_eval_cases() -> None:
    cases = [
        {
            "id": "mf-person-module",
            "fixture": "micro-frontend",
            "profile": "micro_frontend",
            "ticket": {
                "defectId": "MF1",
                "title": "[人员管理] Person list empty",
                "pool": "strict",
                "expectQuality": "explicit",
                "testModule": "Person",
                "titleTag": "人员管理",
                "intent": "data_wrong",
            },
            "expectPathPrefix": "src/Person/",
        },
        {
            "id": "mf-h5-fork",
            "fixture": "micro-frontend",
            "profile": "micro_frontend",
            "ticket": {
                "defectId": "MF2",
                "title": "H5 mobile init blank screen",
                "pool": "strict",
                "expectQuality": "explicit",
                "testModule": "Common",
                "titleTag": "H5",
                "intent": "ui_layout",
            },
            "expectPathPrefix": "src/Common/mobile/",
        },
        {
            "id": "dw-wiper-capability",
            "fixture": "device-web",
            "profile": "device_web",
            "ticket": {
                "defectId": "DW1",
                "title": "雨刷按钮灰掉无法使用",
                "pool": "strict",
                "expectQuality": "explicit",
                "testModule": "预览",
                "titleTag": "雨刷",
                "intent": "logic",
            },
            "expectPathPrefix": "src/Common/service/device.js",
        },
        {
            "id": "dw-mobile-entry",
            "fixture": "device-web",
            "profile": "device_web",
            "ticket": {
                "defectId": "DW2",
                "title": "mobile 端首页无法打开",
                "pool": "strict",
                "expectQuality": "explicit",
                "testModule": "Portal",
                "titleTag": "mobile",
                "intent": "ui_layout",
            },
            "expectPathPrefix": "src/main-mobile.js",
        },
        {
            "id": "el-ipc-box",
            "fixture": "electron",
            "profile": "electron_node",
            "ticket": {
                "defectId": "EL1",
                "title": "盒子校准失败",
                "pool": "strict",
                "expectQuality": "explicit",
                "testModule": "boxCalibration",
                "titleTag": "BoxManage",
                "intent": "logic",
            },
            "expectPathPrefix": "electron/electron/controller/boxCalibration/",
        },
        {
            "id": "el-ui-renderer",
            "fixture": "electron",
            "profile": "electron_node",
            "ticket": {
                "defectId": "EL2",
                "title": "按钮文案显示错误",
                "pool": "strict",
                "expectQuality": "explicit",
                "testModule": "web",
                "titleTag": "文案",
                "intent": "ui_layout",
            },
            "expectPathPrefix": "web/src/",
        },
    ]
    _w(ROOT / "eval-cases.json", json.dumps({"cases": cases}, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    write_micro_frontend()
    write_micro_frontend_in_repo()
    write_device_web()
    write_device_web_host_mf()
    write_electron()
    write_electron_container()
    write_eval_cases()
    print(f"wrote fixtures under {ROOT}")


if __name__ == "__main__":
    main()
