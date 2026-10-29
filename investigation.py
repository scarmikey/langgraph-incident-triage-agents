import json
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from specialists import metric_window, recent_deploys, search_logs


DATA_DIR = Path(__file__).parent / "data"


def resolve_incident_service(incident_id: str) -> str:
    """Resolve an incident ID to its affected service using local fixtures."""
    alerts = json.loads(
        (DATA_DIR / "alerts.json").read_text(encoding="utf-8")
    )

    for alert in alerts:
        if alert["id"] == incident_id:
            return alert["service"]

    raise ValueError(
        f"No service mapping found for incident {incident_id}."
    )


class InvestigationState(TypedDict, total=False):
    service: str
    logs_findings: str
    deployment_findings: str
    metrics_findings: str


def investigate_logs(state: InvestigationState):
    result = search_logs.invoke({
        "service": state["service"],
        "min_level": "WARN",
    })
    return {"logs_findings": result}


def investigate_deployments(state: InvestigationState):
    result = recent_deploys.invoke({"service": state["service"]})
    return {"deployment_findings": result}


def investigate_metrics(state: InvestigationState):
    result = metric_window.invoke({"service": state["service"]})
    return {"metrics_findings": result}


def build_investigation_graph(checkpointer: SqliteSaver):
    builder = StateGraph(InvestigationState)

    builder.add_node("logs_specialist", investigate_logs)
    builder.add_node("deployment_specialist", investigate_deployments)
    builder.add_node("metrics_specialist", investigate_metrics)

    # Fan out: all three specialists start independently.
    builder.add_edge(START, "logs_specialist")
    builder.add_edge(START, "deployment_specialist")
    builder.add_edge(START, "metrics_specialist")

    # Join: wait for all three specialists before finishing.
    builder.add_edge(
        ["logs_specialist", "deployment_specialist", "metrics_specialist"],
        END,
    )

    return builder.compile(checkpointer=checkpointer)
