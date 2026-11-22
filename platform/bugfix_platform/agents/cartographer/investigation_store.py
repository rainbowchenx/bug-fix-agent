"""Agent-2 组级原始响应与进度落盘。解析之前必须先保全。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from bugfix_contracts.code_knowledge import RawResponseRef

DEFAULT_TRANSCRIPT_LIMIT = 32 * 1024 * 1024


def attempt_dir(root: Path | str, group_id: str, call_id: str) -> Path:
    return Path(root) / "agent2" / "groups" / group_id / "attempts" / call_id


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _digest(payload: Any) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def save_group_progress(root: Path | str, progress: dict[str, Any]) -> Path:
    """组间原子进度。partial journal 可读，但不能当 complete cache。"""
    dest = Path(root) / "agent2" / "progress.json"
    _atomic_write(dest, json.dumps(progress, ensure_ascii=False, indent=2, default=str))
    return dest


def load_group_progress(root: Path | str) -> dict[str, Any] | None:
    path = Path(root) / "agent2" / "progress.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_format_repair(
    root: Path | str,
    group_id: str,
    call_id: str,
    *,
    before: str,
    after: str,
) -> Path:
    dest = attempt_dir(root, group_id, call_id) / "format-repair.json"
    _atomic_write(
        dest,
        json.dumps({"before": before, "after": after}, ensure_ascii=False, indent=2),
    )
    return dest


class InvestigationRecorder:
    """流式增量保全：异常退出时已收到的可见文本仍可读。"""

    def __init__(
        self,
        root: Path | str,
        group_id: str,
        call_id: str,
        *,
        input_digest: str = "",
        budget: Optional[dict[str, Any]] = None,
        transcript_limit: int = DEFAULT_TRANSCRIPT_LIMIT,
        sdk_version: str = "",
    ) -> None:
        self.root = Path(root)
        self.group_id = group_id
        self.call_id = call_id
        self.attempt_dir = attempt_dir(self.root, group_id, call_id)
        self.attempt_dir.mkdir(parents=True, exist_ok=True)
        self.input_digest = input_digest
        self.budget = dict(budget or {})
        self.transcript_limit = transcript_limit
        self.sdk_version = sdk_version
        self._transcript_bytes = 0
        self.truncated = False
        self.responses: dict[str, RawResponseRef] = {}
        self._started = datetime.now(timezone.utc).isoformat()

    def append_event(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, default=str) + "\n"
        encoded = line.encode("utf-8")
        path = self.attempt_dir / "transcript.jsonl"
        if self._transcript_bytes + len(encoded) > self.transcript_limit:
            if not self.truncated:
                self.truncated = True
                marker = json.dumps({"kind": "truncated", "limit": self.transcript_limit}) + "\n"
                with path.open("ab") as handle:
                    handle.write(marker.encode("utf-8"))
                self._write_parse_status("incomplete", "transcript truncated; parse inputs stored separately")
            return
        if self.truncated:
            return
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        self._transcript_bytes += len(encoded)
        self._write_parse_status("incomplete", "streaming")

    def save_response(self, response: dict[str, Any], *, repair: bool = False) -> None:
        filename = "repair-response.json" if repair else "response.json"
        _atomic_write(
            self.attempt_dir / filename,
            json.dumps(response, ensure_ascii=False, indent=2, default=str),
        )
        self.responses[filename] = RawResponseRef(path=filename, digest=_digest(response), callId=self.call_id)

    def save_parse_inputs(self, candidates: list[str]) -> None:
        _atomic_write(
            self.attempt_dir / "parse-candidates.json",
            json.dumps(candidates, ensure_ascii=False, indent=2),
        )

    def _write_parse_status(self, status: str, detail: str = "", diagnostics: dict[str, Any] | None = None) -> None:
        payload = {**(diagnostics or {}), "status": status, "detail": detail, "callId": self.call_id}
        _atomic_write(
            self.attempt_dir / "parse-result.json",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )

    def finalize(
        self,
        *,
        status: str,
        stop_reason: str,
        truncated: Optional[bool] = None,
        turns: Optional[int] = None,
        cost: Optional[float] = None,
        terminal: Optional[str] = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> Path:
        if truncated is not None:
            self.truncated = truncated
        responses = {key: ref.model_dump() for key, ref in self.responses.items()}
        self._write_parse_status(status, stop_reason, {**(diagnostics or {}), "responses": responses})
        manifest = {
            "callId": self.call_id,
            "groupId": self.group_id,
            "status": status,
            "stopReason": stop_reason,
            "inputDigest": self.input_digest,
            "budget": self.budget,
            "sdkVersion": self.sdk_version,
            "transcriptTruncated": self.truncated,
            "responses": responses,
            "turns": turns,
            "cost": cost,
            "terminal": terminal,
            "startedAt": self._started,
            "endedAt": datetime.now(timezone.utc).isoformat(),
        }
        dest = self.attempt_dir / "manifest.json"
        _atomic_write(dest, json.dumps(manifest, ensure_ascii=False, indent=2))
        if status == "saved":
            latest = self.root / "agent2" / "groups" / self.group_id / "latest.json"
            _atomic_write(
                latest,
                json.dumps(
                    {"callId": self.call_id, "path": str(self.attempt_dir), "status": status},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        return dest
