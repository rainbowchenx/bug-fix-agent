from __future__ import annotations

import re
from typing import Optional

from bugfix_agent.contracts.defect_batch import BatchCluster, BatchTicket, Intent
from bugfix_agent.defect_batch.intent import IntentClassifier, IntentResult, default_intent_classifier
from bugfix_agent.defect_batch.rules import is_open_like
from bugfix_agent.defect_batch.screen import ScreenedTicket


def _cluster_id(line: str, module: str, tag: str, intent: Intent, token: Optional[str] = None) -> str:
    base = f"{line}::{module}::{tag}::{intent}"
    return f"{base}::{token}" if token else base


def _title_token(title: str) -> str:
    # strip tags / code-review prefix then take a meaningful chunk
    t = re.sub(r"【[^】]+】|\[[^\]]+\]", "", title).strip()
    t = re.sub(r"^问题描述\s*[:：]\s*", "", t)
    m = re.search(r"[A-Za-z_][A-Za-z0-9_.-]{2,24}", t)
    if m:
        return m.group(0)[:24]
    m = re.search(r"[\u4e00-\u9fff]{2,12}", t)
    return m.group(0) if m else "_misc"


def _expect_rank(q: str) -> int:
    return {"explicit": 0, "inferred": 1, "ambiguous": 2}.get(q, 3)


def cluster_screened(
    screened: list[ScreenedTicket],
    product_line: str,
    *,
    intent_classifier: Optional[IntentClassifier] = None,
    fat_ratio: float = 0.25,
    fat_absolute: int = 40,
    intent_on_locatable: bool = False,
) -> tuple[list[BatchCluster], list[BatchTicket]]:
    """把筛选结果编成簇与全量票（L1/L2 规则 + L3 意图 + R5/R6）。

    仅 ``strict`` 进簇并默认跑 L3。过大簇（占比 / 绝对条数 / 代码评审堆）
    按标题 token 再切（R5）；票按池与 expectQuality 排序（R6）。旁路池仍
    出现在 ``tickets``，``clusterId`` 为 ``None``。

    Args:
        screened: 漏斗输出。
        product_line: 写入 ``clusterId`` 前缀。
        intent_classifier: L3 分类器；默认启发式，不调 LLM。
        fat_ratio: 相对 ``strict`` 总数的过肥阈值（默认 0.25）。
        fat_absolute: 绝对条数过肥阈值（默认 40）。
        intent_on_locatable: 为 True 时也对 ``locatable_only`` 打意图。

    Returns:
        ``(clusters, tickets)``。``clusters`` 仅含 strict；``tickets`` 为全量。
    """
    classify = intent_classifier or default_intent_classifier
    strict = [t for t in screened if t.pool == "strict"]
    for_intent = (
        [t for t in screened if t.pool in ("strict", "locatable_only")]
        if intent_on_locatable
        else strict
    )
    intent_map = classify([t.digest for t in for_intent])

    tickets: list[BatchTicket] = []
    cluster_buckets: dict[str, list[ScreenedTicket]] = {}

    for t in screened:
        dig = t.digest
        intent_res = intent_map.get(
            dig.defectId,
            IntentResult("unclear", "unclear", "low", "not classified"),
        )
        in_primary = t.pool == "strict"
        cid = (
            _cluster_id(product_line, dig.testModule, dig.titleTag, intent_res.intent)
            if in_primary
            else None
        )
        if in_primary and cid:
            cluster_buckets.setdefault(cid, []).append(t)

        use_intent = in_primary or intent_on_locatable
        tickets.append(
            BatchTicket(
                defectId=dig.defectId,
                title=dig.title,
                pool=t.pool,
                clusterId=cid,
                testModule=dig.testModule,
                titleTag=dig.titleTag,
                intent=intent_res.intent if use_intent else None,
                intentSource=intent_res.intentSource if use_intent else None,
                intentConfidence=intent_res.intentConfidence if use_intent else None,
                intentRationale=intent_res.rationale if use_intent else None,
                fieldType=dig.fieldType,
                expectQuality=t.expectQuality,
                reasonCode=t.reasonCode,
                reasonDetail=t.reasonDetail,
                observed=dig.observed or None,
                expected=dig.expected or None,
                steps=dig.steps or None,
                status=dig.status,
                severity=dig.severity,
                createdAt=dig.createdAt,
                duplicate=dig.duplicate,
                semanticFree=dig.semanticFree,
            )
        )

    strict_count = max(len(strict), 1)
    final_buckets: dict[str, list[ScreenedTicket]] = {}
    for cid, lst in cluster_buckets.items():
        code_review_heavy = sum(1 for t in lst if t.digest.titleTag == "_code_review") >= max(3, len(lst) // 2)
        fat = (
            len(lst) / strict_count > fat_ratio
            or len(lst) > fat_absolute
            or (code_review_heavy and len(lst) > 5)
        )
        if not fat:
            final_buckets[cid] = lst
            continue
        by_token: dict[str, list[ScreenedTicket]] = {}
        for t in lst:
            token = _title_token(t.digest.title) or "_misc"
            key = f"{cid}::{token}"
            by_token.setdefault(key, []).append(t)
        for key, arr in by_token.items():
            final_buckets[key] = arr
            # rewrite ticket clusterIds
            ids = {x.digest.defectId for x in arr}
            for bt in tickets:
                if bt.defectId in ids and bt.pool == "strict":
                    bt.clusterId = key

    clusters: list[BatchCluster] = []
    for cid, lst in final_buckets.items():
        parts = cid.split("::")
        # productLine::module::tag::intent[::token]
        test_module = parts[1] if len(parts) > 1 else "_unmoduled"
        title_tag = parts[2] if len(parts) > 2 else "_untagged"
        intent = parts[3] if len(parts) > 3 else "unclear"
        open_count = sum(1 for t in lst if is_open_like(t.digest.status))
        clusters.append(
            BatchCluster(
                clusterId=cid,
                testModule=test_module,
                titleTag=title_tag,
                intent=intent,  # type: ignore[arg-type]
                size=len(lst),
                openCount=open_count,
                # Post-split: only absolute size marks oversized (ratio is for split decision).
                oversized=len(lst) > fat_absolute,
                defectIds=[t.digest.defectId for t in lst],
            )
        )

    # priority sort tickets: strict first by expect quality
    def ticket_key(bt: BatchTicket) -> tuple:
        pool_rank = 0 if bt.pool == "strict" else 1 if bt.pool == "locatable_only" else 2
        return (pool_rank, _expect_rank(bt.expectQuality), bt.defectId)

    tickets.sort(key=ticket_key)
    clusters.sort(key=lambda c: (-c.openCount, -c.size, c.clusterId))
    for i, bt in enumerate(tickets):
        if bt.pool == "strict":
            bt.priority = float(i)

    return clusters, tickets
