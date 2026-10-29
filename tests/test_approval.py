from pathlib import Path
import pytest
import app


def make_state():
    return {
        "incident_id": "INC-2041",
        "incident": "Checkout API is returning HTTP 500 errors.",
        "analysis": {
            "severity": "SEV2",
            "summary": "Checkout errors increased.",
            "proposed_action": "Investigate the connection pool configuration.",
            "risk": "high",
            "rationale": "Recent deployment changed the pool size.",
        },
        "policy_reason": "High severity requires review.",
        "service": "checkout-api",
        "owner_team": "payments",
        "owner_on_call": "@payments-oncall",
        "audit_log": [],
    }


def test_approval_records_reviewer_and_team(monkeypatch):
    monkeypatch.setenv("TRIAGE_APPROVED_REVIEWERS", "reviewer-123")
    monkeypatch.setattr(
        app,
        "interrupt",
        lambda payload: {
            "decision": "approve",
            "reviewer": "reviewer-123",
            "reason": "",
        },
    )
    result = app.approval_gate(make_state())
    assert result["decision"] is True
    assert result["approval_reviewer"] == "reviewer-123"
    assert result["status"] == "approved"
    assert any("reviewer-123" in entry for entry in result["audit_log"])
    assert any("payments" in entry for entry in result["audit_log"])


def test_rejection_records_reason(monkeypatch):
    monkeypatch.setenv("TRIAGE_APPROVED_REVIEWERS", "reviewer-456")
    monkeypatch.setattr(
        app,
        "interrupt",
        lambda payload: {
            "decision": "reject",
            "reviewer": "reviewer-456",
            "reason": "Rollback plan is missing.",
        },
    )
    result = app.approval_gate(make_state())
    assert result["decision"] is False
    assert result["status"] == "rejected"
    assert result["rejection_reason"] == "Rollback plan is missing."
    assert any(
        "Rejection reason: Rollback plan is missing." in entry
        for entry in result["audit_log"]
    )


def test_rejection_requires_reason(monkeypatch):
    monkeypatch.setenv("TRIAGE_APPROVED_REVIEWERS", "reviewer-456")
    monkeypatch.setattr(
        app,
        "interrupt",
        lambda payload: {
            "decision": "reject",
            "reviewer": "reviewer-456",
            "reason": "   ",
        },
    )
    with pytest.raises(ValueError, match="reason is required"):
        app.approval_gate(make_state())


def test_approval_requires_reviewer(monkeypatch):
    monkeypatch.setattr(
        app,
        "interrupt",
        lambda payload: {
            "decision": "approve",
            "reviewer": " ",
            "reason": "",
        },
    )
    with pytest.raises(ValueError, match="Reviewer identity is required"):
        app.approval_gate(make_state())


def test_rejection_route_skips_publication(tmp_path, monkeypatch):
    runbook_dir = tmp_path / "runbooks"
    monkeypatch.setattr(app, "RUNBOOK_DIR", runbook_dir)
    state = make_state()
    state["decision"] = False
    state["audit_log"] = ["Approval decision: reject by reviewer-456."]

    assert app.approval_route(state) == "reject_runbook"
    result = app.reject_runbook(state)
    assert result["status"] == "rejected_without_publish"
    assert result["audit_log"][-1] == "Publishing was skipped."
    assert not runbook_dir.exists()


def test_published_runbook_includes_ownership_and_reviewer(
    tmp_path, monkeypatch
):
    runbook_dir = tmp_path / "runbooks"
    monkeypatch.setattr(app, "RUNBOOK_DIR", runbook_dir)

    state = make_state()
    state.update({
        "decision": True,
        "approval_reviewer": "reviewer-123",
        "status": "approved",
        "logs_findings": "No unusual log pattern found.",
        "deployment_findings": "Recent deployment detected.",
        "metrics_findings": "HTTP 500 rate elevated.",
    })

    result = app.publish_runbook(state)
    runbook = Path(result["runbook_path"]).read_text(encoding="utf-8")

    assert result["status"] == "published"
    assert "Owning team: payments" in runbook
    assert "On-call contact: @payments-oncall" in runbook
    assert "Approval reviewer: reviewer-123" in runbook


def test_rejection_route_does_not_call_publisher(monkeypatch):
    state = make_state()
    state["decision"] = False

    def unexpected_publish(_state):
        raise AssertionError("Publisher must not run for a rejection.")

    monkeypatch.setattr(app, "publish_runbook", unexpected_publish)

    assert app.approval_route(state) == "reject_runbook"

def test_approval_denied_when_allowlist_is_missing(monkeypatch):
    monkeypatch.delenv("TRIAGE_APPROVED_REVIEWERS", raising=False)
    monkeypatch.setattr(
        app,
        "interrupt",
        lambda payload: {
            "decision": "approve",
            "reviewer": "reviewer-123",
            "reason": "",
        },
    )
    with pytest.raises(PermissionError, match="No authorized reviewers"):
        app.approval_gate(make_state())


def test_approval_denied_for_unauthorized_reviewer(monkeypatch):
    monkeypatch.setenv("TRIAGE_APPROVED_REVIEWERS", "reviewer-123")
    monkeypatch.setattr(
        app,
        "interrupt",
        lambda payload: {
            "decision": "approve",
            "reviewer": "reviewer-999",
            "reason": "",
        },
    )
    with pytest.raises(PermissionError, match="not authorized"):
        app.approval_gate(make_state())
