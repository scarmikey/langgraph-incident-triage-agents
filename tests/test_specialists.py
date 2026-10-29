import pytest

from specialists import metric_window, recent_deploys, search_logs


def test_logs_specialist_returns_checkout_evidence():
    result = search_logs.invoke({
        "service": "checkout-api",
        "min_level": "WARN",
    })
    assert isinstance(result, str)
    assert result.strip()


def test_deploy_specialist_finds_connection_pool_change():
    result = recent_deploys.invoke({"service": "checkout-api"})
    assert "d-1042" in result
    assert "maximumPoolSize 50 -> 5" in result


def test_metrics_specialist_returns_local_fixture_data(monkeypatch):
    monkeypatch.delenv("TRIAGE_FAIL", raising=False)
    result = metric_window.invoke({"service": "checkout-api"})
    assert isinstance(result, str)
    assert result.strip()


def test_metrics_specialist_can_simulate_backend_failure(monkeypatch):
    monkeypatch.setenv("TRIAGE_FAIL", "metrics")
    with pytest.raises(Exception, match="Metrics backend timed out"):
        metric_window.invoke({"service": "checkout-api"})
