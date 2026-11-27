"""Nexas OS 平台入口：zip 根级 ``graph.py``。

## 两种入参形态

用户输入（``state["input"]``）可以是**参数文件的路径**，也可以**直接是 JSON**。
判定顺序：先试内联 JSON，不成立再当路径。

    input（写法一）: '{"defect_batch": "E:/work/batch.json", "work_dir": "E:/repos/x"}'

    input（写法二）: "E:/work/task-params.json"
                        ↓ 读取
    {
      "defect_batch": "E:/work/defect-batch.json",   ← 也可以是相对路径
      "work_dir":     "E:/repos/transport",
      "product_line": "PJ14PD20260423284",
      "cartography_profile": "device_web"
    }
                        ↓ run_three_agent_workflow()
    analysis-report
                        ↓ 投影
    {summary, result, ok}   + 产物复制到 outputs/ 并 persist

## 为什么内联 JSON 是安全的

Nexas 会把平台自己的说明文字（安全策略、文件传递说明，两千多字符）追加到用户
输入后面。按路径找文件天然免疫这些后缀；内联 JSON 则靠**括号配对截取**：从第一
个 ``{`` 起数到深度归零为止，追加的文字根本进不了 ``json.loads``。

内联 JSON 没有文件目录，相对路径按 cwd（= 业务项目根）解析。

## 参数文件字段

===================  ==========  ==========================================
字段                 必需        说明
===================  ==========  ==========================================
defect_batch         是          Agent-1 产物 JSON 的路径
work_dir             否          业务代码根；缺省用 runner 的 cwd
product_line         否          提供时须和 defect_batch.productLine 一致
posture              否          提供时须和 defect_batch.posture 一致
cartography_profile  否          强烈建议给；缺省 unknown 会明显降质
cartography_mode     否          sdk / heuristic
analyze_mode         否          sdk / heuristic
ticket_ids           否          字符串数组，只跑这些票
apply_fix            否          默认关（只出方案不改码）
artifact_dir         否          产物目录；缺省 <work_dir>/.bugfix-runs/<时间戳>
trace_mode           否          off / summary / detailed
===================  ==========  ==========================================

所有路径字段都支持相对路径——相对于**参数文件所在目录**解析（内联 JSON 则按 cwd）。

## 为什么不需要 input_schema.json

客户端可以用 ``{"input_field": "xxx"}`` 把用户输入映射到某个 state 字段，但值仍然
是字符串。我们只需要一个字符串（路径或 JSON 文本），默认的 ``input`` 就够用。

## 关于出图

本文件只有一个 ``run_workflow`` 节点。Nexas 的 AST 解析器会把这张**外层包装图**
画出来；真正的 Agent-2→3 五节点编排在 ``bugfix_platform/workflow/langgraph_app.py``
里，AST 静态扫描跟不过去。这是已知取舍：先保证能跑出结果。

不要在这里加 ``from __future__ import annotations``——Nexas 的 runner 没把模块注册
进 ``sys.modules``，``get_type_hints()`` 解析不了字符串注解，``TypedDict`` 定义会
直接炸 ``NameError``。
"""

import json
import os
import re
import shutil
import subprocess
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NotRequired, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

# 平台不会替我们读 zip 里的 .env；不在这里调，那个文件就是摆设。
# load_env_file 幂等，且已存在的真实环境变量优先——平台「模型管理」注入的
# 值不会被仓里的 .env 覆盖。
from bugfix_contracts.env import load_env_file

load_env_file()

# SDK 的 Python 代码随包分发（0.5 MB），但那个 356 MB 的 claude.exe 不带 ——
# Nexas 自己就有一份。这里找到它并塞进 PATH，SDK 的 _find_cli() 才解析得到。
# 找不到也不报错：后续 SDK 调用会自己给出清晰的 ImportError/解析失败信息。
from bugfix_platform.sdk.claude_cli import ensure_claude_cli_on_path  # noqa: E402
from bugfix_platform.sdk.trace import trace_output  # noqa: E402
from bugfix_platform.workflow.persist import render_analysis_markdown  # noqa: E402

ensure_claude_cli_on_path()

# 客户端从 outputs 里挑这两个字段展示。summary 进任务卡片，result 进结果面板。
SUMMARY_MAX = 200
RESULT_MAX = 20000

