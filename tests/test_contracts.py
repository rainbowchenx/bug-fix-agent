from bugfix_agent.contracts import (
    ANALYSIS_REPORT_SCHEMA_VERSION,
    CODE_KNOWLEDGE_SCHEMA_VERSION,
    safe_validate_analysis_report,
    safe_validate_code_knowledge,
    validate_analysis_report,
    validate_code_knowledge,
)


def test_code_knowledge_minimal():
    data = validate_code_knowledge(
        {
            "schemaVersion": CODE_KNOWLEDGE_SCHEMA_VERSION,
            "productLine": "hc",
            "workDir": "/tmp/w",
            "generatedAt": "2026-11-03T00:00:00Z",
            "defectCodeMatches": [],
        }
    )
    assert data.cartographyProfile == "unknown"


def test_code_knowledge_rejects_missing_product_line():
    ok, _ = safe_validate_code_knowledge(
        {
            "schemaVersion": CODE_KNOWLEDGE_SCHEMA_VERSION,
            "workDir": "/tmp/w",
            "generatedAt": "2026-11-03T00:00:00Z",
        }
    )
    assert ok is False


def test_analysis_report_requires_proposed_fix_for_plan_only():
    ok, _ = safe_validate_analysis_report(
        {
            "schemaVersion": ANALYSIS_REPORT_SCHEMA_VERSION,
            "productLine": "hc",
            "workDir": "/tmp/w",
            "generatedAt": "2026-11-03T00:00:00Z",
            "tickets": [{"defectId": "1", "outcome": "plan_only"}],
        }
    )
    assert ok is False


def test_analysis_report_requires_blockers_for_needs_info():
    ok, _ = safe_validate_analysis_report(
        {
            "schemaVersion": ANALYSIS_REPORT_SCHEMA_VERSION,
            "productLine": "hc",
            "workDir": "/tmp/w",
            "generatedAt": "2026-11-03T00:00:00Z",
            "tickets": [{"defectId": "1", "outcome": "needs_ticket_info"}],
        }
    )
    assert ok is False


def test_analysis_report_accepts_valid_bodies():
    data = validate_analysis_report(
        {
            "schemaVersion": ANALYSIS_REPORT_SCHEMA_VERSION,
            "productLine": "hc",
            "workDir": "/tmp/w",
            "generatedAt": "2026-11-03T00:00:00Z",
            "tickets": [
                {
                    "defectId": "1",
                    "outcome": "plan_only",
                    "proposedFix": {"summary": "fix layout", "steps": []},
                },
                {
                    "defectId": "2",
                    "outcome": "needs_ticket_info",
                    "blockers": {
                        "kind": "needs_ticket_info",
                        "missingInfo": ["期望结果"],
                        "detail": "",
                    },
                },
            ],
        }
    )
    assert len(data.tickets) == 2
