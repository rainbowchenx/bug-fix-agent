"""Agent-3 报告打分：G0 过程 / G1 定位 / G2 结局。G3 根因只做弱检查。

不跑 SDK。输入已有 analysis-report.json + cases.json（见 docs/field-eval/agent3/）。

用法::

    python packaging/eval_agent3.py \\
        --report analysis-report.json \\
        --cases field-eval/agent3/<run>/cases.json \\
        --out field-eval/agent3/<run>/score.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for extra in ("platform", "contracts"):
    candidate = ROOT / extra
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from bugfix_contracts import validate_analysis_report  # noqa: E402

_ENTRY_MARKERS = (
    "/src/router/",
    "/src/main-pc.",
    "/src/main-mobile.",
    "src/router/",
    "src/main-pc.",
    "src/main-mobile.",
)


def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _rel(candidate: dict[str, Any]) -> str:
    rel = _norm(str(candidate.get("path") or ""))
    repo = candidate.get("repoPath") or "."
    if repo not in (".", "", None):
        rel = f"{_norm(str(repo)).rstrip('/')}/{rel.lstrip('/')}"
    return rel


def loc_hit(candidates: list[dict[str, Any]], prefix: str, k: int) -> bool:
    """True when any of the first ``k`` candidates sits on ``prefix``."""
    if not prefix:
        return False
    want = _norm(prefix).rstrip("/")
    for cand in candidates[:k]:
        rel = _rel(cand)
        if rel == want or rel.startswith(want + "/") or want.endswith("/") and rel.startswith(want):
            return True
    return False


def _is_entry_noise(rel: str) -> bool:
    low = f"/{_norm(rel).lower()}"
    return any(m in low for m in _ENTRY_MARKERS)


def _analyze_source(notes: str | None) -> str | None:
    text = notes or ""
    for tag in ("analyze=sdk_fallback", "analyze=heuristic", "analyze=sdk"):
        if tag in text:
            return tag.split("=", 1)[1]
    return None


def score_ticket(case: dict[str, Any], ticket: dict[str, Any] | None) -> dict[str, Any]:
    """Score one gold case against one report ticket."""
    g0: list[str] = []
    loc = ticket.get("localization") or {} if ticket else {}
    cands = list(loc.get("candidates") or [])
    notes = loc.get("notes") or ""
    outcome = ticket.get("outcome") if ticket else None
    pool = (case.get("pool") or "").strip()
    expect_outcomes = list(case.get("expectOutcomes") or [])
    prefix = (case.get("expectPathPrefix") or "").strip()
    source = _analyze_source(notes) if ticket else None

    if ticket is None:
        g0.append("missing_ticket")
        return _row(case, None, cands, source, g0, False, False, False)

    if pool == "needs_info":
        if source == "sdk":
            g0.append("needs_info_ran_sdk")
        if outcome != "needs_ticket_info":
            g0.append("needs_info_wrong_outcome")
    elif expect_outcomes and "needs_ticket_info" not in expect_outcomes:
        if source != "sdk":
            g0.append(f"analyze_source={source or 'missing'}")

    if outcome == "patch_ready":
        g0.append("patch_ready_on_report_path")
    verify = ticket.get("suggestedVerify") or {}
    if verify.get("executed") is True:
        g0.append("verify_executed")

    conf = ticket.get("confidence") or "low"
    if cands and prefix and not loc_hit(cands, prefix, 3):
        if all(_is_entry_noise(_rel(c)) for c in cands) and conf in ("high", "medium"):
            g0.append("entry_noise_confident")

    root = ticket.get("rootCause") or {}
    summary = (root.get("summary") or "").strip()
    title = ((ticket.get("ticket") or {}).get("title") or "").strip()
    keywords = list(case.get("rootCauseMustInclude") or [])
    weak_ok = bool(summary) and summary != title
    keyword_ok = all(k in summary for k in keywords) if keywords else True

    hit1 = loc_hit(cands, prefix, 1) if prefix else None
    hit3 = loc_hit(cands, prefix, 3) if prefix else None
    if prefix and pool != "needs_info" and not cands:
        hit1 = False
        hit3 = False
    outcome_ok = outcome in expect_outcomes if expect_outcomes else None

    return _row(case, ticket, cands, source, g0, hit1, hit3, outcome_ok, weak_ok and keyword_ok)


def _row(
    case: dict[str, Any],
    ticket: dict[str, Any] | None,
    cands: list[dict[str, Any]],
    source: str | None,
    g0: list[str],
    hit1: bool | None,
    hit3: bool | None,
    outcome_ok: bool | None,
    root_weak: bool | None = None,
) -> dict[str, Any]:
    paths = [_rel(c) for c in cands]
    return {
        "id": case.get("id", case.get("defectId")),
        "defectId": case["defectId"],
        "g0": g0,
        "g0Pass": not g0,
        "analyze": source,
        "outcome": None if ticket is None else ticket.get("outcome"),
        "outcomeOk": outcome_ok,
        "locAt1": hit1,
        "locAt3": hit3,
        "nCandidates": len(cands),
        "top1": paths[0] if paths else None,
        "candidates": paths[:3],
        "rootCauseWeakOk": root_weak,
        "expect": case.get("expectPathPrefix"),
        "expectOutcomes": case.get("expectOutcomes"),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    g0_pass = all(r["g0Pass"] for r in rows)
    loc_rows = [r for r in rows if r["locAt3"] is not None]
    out_rows = [r for r in rows if r["outcomeOk"] is not None]
    loc_n = len(loc_rows)
    out_n = len(out_rows)
    loc3 = sum(1 for r in loc_rows if r["locAt3"])
    loc1 = sum(1 for r in loc_rows if r["locAt1"])
    out_ok = sum(1 for r in out_rows if r["outcomeOk"])
    loc_rate = (loc3 / loc_n) if loc_n else None
    out_rate = (out_ok / out_n) if out_n else None

    if not g0_pass:
        verdict = "process_fail"
    elif loc_rate is not None and loc_rate < 0.4:
        verdict = "loc_unusable"
    elif out_rate is not None and out_rate < 0.6:
        verdict = "outcome_unusable"
    elif loc_rate is not None and loc_rate < 0.5:
        verdict = "loc_weak"
    elif (loc_rate is None or loc_rate >= 0.5) and (out_rate is None or out_rate >= 0.8):
        verdict = "usable_pending_g3"
    else:
        verdict = "mixed"

    return {
        "g0Pass": g0_pass,
        "locAt1": f"{loc1}/{loc_n}" if loc_n else None,
        "locAt3": f"{loc3}/{loc_n}" if loc_n else None,
        "outcome": f"{out_ok}/{out_n}" if out_n else None,
        "verdict": verdict,
        "bands": {
            "loc": (
                "good"
                if loc_rate is not None and loc_rate >= 0.7 and loc_n and loc1 / loc_n >= 0.4
                else "usable"
                if loc_rate is not None and loc_rate >= 0.5
                else "unusable"
                if loc_rate is not None
                else None
            ),
            "outcome": (
                "usable"
                if out_rate is not None and out_rate >= 0.8
                else "unusable"
                if out_rate is not None
                else None
            ),
        },
    }


def score_report(report: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    validated = validate_analysis_report(report)
    dumped = validated.model_dump()
    by_id = {t["defectId"]: t for t in dumped["tickets"]}
    rows = [score_ticket(case, by_id.get(case["defectId"])) for case in cases]
    return {"summary": summarize(rows), "applyFix": dumped.get("applyFix"), "rows": rows}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Agent-3 analysis-report 打分（G0/G1/G2）")
    ap.add_argument("--report", required=True, help="analysis-report.json")
    ap.add_argument("--cases", required=True, help="真值 cases.json")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    payload = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases = payload["cases"] if isinstance(payload, dict) and "cases" in payload else payload
    scored = score_report(report, cases)
    summary = scored["summary"]

    print(f"  G0={'PASS' if summary['g0Pass'] else 'FAIL'}  "
          f"loc@1={summary['locAt1']}  loc@3={summary['locAt3']}  "
          f"outcome={summary['outcome']}  verdict={summary['verdict']}")
    for row in scored["rows"]:
        g0 = ",".join(row["g0"]) or "ok"
        loc = "n/a" if row["locAt3"] is None else ("OK" if row["locAt3"] else "--")
        print(f"  {row['id']:28s} loc3={loc:3s}  outcome={row['outcome']!s:20s}  "
              f"g0={g0}  → {row['top1']}")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(scored, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  -> {out}")

    return 0 if summary["g0Pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
