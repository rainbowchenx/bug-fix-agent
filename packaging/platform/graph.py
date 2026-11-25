"""Nexas OS 平台入口：zip 根级 ``graph.py``。

## 设计原则：所有参数都是"路径"

本入口只认一件事——**一个参数文件**。用户输入（``state["input"]``）写的是该文件的
路径，其余所有参数（defect-batch 路径、工作区、产线、仓型……）都写在那个文件里。
参数文件本身也是路径，不是 JSON 字符串。

这样做的原因：Nexas 会把平台自己的说明文字追加到用户输入后面（安全策略、文件传递
说明，两千多字符），任何"输入即 JSON"的假设都会被这些后缀破坏。路径模型对追加
文字免疫——取第一行或第一个存在的路径就够了。

    input: "E:/work/task-params.json"
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
    {summary, result, ok}

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

所有路径字段都支持相对路径——相对于**参数文件所在目录**解析，其次相对于 cwd。

## 为什么不需要 input_schema.json

客户端可以用 ``{"input_field": "xxx"}`` 把用户输入映射到某个 state 字段，但值仍然
是字符串。既然我们本来就只读一个路径，默认的 ``input`` 字段就够用。

## 关于出图

本文件只有一个 ``run_workflow`` 节点。Nexas 的 AST 解析器会把这张**外层包装图**
画出来；真正的 Agent-2→3 五节点编排在 ``bugfix_platform/workflow/langgraph_app.py``
里，AST 静态扫描跟不过去。这是已知取舍：先保证能跑出结果。

不要在这里加 ``from __future__ import annotations``——Nexas 的 runner 没把模块注册
进 ``sys.modules``，``get_type_hints()`` 解析不了字符串注解，``TypedDict`` 定义会
直接炸 ``NameError``。
"""

import json
import re
import traceback
from pathlib import Path
from typing import Any, NotRequired, TypedDict

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
_RESUME_KEYS = _COMMON_KEYS | {"defect_id", "feedback_file", "revision_id"}


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


def _load_params(path: Path) -> dict[str, Any]:
    """读参数文件。支持带 BOM、单行注释（``//``）的宽松 JSON。"""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as err:
        raise ValueError(f"读取参数文件失败：{path}：{err}") from err

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
                f"参数文件不是合法 JSON：{path}（第 {err.lineno} 行第 {err.colno} 列）"
            ) from err

    if not isinstance(data, dict):
        raise ValueError(f"参数文件顶层必须是 JSON 对象：{path}")
    return data


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


def _validate(params: dict[str, Any]) -> None:
    """启动前把明显缺的东西一次性报清楚，别让下游报一堆无关的校验错。"""
    problems: list[str] = []

    action = params.get("action", "run")
    if action not in ("run", "resume"):
        raise ValueError("action 必须是 run 或 resume")

    for key in _PATH_KEYS:
        if key in params and (not isinstance(params[key], str) or not params[key].strip()):
            problems.append(f"{key} 必须是非空路径")
    if action == "resume":
        root = params.get("artifact_dir")
        if not isinstance(root, str) or not root or not Path(root).is_dir():
            problems.append("resume 的 artifact_dir 必须指向首轮产物目录")
        for key in ("defect_id", "revision_id"):
            if key == "defect_id" or key in params:
                if not isinstance(params.get(key), str) or not params[key].strip():
                    problems.append(f"resume 的 {key} 必须是非空字符串")
        feedback = params.get("feedback_file")
        if isinstance(feedback, str) and not Path(feedback).is_file():
            problems.append(f"feedback_file 指向的文件不存在：{feedback}")
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
        params_path = _find_params_file(body)
        params = _resolve_paths(_load_params(params_path), params_path.parent)
    except Exception as err:  # noqa: BLE001
        return _failure(f"入参解析失败：{err}")

    try:
        _validate(params)
    except Exception as err:  # noqa: BLE001
        return _failure(f"参数校验失败（{params_path}）：\n{err}")

    try:
        with trace_output(params.get("trace_mode"), nexas=True) as display:
            result = _execute(params)
    except Exception as err:  # noqa: BLE001 — 任何异常都要变成可读结果，不能崩在图里
        detail = f"{type(err).__name__}: {err}\n{traceback.format_exc(limit=5)}"
        return _failure(f"编排执行失败：{err}", detail)

    return _project(result, detailed=display.mode == "detailed", resumed_ticket=params.get("defect_id"))


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

        root = Path(params["artifact_dir"])
        feedback = params.get("feedback_file")
        report = resume_defect(
            root,
            params["defect_id"],
            params.get("revision_id"),
            execute=True,
            apply_fix=params.get("apply_fix", False),
            feedback_file=Path(feedback) if feedback else None,
            **shared,
        )
        return ThreeAgentWorkflowResult(
            ok=True, stage="done", artifacts=WorkflowArtifacts(analysis_report=report), artifact_dir=str(root),
        )

    return run_three_agent_workflow(
        work_dir=params.get("work_dir") or _default_work_dir(),
        product_line=params.get("product_line"),
        defect_batch=params["defect_batch"],
        posture=params.get("posture"),
        apply_fix=params.get("apply_fix"),
        cartography_mode=params.get("cartography_mode"),
        cartography_profile=params.get("cartography_profile"),
        ticket_ids=params.get("ticket_ids"),
        artifact_dir=params.get("artifact_dir"),
        **shared,
    )


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
