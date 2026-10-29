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
