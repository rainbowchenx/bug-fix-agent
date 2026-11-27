"""Nexas 图入口的两种入参形态与产物发布。

- 入参：既可以是参数文件的路径，也可以直接是 JSON 内容（Dify 直传）。
- 出参：产物要进 Nexas 的 ``output_files``，否则下游拿不到、人也下载不了。
"""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

GRAPH = Path(__file__).resolve().parents[2] / "packaging" / "platform" / "graph.py"


@pytest.fixture(scope="module")
def nx():
    return runpy.run_path(str(GRAPH))


# ---------------------------------------------------------------------------
# 内联 JSON
# ---------------------------------------------------------------------------


def test_inline_json_ignores_platform_suffix(nx):
    """Nexas 会在用户输入后追加两千多字符的平台说明，JSON 部分要能切出来。"""
    text = (
        '{\n  "defect_batch": "E:/work/batch.json",\n  "apply_fix": true\n}\n\n'
        "## 跨设备文件传递消费说明\n"
        "工具调用：shim 脚本在数据目录根，绝对路径 C:/x/nexas-file.sh\n"
        "1. 要传下游的产出，写数据目录 outputs/"
    )
    parsed, origin = nx["_inline_json"](text)
    assert parsed == {"defect_batch": "E:/work/batch.json", "apply_fix": True}
    assert origin == "<inline-json>"


def test_inline_json_handles_braces_and_escapes_inside_strings(nx):
    assert nx["_inline_json"]('{"m": "a{b}c"}')[0] == {"m": "a{b}c"}
    assert nx["_inline_json"](r'{"m": "say \"hi\""}')[0] == {"m": 'say "hi"'}


def test_inline_json_allows_line_comments(nx):
    text = '{\n  // 批次路径\n  "defect_batch": "x.json"\n}'
    assert nx["_inline_json"](text)[0] == {"defect_batch": "x.json"}


@pytest.mark.parametrize("text", ["", r"E:\work\task-params.json", '{"a": 1', "not json at all"])
def test_inline_json_returns_none_when_not_json(nx, text):
    assert nx["_inline_json"](text) is None


def test_relative_paths_resolve_against_cwd_for_inline(nx, tmp_path, monkeypatch):
    """内联 JSON 没有参数文件目录，相对路径退回 cwd（= 业务项目根）。"""
    monkeypatch.chdir(tmp_path)
    parsed = {"defect_batch": "rel/batch.json"}
    resolved = nx["_resolve_paths"](parsed, Path.cwd())
    assert Path(resolved["defect_batch"]) == tmp_path / "rel" / "batch.json"


# ---------------------------------------------------------------------------
# 产物发布
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, artifact_dir: Path) -> None:
        self.artifact_dir = str(artifact_dir)


@pytest.fixture
def task_env(tmp_path, monkeypatch):
    """搭一个 Nexas 任务数据目录：outputs/ + 会记录调用的 nexas-file.sh。"""
    data_dir = tmp_path / "任务 产物"
    outputs = data_dir / "outputs"
    outputs.mkdir(parents=True)
    calls = data_dir / "calls.log"
    shim = data_dir / "nexas-file.sh"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        '[[ "$1" == persist && -f "$2" ]] || exit 1\n'
        'printf \'%s\\n\' "$1 ${2##*/}" >> "${0%/*}/calls.log"\n'
        'echo \'{"ok":true,"result":{"fileRef":"ref-1"}}\'\n',
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setenv("NEXAS_TEMP_OUTPUT_DIR", str(outputs))
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "analysis-report.md").write_text("# 报告", encoding="utf-8")
    (artifacts / "analysis-report.json").write_text('{"a":1}', encoding="utf-8")
    return data_dir, outputs, calls, artifacts


def test_publish_copies_to_outputs_and_persists(nx, task_env):
    """报告既要进 outputs/（下游可读），也要 persist（人可下载）。"""
    if nx["_persist_bash"]() is None:
        pytest.skip("Native Bash is required to exercise the Nexas shell shim")
    _, outputs, calls, artifacts = task_env
    nx["_publish_outputs"](_Result(artifacts))

    assert sorted(p.name for p in outputs.iterdir()) == [
        "analysis-report.json", "analysis-report.md",
    ]
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "persist analysis-report.md", "persist analysis-report.json",
    ]


def test_persist_shim_returns_file_reference(nx, task_env):
    if nx["_persist_bash"]() is None:
        pytest.skip("Native Bash is required to exercise the Nexas shell shim")
    data_dir, _, _, artifacts = task_env
    assert nx["_persist_with_shim"](data_dir / "nexas-file.sh", artifacts / "analysis-report.md") == "ref-1"


