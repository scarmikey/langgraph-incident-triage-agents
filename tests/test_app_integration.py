from langgraph.checkpoint.sqlite import SqliteSaver

import app


def test_main_graph_investigates_before_analysis_and_publishes_findings(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("TRIAGE_FAIL", raising=False)
    monkeypatch.setattr(app, "RUNBOOK_DIR", tmp_path / "runbooks")

    def fake_analysis(state):
        # These assertions prove investigation finished before analysis.
        assert state["service"] == "checkout-api"
        assert state["logs_findings"].strip()
        assert "d-1042" in state["deployment_findings"]
        assert "maximumPoolSize 50 -> 5" in state["deployment_findings"]
        assert state["metrics_findings"].strip()

        return {
            "analysis": {
                "severity": "SEV3",
                "summary": "Checkout service requires investigation.",
                "proposed_action": "Review recent checkout-api metrics and logs.",
                "risk": "low",
                "rationale": "Based on the local investigation evidence.",
            },
            "status": "analyzed",
            "audit_log": state.get("audit_log", [])
            + ["Mock analyst used in integration test."],
        }

    monkeypatch.setattr(app, "analyze_incident", fake_analysis)

    config = {
        "configurable": {
            "thread_id": "test-main-graph-integration",
        }
    }

    with SqliteSaver.from_conn_string(
        str(tmp_path / "main-graph.sqlite")
    ) as checkpointer:
        graph = app.build_graph(checkpointer)
        result = graph.invoke(
            {
                "incident_id": "INC-2041",
                "incident": (
                    "checkout-api is returning HTTP 500 errors and "
                    "customers cannot complete orders."
                ),
                "status": "new",
                "audit_log": [],
            },
            config=config,
        )

    assert result["service"] == "checkout-api"
    assert result["status"] == "published"
    assert result["logs_findings"].strip()
    assert "d-1042" in result["deployment_findings"]
    assert result["metrics_findings"].strip()

    runbook = (tmp_path / "runbooks" / "INC-2041.md").read_text(
        encoding="utf-8"
    )
    assert "Investigation findings:" in runbook
    assert "d-1042" in runbook
    assert "Metrics:" in runbook
    assert "Resolved incident INC-2041 to service checkout-api." in runbook


def test_main_graph_recovers_without_repeating_completed_specialists(
    tmp_path, monkeypatch
):
    import investigation

    monkeypatch.setenv("TRIAGE_FAIL", "metrics")
    monkeypatch.setattr(app, "RUNBOOK_DIR", tmp_path / "recovery-runbooks")

    calls = {"logs": 0, "deployments": 0, "metrics": 0, "analysis": 0}

    original_logs = investigation.investigate_logs
    original_deployments = investigation.investigate_deployments
    original_metrics = investigation.investigate_metrics

    def counted_logs(state):
        calls["logs"] += 1
        return original_logs(state)

    def counted_deployments(state):
        calls["deployments"] += 1
        return original_deployments(state)

    def counted_metrics(state):
        calls["metrics"] += 1
        return original_metrics(state)

    def fake_analysis(state):
        calls["analysis"] += 1
        assert state["service"] == "checkout-api"
        assert state["logs_findings"].strip()
        assert "d-1042" in state["deployment_findings"]
        assert state["metrics_findings"].strip()

        return {
            "analysis": {
                "severity": "SEV3",
                "summary": "Checkout service requires investigation.",
                "proposed_action": "Review checkout-api evidence.",
                "risk": "low",
                "rationale": "Based on local investigation evidence.",
            },
            "status": "analyzed",
            "audit_log": state.get("audit_log", [])
            + ["Mock analyst used in recovery test."],
        }

    # app.build_graph registers these functions from the app module.
    monkeypatch.setattr(app, "investigate_logs", counted_logs)
    monkeypatch.setattr(app, "investigate_deployments", counted_deployments)
    monkeypatch.setattr(app, "investigate_metrics", counted_metrics)
    monkeypatch.setattr(app, "analyze_incident", fake_analysis)

    config = {
        "configurable": {"thread_id": "test-main-graph-recovery"}
    }
    database = str(tmp_path / "main-graph-recovery.sqlite")

    with SqliteSaver.from_conn_string(database) as checkpointer:
        graph = app.build_graph(checkpointer)

        try:
            graph.invoke(
                {
                    "incident_id": "INC-2041",
                    "incident": (
                        "checkout-api is returning HTTP 500 errors and "
                        "customers cannot complete orders."
                    ),
                    "status": "new",
                    "audit_log": [],
                },
                config=config,
            )
        except RuntimeError as error:
            assert "Metrics backend timed out" in str(error)
        else:
            raise AssertionError("Expected the simulated metrics failure.")

        assert calls == {
            "logs": 1,
            "deployments": 1,
            "metrics": 1,
            "analysis": 0,
        }

        saved_state = graph.get_state(config)
        assert saved_state.values["logs_findings"].strip()
        assert "d-1042" in saved_state.values["deployment_findings"]
        assert saved_state.next == ("metrics_specialist",)

        monkeypatch.delenv("TRIAGE_FAIL")

        result = graph.invoke(None, config=config)

    assert calls == {
        "logs": 1,
        "deployments": 1,
        "metrics": 2,
        "analysis": 1,
    }
    assert result["status"] == "published"
    assert result["metrics_findings"].strip()

    runbook = (
        tmp_path / "recovery-runbooks" / "INC-2041.md"
    ).read_text(encoding="utf-8")
    assert "d-1042" in runbook
    assert "Metrics:" in runbook


def test_end_to_end_approval_publishes_runbook(tmp_path, monkeypatch):
    from langgraph.types import Command

    monkeypatch.delenv("TRIAGE_FAIL", raising=False)
    runbook_dir = tmp_path / "approved-runbooks"
    monkeypatch.setattr(app, "RUNBOOK_DIR", runbook_dir)

    def fake_analysis(state):
        return {
            "analysis": {
                "severity": "SEV2",
                "summary": "Checkout failures require review.",
                "proposed_action": "Review checkout-api health and recent logs.",
                "risk": "medium",
                "rationale": "Mocked evidence for approval integration testing.",
            },
            "status": "analyzed",
            "audit_log": state.get("audit_log", [])
            + ["Mock analyst used in approval integration test."],
        }

    monkeypatch.setattr(app, "analyze_incident", fake_analysis)
    config = {"configurable": {"thread_id": "test-e2e-approval"}}

    with SqliteSaver.from_conn_string(str(tmp_path / "approval.sqlite")) as saver:
        graph = app.build_graph(saver)
        paused = graph.invoke(
            {
                "incident_id": "INC-2041",
                "incident": "checkout-api is returning HTTP 500 errors.",
                "status": "new",
                "audit_log": [],
            },
            config=config,
        )

        assert paused.get("__interrupt__"), "Expected graph to pause for approval."
        payload = paused["__interrupt__"][0].value
        assert payload["allowed_decisions"] == ["approve", "reject"]
        assert payload["owning_team"] == "payments"
        assert payload["on_call"] == "@payments-oncall"

        result = graph.invoke(
            Command(
                resume={
                    "decision": "approve",
                    "reviewer": "reviewer-123",
                    "reason": "",
                }
            ),
            config=config,
        )

    assert result["status"] == "published"
    assert result["approval_reviewer"] == "reviewer-123"
    assert result["owner_team"] == "payments"
    assert result["owner_on_call"] == "@payments-oncall"
    assert any("Approval decision: approve by reviewer-123" in item
               for item in result["audit_log"])

    runbook = (runbook_dir / "INC-2041.md").read_text(encoding="utf-8")
    assert "Owning team: payments" in runbook
    assert "On-call contact: @payments-oncall" in runbook
    assert "Approval reviewer: reviewer-123" in runbook


def test_end_to_end_rejection_does_not_publish_runbook(tmp_path, monkeypatch):
    from langgraph.types import Command

    monkeypatch.delenv("TRIAGE_FAIL", raising=False)
    runbook_dir = tmp_path / "rejected-runbooks"
    monkeypatch.setattr(app, "RUNBOOK_DIR", runbook_dir)

    def fake_analysis(state):
        return {
            "analysis": {
                "severity": "SEV2",
                "summary": "Checkout failures require review.",
                "proposed_action": "Review checkout-api health and recent logs.",
                "risk": "medium",
                "rationale": "Mocked evidence for rejection integration testing.",
            },
            "status": "analyzed",
            "audit_log": state.get("audit_log", [])
            + ["Mock analyst used in rejection integration test."],
        }

    monkeypatch.setattr(app, "analyze_incident", fake_analysis)
    config = {"configurable": {"thread_id": "test-e2e-rejection"}}
    rejection_reason = "Evidence is insufficient; investigate further first."

    with SqliteSaver.from_conn_string(str(tmp_path / "rejection.sqlite")) as saver:
        graph = app.build_graph(saver)
        paused = graph.invoke(
            {
                "incident_id": "INC-2041",
                "incident": "checkout-api is returning HTTP 500 errors.",
                "status": "new",
                "audit_log": [],
            },
            config=config,
        )

        assert paused.get("__interrupt__"), "Expected graph to pause for approval."

        result = graph.invoke(
            Command(
                resume={
                    "decision": "reject",
                    "reviewer": "reviewer-456",
                    "reason": rejection_reason,
                }
            ),
            config=config,
        )

    assert result["status"] == "rejected_without_publish"
    assert result["approval_reviewer"] == "reviewer-456"
    assert result["rejection_reason"] == rejection_reason
    assert any(f"Rejection reason: {rejection_reason}" in item
               for item in result["audit_log"])
    assert not (runbook_dir / "INC-REJECT-E2E.md").exists()


