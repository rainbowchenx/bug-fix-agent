"""Lossless source preservation; semantic relevance remains explicitly uncertain."""
import hashlib
import re
from bugfix_contracts.defect_batch import RawDefect, SourceDocument, SourceSection, InputQuality

BUSINESS_FIELDS = {"测试环境", "版本", "版本号", "产品版本", "产品型号", "出现概率", "测试数据", "前置条件", "问题", "attachments", "attachmentRefs"}

def build_source_document(raw: RawDefect) -> SourceDocument:
    text = raw.description
    matches = list(re.finditer(r"(前置条件|测试数据|操作步骤|实际结果|预期结果|问题|初步定位|附件)[：:]", text))
    sections = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append(SourceSection(name=match.group(1), start=start, end=end, text=text[start:end]))
    fields = {k:v for k,v in (raw.metadata or {}).items() if k in BUSINESS_FIELDS}
    return SourceDocument(recordId=raw.defectId, description=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), fields=fields, sections=sections)

def assess_input_quality(source: SourceDocument, observed: str, expected: str) -> InputQuality:
    issues = []
    if not expected.strip():
        issues.append("missing explicit expected behavior")
    else:
        issues.append("expected relevance requires semantic review; nonempty is not proof")
    return InputQuality(expectedOrigin=("explicit" if expected.strip() in source.description else "inferred") if expected.strip() else "absent", expectedRelevance="uncertain", issues=issues)