# 参数文件里允许出现的键。未知字段报错。
_PATH_KEYS = ("defect_batch", "work_dir", "artifact_dir", "feedback_file", "repair_skill")
_COMMON_KEYS = {"action", "artifact_dir", "trace_mode", "analyze_mode", "apply_fix", "repair_skill", "project_integrations"}
_RUN_KEYS = _COMMON_KEYS | frozenset(
    {
        "defect_batch",
        "work_dir",
        "product_line",
        "posture",
        "cartography_profile",
        "cartography_mode",
        "ticket_ids",
    }
)
# ``work_dir`` 对 resume 也有效：不给 artifact_dir 时靠它定位 .bugfix-runs/LATEST。
_RESUME_KEYS = _COMMON_KEYS | {"defect_id", "feedback_file", "feedback", "revision_id", "work_dir"}


class NexasState(TypedDict):
    """外层包装图的 state。

    ``input`` 必须声明——LangGraph 会丢弃未声明的键，不声明的话节点里根本
    看不到用户输入。
    """

    input: NotRequired[str]
    summary: NotRequired[str]
    result: NotRequired[str]
    ok: NotRequired[bool]
    error: NotRequired[str]


# ---------------------------------------------------------------------------
# 输入解析：从用户输入里取参数文件路径
# ---------------------------------------------------------------------------


def _user_paths(text: str) -> list[str]:
    """从用户输入里摘出候选路径，按出现顺序。

    Nexas 会在用户输入后面追加平台说明（含大量中文和反斜杠），所以不能整体
    当路径用。做法是逐行找"像路径"的片段：

    - 去掉首尾引号/空白
    - 必须含路径分隔符或盘符
    - 不含换行
    """
    found: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip().strip('"').strip("'").strip("`").strip()
        if not line or len(line) > 400:
            continue
        # 盘符开头 / POSIX 绝对路径 / 含分隔符的相对路径
        if re.match(r"^[A-Za-z]:[\\/]", line) or line.startswith(("/", "\\")):
            found.append(line)
        elif ("\\" in line or "/" in line) and " " not in line:
            found.append(line)
    return found


def _candidates(text: str) -> list[Path]:
    """把候选路径展开成绝对路径列表（相对 cwd 解析）。"""
    out: list[Path] = []
    for raw in _user_paths(text):
        p = Path(raw).expanduser()
        out.append(p if p.is_absolute() else (Path.cwd() / p))
    return out


def _find_params_file(text: str) -> Path:
    """定位参数文件。

    依次尝试：输入里的每个候选路径 → 若指向目录则找其中的 params.json /
    task-params.json / input.json。找到一个存在的就返回。
    """
    tried: list[str] = []
    for cand in _candidates(text):
        tried.append(str(cand))
        if cand.is_file():
            return cand
        if cand.is_dir():
            for name in ("params.json", "task-params.json", "input.json", "args.json"):
                nested = cand / name
                if nested.is_file():
                    return nested
            tried.extend(str(cand / n) for n in ("params.json", "task-params.json", "input.json"))

    detail = "\n".join(f"  · {t}" for t in tried) or "  （输入里没有找到任何路径）"
    raise ValueError(
        "没有找到参数文件。用户输入应当是一个 JSON 文件的路径，例如：\n"
        "  E:/work/task-params.json\n"
        f"尝试过：\n{detail}\n"
        f"当前工作目录：{Path.cwd()}"
    )


def _parse_params_text(text: str, origin: str) -> dict[str, Any]:
    """解析参数 JSON 文本。支持带 BOM、单行注释（``//``）的宽松 JSON。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        # 允许 // 开头整行注释，方便人手工维护这个文件
        stripped = "\n".join(
            ln for ln in text.splitlines() if not ln.lstrip().startswith("//")
        )
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            raise ValueError(
                f"参数不是合法 JSON：{origin}（第 {err.lineno} 行第 {err.colno} 列）"
            ) from err

    if not isinstance(data, dict):
        raise ValueError(f"参数顶层必须是 JSON 对象：{origin}")
    return data


def _load_params(path: Path) -> dict[str, Any]:
    """读参数文件。支持带 BOM、单行注释（``//``）的宽松 JSON。"""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as err:
        raise ValueError(f"读取参数文件失败：{path}：{err}") from err
    return _parse_params_text(text, str(path))