@pytest.mark.parametrize("install", ["standard", "custom", None])
def test_windows_persist_bash_avoids_wsl_launcher(nx, tmp_path, monkeypatch, install):
    find_bash = nx["_persist_bash"]
    program_files = tmp_path / "Program Files"
    git_root = tmp_path / "Custom Git" if install == "custom" else program_files / "Git"
    git_bash = git_root / "bin" / "bash.exe"
    if install:
        git_bash.parent.mkdir(parents=True)
        git_bash.touch()
    monkeypatch.setitem(find_bash.__globals__, "os", SimpleNamespace(
        name="nt", environ={"ProgramFiles": str(program_files)},
    ))
    executables = {"bash": str(tmp_path / "Windows" / "System32" / "bash.exe")}
    if install == "custom":
        executables["git.exe"] = str(git_root / "cmd" / "git.exe")
    monkeypatch.setattr(find_bash.__globals__["shutil"], "which", executables.get)
    assert find_bash() == (str(git_bash) if install else None)


def test_publish_skips_missing_files(nx, task_env):
    _, outputs, _, artifacts = task_env
    (artifacts / "code-knowledge.json").write_text("{}", encoding="utf-8")
    nx["_publish_outputs"](_Result(artifacts))
    assert (outputs / "code-knowledge.json").is_file()


def test_publish_is_noop_without_nexas_data_dir(nx, monkeypatch, tmp_path):
    monkeypatch.delenv("NEXAS_TEMP_OUTPUT_DIR", raising=False)
    assert nx["_nexas_shim"]() is None
    nx["_publish_outputs"](_Result(tmp_path))  # 不该抛


def test_publish_is_noop_when_artifact_dir_missing(nx, task_env, tmp_path):
    _, outputs, _, _ = task_env
    nx["_publish_outputs"](_Result(tmp_path / "nope"))
    assert list(outputs.iterdir()) == []


def test_shim_failure_does_not_raise(nx, task_env):
    """persist 失败只影响可下载性，不能让整个任务失败。"""
    data_dir, outputs, _, artifacts = task_env
    (data_dir / "nexas-file.sh").write_text(
        "#!/usr/bin/env bash\necho '{\"ok\":false}'\nexit 1\n", encoding="utf-8"
    )
    nx["_publish_outputs"](_Result(artifacts))
    assert (outputs / "analysis-report.md").is_file()  # 复制仍完成


# ---------------------------------------------------------------------------
# 内联 feedback（Dify 代码节点只能传 JSON 对象，碰不到业务盘）
# ---------------------------------------------------------------------------


def test_inline_feedback_is_accepted(nx, tmp_path):
    params = {
        "action": "resume",
        "artifact_dir": str(tmp_path),
        "defect_id": "BGCM1",
        "feedback": {"feedbackId": "f1", "defectId": "BGCM1", "text": "补充"},
    }
    nx["_validate"](params)  # 不该抛


def test_inline_feedback_rejects_non_object(nx, tmp_path):
    params = {
        "action": "resume",
        "artifact_dir": str(tmp_path),
        "defect_id": "BGCM1",
        "feedback": "不是对象",
    }
    with pytest.raises(ValueError, match="feedback 必须是 JSON 对象"):
        nx["_validate"](params)


def test_inline_feedback_conflicts_with_file_and_revision(nx, tmp_path):
    for extra in ({"feedback_file": "x.json"}, {"revision_id": "r1"}):
        params = {
            "action": "resume",
            "artifact_dir": str(tmp_path),
            "defect_id": "BGCM1",
            "feedback": {"text": "x"},
            **extra,
        }
        with pytest.raises(ValueError, match="不能与"):
            nx["_validate"](params)


def test_materialize_feedback_writes_under_artifact_dir(nx, tmp_path):
    root = tmp_path / "art"
    root.mkdir()
    path = nx["_materialize_feedback"](
        {"feedback": {"text": "现象"}, "defect_id": "BGCM1"}, root
    )
    assert path is not None and path.is_file()
    assert "feedback" in path.parts
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["text"] == "现象"
    assert data["defectId"] == "BGCM1"      # 从 params 补齐
    assert data["feedbackId"]                # 自动生成


def test_materialize_feedback_prefers_file_and_handles_absent(nx, tmp_path):
    feedback_file = tmp_path / "f.json"
    feedback_file.write_text("{}", encoding="utf-8")
    assert nx["_materialize_feedback"]({"feedback_file": str(feedback_file)}, tmp_path) == feedback_file
    assert nx["_materialize_feedback"]({}, tmp_path) is None


# ---------------------------------------------------------------------------
# 产物目录默认值与 LATEST 指针
# ---------------------------------------------------------------------------


def test_run_without_artifact_dir_uses_work_dir_default(nx, tmp_path):
    """run 不给 artifact_dir 时落在 <work_dir>/.bugfix-runs/ 下，是新目录。"""
    root = nx["_resolve_artifact_dir"]({"work_dir": str(tmp_path)}, for_resume=False)
    assert root.parent == tmp_path / ".bugfix-runs"
    assert not root.exists()          # 只算出路径，由下游创建


def test_explicit_artifact_dir_wins(nx, tmp_path):
    explicit = tmp_path / "custom"
    root = nx["_resolve_artifact_dir"](
        {"work_dir": str(tmp_path), "artifact_dir": str(explicit)}, for_resume=False
    )
    assert root == explicit


