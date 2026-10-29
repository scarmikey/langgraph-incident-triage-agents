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