def _inline_json(text: str) -> Optional[tuple[dict[str, Any], str]]:
    """用户输入本身就是参数 JSON 时，直接取用，不用再落一个文件。

    Nexas 会在用户输入后面追加平台说明（含中文和反斜杠），所以只认**开头就是
    JSON 对象**的输入：从第一个 ``{`` 到与之配对的 ``}`` 截断，剩余内容（平台
    追加的说明）忽略。找不到平衡的结尾就返回 ``None``，退回路径模式。
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for pos in range(start, len(text)):
        ch = text[pos]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                chunk = text[start : pos + 1]
                try:
                    return _parse_params_text(chunk, "用户输入里的 JSON"), _INLINE_ORIGIN
                except ValueError:
                    return None
    return None


# 内联 JSON 没有参数文件目录，相对路径按 cwd（= 业务项目根）解析。
_INLINE_ORIGIN = "<inline-json>"


def _resolve_paths(params: dict[str, Any], base: Path) -> dict[str, Any]:
    """把参数文件里的相对路径按参数文件所在目录解析成绝对路径。"""
    out = dict(params)
    for key in _PATH_KEYS:
        raw = out.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        p = Path(raw.strip()).expanduser()
        if not p.is_absolute():
            p = base / p
        out[key] = str(p.resolve())
    return out


def _default_work_dir() -> str:
    """缺省工作区：runner 被 spawn 时的 cwd。

    Nexas 用 ``t.cwd || e.workspace`` 作为 spawn 的 cwd（业务项目根），并把同一个值
    写进 state.workspacePath。所以进程的 cwd 就是我们想要的业务代码根。
    """
    return str(Path.cwd())


# 默认产物根。持续保留同一个位置，续跑才能找回首轮产物。
_RUNS_DIRNAME = ".bugfix-runs"
_LATEST_POINTER = "LATEST"
_ARTIFACT_STAMP_FMT = "%Y%m%dT%H%M%SZ"


def _runs_root(work_dir: str | Path) -> Path:
    return Path(work_dir) / _RUNS_DIRNAME


def _read_latest_pointer(work_dir: str | Path) -> Optional[Path]:
    """读 ``<work_dir>/.bugfix-runs/LATEST``，返回它指向的产物目录。"""
    pointer = _runs_root(work_dir) / _LATEST_POINTER
    try:
        raw = pointer.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    target = Path(raw)
    if not target.is_absolute():
        target = _runs_root(work_dir) / target
    return target if target.is_dir() else None


def _write_latest_pointer(work_dir: str | Path, artifact_dir: Path) -> None:
    """把本次产物目录记到 ``LATEST``，下次 resume 不必再让用户填路径。"""
    root = _runs_root(work_dir)
    try:
        root.mkdir(parents=True, exist_ok=True)
        target = root / _LATEST_POINTER
        tmp = target.with_suffix(".tmp")
        tmp.write_text(str(artifact_dir), encoding="utf-8")
        tmp.replace(target)
    except OSError:
        pass  # 指针只是便利，写不了不影响本次产物


def _resolve_artifact_dir(params: dict[str, Any], *, for_resume: bool) -> Path:
    """确定产物目录。

    - 显式给了 ``artifact_dir`` → 用它（人想固定或指向旧批次时）
    - ``run`` 没给 → ``<work_dir>/.bugfix-runs/<时间戳>``，每次新目录，历史不覆盖
    - ``resume`` 没给 → 读 ``LATEST``；没有就报错，让用户知道要先跑首轮
    """
    raw = params.get("artifact_dir")
    if isinstance(raw, str) and raw.strip():
        return Path(raw.strip())

    work_dir = params.get("work_dir") or _default_work_dir()

    if for_resume:
        latest = _read_latest_pointer(work_dir)
        if latest is None:
            raise ValueError(
                "没有找到首轮产物目录。请在「产物目录」里填首轮的路径，"
                f"或先跑一次 run 模式（产物默认在 {_runs_root(work_dir)}）"
            )
        return latest

    stamp = datetime.now(timezone.utc).strftime(_ARTIFACT_STAMP_FMT)
    target = _runs_root(work_dir) / f"{stamp}-{os.getpid():x}"
    # 同秒重复调用时加后缀，避免覆盖
    if target.exists():
        suffix = 1
        while (candidate := target.with_name(f"{target.name}-{suffix}")).exists():
            suffix += 1
        target = candidate
    return target


def _find_ticket_feedback(artifact_dir: Path, defect_id: str) -> Optional[Path]:
    """找某张票的 ``feedback-form.md``，并确认用户确实填了内容。

    只看 ``ANSWER`` 标记之间的正文：空白表单不能当反馈导入，否则会生成
    一份空 revision。
    """
    form = artifact_dir / "defects" / defect_id / "feedback-form.md"
    if not form.is_file():
        return None
    try:
        text = form.read_text(encoding="utf-8")
    except OSError:
        return None
    if "BUGFIX_FEEDBACK_FORM" not in text:
        return None
    for match in _ANSWER_BODY_RE.finditer(text.replace("\r\n", "\n")):
        if match.group("body").strip():
            return form
    return None


_ANSWER_BODY_RE = re.compile(
    r"<!--\s*ANSWER:(?P<key>[\w-]+)\s*-->(?P<body>.*?)<!--\s*/ANSWER:\1\s*-->",
    re.S,
)


def _validate(params: dict[str, Any]) -> None:
    """启动前把明显缺的东西一次性报清楚，别让下游报一堆无关的校验错。"""
    problems: list[str] = []

    action = params.get("action", "run")
    if action not in ("run", "resume"):
        raise ValueError("action 必须是 run 或 resume")

    for key in _PATH_KEYS:
        if key in params and (not isinstance(params[key], str) or not params[key].strip()):
            problems.append(f"{key} 必须是非空路径")
    # artifact_dir 可省略：run 走 <work_dir>/.bugfix-runs/<时间戳>，resume 读 LATEST。
    # 只有显式给了才校验它存在。
    if isinstance(raw_root := params.get("artifact_dir"), str) and raw_root.strip():
        if action == "resume" and not Path(raw_root.strip()).is_dir():
            problems.append(f"resume 的 artifact_dir 不是目录：{raw_root.strip()}")
    if action == "resume":
        for key in ("defect_id", "revision_id"):
            if key == "defect_id" or key in params:
                if not isinstance(params.get(key), str) or not params[key].strip():
                    problems.append(f"resume 的 {key} 必须是非空字符串")
        feedback = params.get("feedback_file")
        if isinstance(feedback, str) and not Path(feedback).is_file():
            problems.append(f"feedback_file 指向的文件不存在：{feedback}")
        inline = params.get("feedback")
        if inline is not None and not isinstance(inline, dict):
            problems.append("feedback 必须是 JSON 对象（内联反馈）")
        if inline is not None and ("feedback_file" in params or "revision_id" in params):
            problems.append("feedback 不能与 feedback_file / revision_id 同时使用")
        if "feedback_file" in params and "revision_id" in params:
            problems.append("feedback_file 与 revision_id 不能同时使用")
    else:
        db = params.get("defect_batch")
        if not isinstance(db, str) or not db or not Path(db).is_file():
            problems.append("defect_batch 必须指向已有的 defect-batch JSON")
        wd = params.get("work_dir")
        if isinstance(wd, str) and not Path(wd).is_dir():
            problems.append(f"work_dir 不是目录：{wd}")

    unknown = set(params) - (_RESUME_KEYS if action == "resume" else _RUN_KEYS)
    if unknown:
        problems.append(f"参数文件里有无法识别的字段（拼错了？）：{sorted(unknown)}")
    if "trace_mode" in params and params["trace_mode"] not in ("off", "summary", "detailed"):
        problems.append("trace_mode 必须是 off、summary 或 detailed")
    for key in ("project_integrations", "apply_fix"):
        if key in params and not isinstance(params[key], bool):
            problems.append(f"{key} 必须是布尔值")
    if "analyze_mode" in params and params["analyze_mode"] not in ("sdk", "heuristic"):
        problems.append("analyze_mode 必须是 sdk 或 heuristic")
    if params.get("repair_skill") and params.get("analyze_mode") == "heuristic":
        problems.append("repair_skill 需要 Agent3 SDK 模式")

    if problems:
        raise ValueError("\n".join(f"  · {p}" for p in problems))
    if path := params.get("repair_skill"):
        from bugfix_platform.sdk.credentials import has_credentials
        from bugfix_platform.sdk.skill_inject import load_repair_skill

        load_repair_skill(path)
        if not has_credentials():
            raise ValueError("repair_skill 需要 Agent3 SDK 模型凭据")


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------


def run_workflow(state: NexasState) -> dict[str, Any]:
    """读取参数文件，首跑或续跑后返回 Nexas 展示字段。"""
    body = state.get("input") or ""

    try:
        inline = _inline_json(body)
        if inline is not None:
            params, params_origin = inline
            params = _resolve_paths(params, Path.cwd())
        else:
            params_path = _find_params_file(body)
            params = _resolve_paths(_load_params(params_path), params_path.parent)
            params_origin = str(params_path)
    except Exception as err:  # noqa: BLE001
        return _failure(f"入参解析失败：{err}")

    try:
        _validate(params)
    except Exception as err:  # noqa: BLE001
        return _failure(f"参数校验失败（{params_origin}）：\n{err}")

    try:
        with trace_output(params.get("trace_mode"), nexas=True) as display:
            result = _execute(params)
    except Exception as err:  # noqa: BLE001 — 任何异常都要变成可读结果，不能崩在图里
        detail = f"{type(err).__name__}: {err}\n{traceback.format_exc(limit=5)}"
        return _failure(f"编排执行失败：{err}", detail)

    _publish_outputs(result)

    return _project(result, detailed=display.mode == "detailed", resumed_ticket=params.get("defect_id"))


def _materialize_feedback(params: dict[str, Any], root: Path) -> Optional[Path]:
    """把内联 ``feedback`` 对象落成临时文件，供 ``resume_defect`` 读取。

    Dify 的代码节点跑在 Linux 沙箱里、碰不到业务盘，所以反馈只能以 JSON 对象
    的形式随参数传进来，再由这里落到产物目录下的受控位置。``feedback_file``
    仍然优先——它给了调用方自己管理文件的机会。
    """
    raw = params.get("feedback")
    if raw is None:
        path = params.get("feedback_file")
        return Path(path) if path else None
    if not isinstance(raw, dict):
        raise ValueError("feedback 必须是 JSON 对象")

    # 缺 defectId 时用 params 里的补上：代码节点通常只回传人工填的那几项
    payload = dict(raw)
    payload.setdefault("defectId", params.get("defect_id"))
    payload.setdefault(
        "feedbackId",
        f"{params.get('defect_id') or 'feedback'}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
    )

    # 落进产物目录：既随产物留档，也不污染业务仓
    target_dir = root / "feedback"
    target_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(payload["defectId"] or "defect"))
    target = target_dir / f"{safe}-{payload['feedbackId']}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _execute(params: dict[str, Any]):
    from bugfix_platform.workflow import run_three_agent_workflow

    shared = {
        "analyze_mode": params.get("analyze_mode"),
        "repair_skill_path": params.get("repair_skill"),
        "project_integrations": params.get("project_integrations", False),
    }
    if params.get("action") == "resume":
        from bugfix_platform.workflow.resume import resume_defect
        from bugfix_platform.workflow.run import ThreeAgentWorkflowResult, WorkflowArtifacts

        root = _resolve_artifact_dir(params, for_resume=True)
        revision_id = params.get("revision_id")
        feedback = _materialize_feedback(params, root)
        if feedback is None and revision_id is None:
            # 没显式给反馈时，看用户是否填了该票的 feedback-form.md
            feedback = _find_ticket_feedback(root, params["defect_id"])
        report = resume_defect(
            root,
            params["defect_id"],
            revision_id,
            execute=True,
            apply_fix=params.get("apply_fix", False),
            feedback_file=feedback,
            **shared,
        )
        return ThreeAgentWorkflowResult(
            ok=True, stage="done", artifacts=WorkflowArtifacts(analysis_report=report), artifact_dir=str(root),
        )

    work_dir = params.get("work_dir") or _default_work_dir()
    root = _resolve_artifact_dir(params, for_resume=False)
    result = run_three_agent_workflow(
        work_dir=work_dir,
        product_line=params.get("product_line"),
        defect_batch=params["defect_batch"],
        posture=params.get("posture"),
        apply_fix=params.get("apply_fix"),
        cartography_mode=params.get("cartography_mode"),
        cartography_profile=params.get("cartography_profile"),
        ticket_ids=params.get("ticket_ids"),
        artifact_dir=str(root),
        **shared,
    )
    # 失败或未落盘的首跑不能替换可续跑的批次。
    if result.ok and result.artifact_dir and (completed_root := Path(result.artifact_dir)).is_dir():
        _write_latest_pointer(work_dir, completed_root)
    return result


# 能进 output_files 的产物，按重要性排序；同样是这些文件会被 persist 成可下载成果物。
_PUBLISH_FILES = (
    ("analysis-report.md", "报告（可读）"),
    ("analysis-report.json", "报告（机器读）"),
    ("code-knowledge.json", "仓型知识"),
)


def _nexas_shim() -> tuple[Path, Optional[str]] | None:
    """定位 Nexas 的 ``nexas-file.sh`` 及其数据目录。

    Nexas 只在**有文件传递上下文的任务**里注入 ``NEXAS_TEMP_OUTPUT_DIR``
    （= ``<数据目录>/outputs``）。没有这个变量说明是本地直跑，不需要发布。
    """
    raw = (os.environ.get("NEXAS_TEMP_OUTPUT_DIR") or "").strip()
    if not raw:
        return None
    outputs = Path(raw)
    data_dir = outputs.parent
    shim = data_dir / "nexas-file.sh"
    return (shim, str(data_dir)) if shim.is_file() else None


def _publish_outputs(result: Any) -> None:
    """把产物登记到 Nexas 的 ``output_files``，失败不影响主流程。

    两条通道对应两种用途：

    - **写进 ``outputs/``** —— 任务结束自动进传递清单，给下游 Dify 节点用
    - **``nexas-file persist``** —— 进成果物列表且可下载（留档给人看）

    报告同时走两条：下游要读，人也要下载。
    """
    located = _nexas_shim()
    if located is None:
        return
    shim, data_dir = located
    artifact_dir = getattr(result, "artifact_dir", None)
    if not artifact_dir:
        return
    root = Path(artifact_dir)
    if not root.is_dir():
        return

    outputs = Path(data_dir) / "outputs"
    published: list[str] = []
    for name, _label in _PUBLISH_FILES:
        source = root / name
        if not source.is_file():
            continue
        try:
            outputs.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, outputs / name)
            published.append(name)
        except OSError:
            continue

    for name in published:
        _persist_with_shim(shim, Path(data_dir) / "outputs" / name)


def _persist_bash() -> Optional[str]:
    if os.name != "nt":
        return shutil.which("bash")

    # 系统目录里的 bash.exe 是 WSL 启动器，无法直接用宿主的 Windows 路径执行 shim。
    git_roots = [
        Path(root) / "Git"
        for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)")
        if (root := os.environ.get(key))
    ]
    if local_app_data := os.environ.get("LOCALAPPDATA"):
        git_roots.append(Path(local_app_data) / "Programs" / "Git")
    if git := shutil.which("git.exe"):
        git_roots.append(Path(git).resolve().parent.parent)
    for git_root in git_roots:
        bash = git_root / "bin" / "bash.exe"
        if bash.is_file():
            return str(bash)

    bash = shutil.which("bash")
    if bash and Path(bash).parent.name.lower() not in {"system32", "sysnative", "syswow64", "windowsapps"}:
        return bash
    return None


def _persist_with_shim(shim: Path, target: Path) -> Optional[str]:
    """调 ``nexas-file persist``；返回 file_ref，失败返回 None。

    shim 是 bash 脚本（靠 ``/dev/tcp`` 回传主进程），所以必须交给 bash 跑。
    Windows 上不能用 ``nexas-file.cmd`` —— cmd.exe 按 GBK 解析参数，中文路径会毁。
    """
    bash = _persist_bash()
    if bash is None:
        return None
    try:
        done = subprocess.run(
            [bash, shim.as_posix(), "persist", target.as_posix()],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    try:
        payload = json.loads((done.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    return (payload.get("result") or {}).get("fileRef")


def _project(result: Any, *, detailed: bool = False, resumed_ticket: str | None = None) -> dict[str, Any]:
    """把 ``ThreeAgentWorkflowResult`` 投影成客户端会读的字段。"""
    ok = bool(getattr(result, "ok", False))
    stage = getattr(result, "stage", "?")
    error = getattr(result, "error", None)
    artifacts = getattr(result, "artifacts", None)
    report = getattr(artifacts, "analysis_report", None) if artifacts else None
    knowledge = getattr(artifacts, "code_knowledge", None) if artifacts else None
    batch = getattr(artifacts, "defect_batch", None) if artifacts else None

    lines: list[str] = []
    lines.append(f"状态：{'成功' if ok else '失败'}（stage={stage}）")
    if error:
        lines.append(f"原因：{error}")
    if resumed_ticket:
        lines.append(f"Agent3 续跑票号：{resumed_ticket}")
    if batch is not None:
        lines.append(f"缺陷批次：{len(getattr(batch, 'tickets', []) or [])} 张票")
    if knowledge is not None:
        lines.append(f"仓型：{getattr(knowledge, 'cartographyProfile', '?')}")
    if report is not None:
        summary = getattr(report, "summary", None)
        if summary is not None:
            total = getattr(summary, "total", 0)
            by_outcome = getattr(summary, "byOutcome", {}) or {}
            lines.append(f"分析结果：{total} 张票")
            for outcome, count in sorted(by_outcome.items()):
                lines.append(f"  · {outcome}: {count}")
        for ticket in (getattr(report, "tickets", []) or [])[:10]:
            defect_id = getattr(ticket, "defectId", "?")
            outcome = getattr(ticket, "outcome", None) or getattr(ticket, "analysisStatus", "?")
            lines.append(f"  - {defect_id}: {outcome}")
    artifact_dir = getattr(result, "artifact_dir", None)
    if artifact_dir:
        lines.append(f"产物目录：{artifact_dir}")
        if detailed:
            lines.append(f"会话记录：{Path(artifact_dir) / 'logs'}")

    text = "\n".join(lines)
    if detailed and report is not None:
        report_text = "\n\n" + render_analysis_markdown(report)
        available = max(0, RESULT_MAX - len(text))
        if len(report_text) > available:
            footer = "\n\n报告预览已截断，完整报告见产物目录的 analysis-report.md。"
            report_text = report_text[:max(0, available - len(footer))].rstrip() + footer
        text += report_text
    head = lines[0]
    if error:
        head = f"{head} — {error}"

    return {
        "summary": head[:SUMMARY_MAX],
        "result": text[:RESULT_MAX],
        "ok": ok,
    }


def _failure(message: str, detail: str = "") -> dict[str, Any]:
    """失败也要写 summary/result——否则客户端只能看到一个空白任务。"""
    text = message if not detail else f"{message}\n\n{detail[:RESULT_MAX]}"
    return {
        "summary": message[:SUMMARY_MAX],
        "result": text[:RESULT_MAX],
        "ok": False,
    }


# ---------------------------------------------------------------------------
# 图
# ---------------------------------------------------------------------------


def _compile():
    """构造并编译外层包装图。"""
    g = StateGraph(NexasState)
    g.add_node("run_workflow", run_workflow)
    g.add_edge(START, "run_workflow")
    g.add_edge("run_workflow", END)
    return g.compile()


def build_graph():
    """返回已编译的外层包装图。

    必须返回**同一个**编译产物：``langgraph_runner.py`` 会在拿到图之后从
    ``.builder`` 重新 compile 注入 checkpointer，对象不唯一会导致行为和图定义
    脱节。所以这里复用模块级 ``graph``，不每次新建。
    """
    return graph


# 模块级 graph：Nexas 的 load_graph() 先找 build_graph()，没有才用这个。
# 两个都给，平台和本地脚本都能用。
graph = _compile()


def main() -> int:
    """本地/兜底入口：``python graph.py <参数文件路径>``。"""
    import sys

    body = sys.argv[1] if len(sys.argv) > 1 else ""
    out = graph.invoke({"input": body})
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
