from langgraph.checkpoint.sqlite import SqliteSaver

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
        except Exception as error:
            assert "Metrics backend timed out" in str(error)
        else:
            raise AssertionError("Expected the simulated metrics failure.")