def test_latest_pointer_roundtrip(nx, tmp_path):
    target = tmp_path / ".bugfix-runs" / "20260101T000000Z-ab"
    target.mkdir(parents=True)
    nx["_write_latest_pointer"](tmp_path, target)
    assert nx["_read_latest_pointer"](tmp_path) == target


@pytest.mark.parametrize("ok", [True, False])
def test_first_run_updates_latest_only_on_success(nx, tmp_path, monkeypatch, ok):
    from bugfix_platform import workflow

    previous = tmp_path / "previous"
    previous.mkdir()
    nx["_write_latest_pointer"](tmp_path, previous)
    current = tmp_path / "current"
    current.mkdir()
    result = SimpleNamespace(ok=ok, artifact_dir=str(current))
    monkeypatch.setattr(workflow, "run_three_agent_workflow", lambda **_: result)
    assert nx["_execute"]({"work_dir": str(tmp_path), "defect_batch": "batch.json"}) is result
    assert nx["_read_latest_pointer"](tmp_path) == (current if ok else previous)


def test_resume_without_artifact_dir_reads_pointer(nx, tmp_path):
    target = tmp_path / ".bugfix-runs" / "stamp"
    target.mkdir(parents=True)
    nx["_write_latest_pointer"](tmp_path, target)
    assert nx["_resolve_artifact_dir"]({"work_dir": str(tmp_path)}, for_resume=True) == target


def test_resume_without_pointer_errors_actionably(nx, tmp_path):
    with pytest.raises(ValueError, match="没有找到首轮产物目录"):
        nx["_resolve_artifact_dir"]({"work_dir": str(tmp_path)}, for_resume=True)


def test_validate_allows_missing_artifact_dir_for_resume(nx, tmp_path):
    """resume 不再强制 artifact_dir，只要能找到首轮产物。"""
    (tmp_path / "defects").mkdir()
    params = {"action": "resume", "work_dir": str(tmp_path), "defect_id": "D1"}
    nx["_validate"](params)


def test_validate_rejects_nonexistent_explicit_artifact_dir(nx, tmp_path):
    params = {
        "action": "resume",
        "artifact_dir": str(tmp_path / "nope"),
        "defect_id": "D1",
    }
    with pytest.raises(ValueError, match="不是目录"):
        nx["_validate"](params)


def test_find_ticket_feedback_ignores_blank_form(nx, tmp_path):
    did = "D1"
    form = tmp_path / "defects" / did / "feedback-form.md"
    form.parent.mkdir(parents=True)
    form.write_text(
        "<!-- BUGFIX_FEEDBACK_FORM -->\n"
        "<!-- ANSWER:observed -->\n\n<!-- /ANSWER:observed -->\n",
        encoding="utf-8",
    )
    assert nx["_find_ticket_feedback"](tmp_path, did) is None


def test_find_ticket_feedback_accepts_filled_form(nx, tmp_path):
    did = "D1"
    form = tmp_path / "defects" / did / "feedback-form.md"
    form.parent.mkdir(parents=True)
    form.write_text(
        "<!-- BUGFIX_FEEDBACK_FORM -->\n"
        "<!-- ANSWER:observed -->\n切换设备后无提示\n<!-- /ANSWER:observed -->\n",
        encoding="utf-8",
    )
    assert nx["_find_ticket_feedback"](tmp_path, did) == form


@pytest.mark.parametrize("revision_id", [None, "r1"])
def test_resume_auto_imports_form_only_without_revision_id(nx, tmp_path, monkeypatch, revision_id):
    from bugfix_platform.workflow import resume

    form = tmp_path / "defects" / "D1" / "feedback-form.md"
    form.parent.mkdir(parents=True)
    form.write_text(
        "<!-- BUGFIX_FEEDBACK_FORM -->\n"
        "<!-- ANSWER:observed -->\n切换设备后无提示\n<!-- /ANSWER:observed -->\n",
        encoding="utf-8",
    )
    calls = []

    def record_resume(root, defect_id, revision, *, feedback_file, **_):
        calls.append((root, defect_id, revision, feedback_file))

    monkeypatch.setattr(resume, "resume_defect", record_resume)
    params = {"action": "resume", "artifact_dir": str(tmp_path), "defect_id": "D1"}
    if revision_id is not None:
        params["revision_id"] = revision_id
    assert nx["_execute"](params).ok
    assert calls == [(tmp_path, "D1", revision_id, form if revision_id is None else None)]


def test_find_ticket_feedback_requires_marker(nx, tmp_path):
    did = "D1"
    form = tmp_path / "defects" / did / "feedback-form.md"
    form.parent.mkdir(parents=True)
    form.write_text("<!-- ANSWER:observed -->x<!-- /ANSWER:observed -->", encoding="utf-8")
    assert nx["_find_ticket_feedback"](tmp_path, did) is None
