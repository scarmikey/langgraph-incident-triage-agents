import os

from langgraph.checkpoint.sqlite import SqliteSaver

import investigation
from investigation import build_investigation_graph


def test_parallel_investigation_collects_all_three_findings(tmp_path, monkeypatch):
    monkeypatch.delenv("TRIAGE_FAIL", raising=False)
    database = str(tmp_path / "investigation.sqlite")

    with SqliteSaver.from_conn_string(database) as checkpointer:
        graph = build_investigation_graph(checkpointer)
        result = graph.invoke(
            {"service": "checkout-api"},
            config={"configurable": {"thread_id": "test-parallel-success"}},
        )

    assert result["logs_findings"].strip()
    assert "d-1042" in result["deployment_findings"]
    assert "maximumPoolSize 50 -> 5" in result["deployment_findings"]
    assert result["metrics_findings"].strip()


def test_parallel_investigation_surfaces_metrics_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIAGE_FAIL", "metrics")
    database = str(tmp_path / "investigation-failure.sqlite")

    with SqliteSaver.from_conn_string(database) as checkpointer:
        graph = build_investigation_graph(checkpointer)

        try:
            graph.invoke(
                {"service": "checkout-api"},
                config={"configurable": {"thread_id": "test-parallel-failure"}},
            )
        except RuntimeError as error:
            assert "Metrics backend timed out" in str(error)
        else:
            raise AssertionError("Expected the simulated metrics failure.")


def test_recovery_retries_only_failed_metrics_specialist(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIAGE_FAIL", "metrics")

    calls = {"logs": 0, "deployments": 0, "metrics": 0}

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

    monkeypatch.setattr(investigation, "investigate_logs", counted_logs)
    monkeypatch.setattr(
        investigation, "investigate_deployments", counted_deployments
    )
    monkeypatch.setattr(investigation, "investigate_metrics", counted_metrics)

    database = str(tmp_path / "investigation-recovery.sqlite")
    config = {"configurable": {"thread_id": "test-investigation-recovery"}}

    with SqliteSaver.from_conn_string(database) as checkpointer:
        graph = build_investigation_graph(checkpointer)

        try:
            graph.invoke({"service": "checkout-api"}, config=config)
        except RuntimeError as error:
            assert "Metrics backend timed out" in str(error)
        else:
            raise AssertionError("Expected the simulated metrics failure.")

        assert calls == {"logs": 1, "deployments": 1, "metrics": 1}

        saved_state = graph.get_state(config)
        assert saved_state.values["logs_findings"].strip()
        assert "d-1042" in saved_state.values["deployment_findings"]
        assert saved_state.next == ("metrics_specialist",)

        monkeypatch.delenv("TRIAGE_FAIL")

        result = graph.invoke(None, config=config)

    assert calls == {"logs": 1, "deployments": 1, "metrics": 2}
    assert result["logs_findings"].strip()
    assert "d-1042" in result["deployment_findings"]
    assert result["metrics_findings"].strip()
