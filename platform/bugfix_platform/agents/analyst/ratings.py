"""Bind human judgments to an immutable report rather than a ticket title."""
import hashlib
import json
from pydantic import BaseModel, Field

class RatingBinding(BaseModel):
    product: str
    defectId: str
    attemptId: str | None = None
    reportDigest: str
    claimIds: list[str] = Field(default_factory=list)

def report_digest(report: dict) -> str:
    return hashlib.sha256(json.dumps(report,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def rating_stale(binding: RatingBinding, report: dict) -> bool:
    return binding.reportDigest != report_digest(report)
