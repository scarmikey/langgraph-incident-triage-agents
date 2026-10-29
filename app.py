import argparse
import getpass
import json
import os
from pathlib import Path
from typing import Literal, TypedDict

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from investigation import (
    investigate_deployments,
    investigate_logs,
    investigate_metrics,
    resolve_incident_service,
)

MODEL_ID = "gemini-3.7-flash"
DB_PATH = "incident_checkpoints.db"
RUNBOOK_DIR = Path("runbooks")
RESTRICTED_TERMS = (
    "delete",
    "disable",
    "drop",
    "production",
    "restart",
    "rotate",
)

ANALYSIS_SCHEMA = {
    "title": "IncidentAnalysis",
    "type": "object",
    "properties": {
        "severity": {
            "type": "string",
            "enum": ["SEV1", "SEV2", "SEV3", "SEV4"],
        },
        "summary": {"type": "string"},
        "proposed_action": {"type": "string"},
        "risk": {
            "type": "string",
            "enum": ["low", "high"],
        },
        "rationale": {"type": "string"},
    },
    "required": [
        "severity",
        "summary",
        "proposed_action",
        "risk",
        "rationale",
    ],
}


class IncidentState(TypedDict, total=False):
    incident_id: str
    incident: str
    analysis: dict[str, str]
    requires_approval: bool
    policy_reason: str
    decision: bool
    status: str
    audit_log: list[str]
    runbook_path: str
    service: str
    owner_team: str
    owner_on_call: str
    approval_reviewer: str
    rejection_reason: str
    logs_findings: str
    deployment_findings: str
    metrics_findings: str


def resolve_service(state: IncidentState):
    service = resolve_incident_service(state["incident_id"])

    services_path = Path("data/services.json")
    services = json.loads(services_path.read_text(encoding="utf-8"))
    service_config = services.get(service)

    if service_config is None:
        raise ValueError(f"No configuration found for service: {service}")

    owner_team = service_config.get("team")
    if not owner_team:
        raise ValueError(f"No owning team configured for service: {service}")

    owner_on_call = service_config.get("on_call")
    if not owner_on_call:
        raise ValueError(f"No on-call contact configured for service: {service}")

    audit_log = state.get("audit_log", []) + [
        f"Resolved incident {state['incident_id']} to service {service}.",
        f"Resolved owning team for {service}: {owner_team}.",
        f"Resolved on-call contact for {service}: {owner_on_call}.",
    ]
    return {
        "service": service,
        "owner_team": owner_team,
        "owner_on_call": owner_on_call,
        "audit_log": audit_log,
    }


def build_analyst():
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT is not set.")

    model = ChatGoogleGenerativeAI(
        model=MODEL_ID,
        project=project_id,
        location="global",
        vertexai=True,
        max_retries=2,
    )
    return model.with_structured_output(
        schema=ANALYSIS_SCHEMA,
        method="json_schema",
    )


def safe_incident_id(incident_id: str) -> str:
    safe_id = "".join(
        character
        for character in incident_id
        if character.isalnum() or character in {"-", "_"}
    )
    if not any(character.isalnum() for character in safe_id):
        raise ValueError("Incident ID must contain a letter or number.")
    return safe_id


def analyze_incident(state: IncidentState):
    analyst = build_analyst()

    investigation_context = (
        f"Service: {state['service']}\n\n"
        f"Logs:\n{state['logs_findings']}\n\n"
        f"Recent deployments:\n{state['deployment_findings']}\n\n"
        f"Metrics:\n{state['metrics_findings']}"
    )

    analysis = analyst.invoke(
        [
            (
                "system",
                "You are an SRE incident analyst. Classify the incident and "
                "propose one reversible remediation step. Keep every field "
                "concise. Use the supplied investigation findings as evidence. "
                "Distinguish observed facts from hypotheses; do not claim a "
                "root cause unless the evidence supports it.",
            ),
            (
                "human",
                f"Incident:\n{state['incident']}\n\n"
                f"Investigation findings:\n{investigation_context}",
            ),
        ]
    )

    return {
        "analysis": analysis,
        "status": "analyzed",
        "audit_log": state.get("audit_log", [])
        + ["Model produced structured incident analysis using investigation findings."],
    }

def policy_check(state: IncidentState):
    analysis = state["analysis"]
    searchable_text = (
        f"{state['incident']} {analysis['proposed_action']}"
    ).lower()
    severity_requires_review = analysis["severity"] in {"SEV1", "SEV2"}
    term_requires_review = any(
        term in searchable_text for term in RESTRICTED_TERMS
    )
    requires_approval = severity_requires_review or term_requires_review
    reason = (
        "High severity or restricted operational language detected."
        if requires_approval
        else "No high-risk policy rule matched."
    )
    return {
        "requires_approval": requires_approval,
        "policy_reason": reason,
        "status": "policy_checked",
        "audit_log": state["audit_log"] + [f"Policy check: {reason}"],
    }


def policy_route(state: IncidentState) -> Literal["approval_gate", "publish_runbook"]:
    return "approval_gate" if state["requires_approval"] else "publish_runbook"


def approval_gate(state: IncidentState):
    response = interrupt(
        {
            "question": "Approve this remediation proposal?",
            "incident_id": state["incident_id"],
            "incident": state["incident"],
            "analysis": state["analysis"],
            "policy_reason": state["policy_reason"],
            "service": state.get("service"),
            "owning_team": state.get("owner_team"),
            "on_call": state.get("owner_on_call"),
            "allowed_decisions": ["approve", "reject"],
            "required_response": {
                "decision": "approve or reject",
                "reviewer": "name or unique reviewer identifier",
                "reason": "required when decision is reject",
            },
        }
    )

    if isinstance(response, str):
        decision = response
        reviewer = "legacy CLI (identity not supplied)"
        reason = ""
    elif isinstance(response, dict):
        decision = response.get("decision")
        reviewer = response.get("reviewer")
        reason = response.get("reason", "")
        reviewer = reviewer.strip() if isinstance(reviewer, str) else ""
        reason = reason.strip() if isinstance(reason, str) else ""
    else:
        raise ValueError(
            "Approval response must be a decision string or object."
        )

    if decision not in ("approve", "reject"):
        raise ValueError("Decision must be 'approve' or 'reject'.")
    if not reviewer:
        raise ValueError("Reviewer identity is required.")

    allowed_reviewers = {
        item.strip()
        for item in os.getenv("TRIAGE_APPROVED_REVIEWERS", "").split(",")
        if item.strip()
    }
    if not allowed_reviewers:
        raise PermissionError("No authorized reviewers are configured.")
    if reviewer not in allowed_reviewers:
        raise PermissionError("Reviewer is not authorized to make approval decisions.")

    if decision == "reject" and not reason:
        raise ValueError("A reason is required when rejecting a proposal.")

    approved = decision == "approve"
    audit_log = state.get("audit_log", []) + [
        (
            f"Approval decision: {decision} by {reviewer} "
            f"for owning team {state.get('owner_team', 'unknown')}."
        )
    ]
    if not approved:
        audit_log.append(f"Rejection reason: {reason}")

    return {
        "decision": approved,
        "approval_reviewer": reviewer,
        "rejection_reason": reason if not approved else "",
        "status": "approved" if approved else "rejected",
        "audit_log": audit_log,
    }


def approval_route(state: IncidentState) -> Literal["publish_runbook", "reject_runbook"]:
    return "publish_runbook" if state["decision"] else "reject_runbook"


def publish_runbook(state: IncidentState):
    RUNBOOK_DIR.mkdir(exist_ok=True)
    path = RUNBOOK_DIR / f"{safe_incident_id(state['incident_id'])}.md"
    analysis = state["analysis"]
    approval_outcome = "Approved" if state.get("decision") else "Not required by policy"
    audit_log = state["audit_log"] + [f"Published runbook to {path}."]
    audit_lines = "\n".join(f"- {entry}" for entry in audit_log)

    path.write_text(
        "# Policy-Controlled Incident Runbook\n\n"
        f"Incident ID: {state['incident_id']}\n\n"
        f"Incident: {state['incident']}\n\n"
        f"Owning team: {state.get('owner_team', 'Not specified')}\n\n"
        f"On-call contact: {state.get('owner_on_call', 'Not specified')}\n\n"
        f"Severity: {analysis['severity']}\n\n"
        f"Summary: {analysis['summary']}\n\n"
        f"Proposed action: {analysis['proposed_action']}\n\n"
        f"Rationale: {analysis['rationale']}\n\n"
        f"Model risk: {analysis['risk']}\n\n"
        f"Policy result: {state['policy_reason']}\n\n"
        f"Approval outcome: {approval_outcome}\n\n"
        f"Approval reviewer: {state.get('approval_reviewer', 'Not required')}\n\n"
        "Investigation findings:\n\n"
        f"Service: {state['service']}\n\n"
        f"Logs:\n{state['logs_findings']}\n\n"
        f"Deployments:\n{state['deployment_findings']}\n\n"
        f"Metrics:\n{state['metrics_findings']}\n\n"
        "Audit log:\n"
        f"{audit_lines}\n",
        encoding="utf-8",
    )
    return {
        "status": "published",
        "runbook_path": str(path),
        "audit_log": audit_log,
    }


def reject_runbook(state: IncidentState):
    return {
        "status": "rejected_without_publish",
        "audit_log": state["audit_log"] + ["Publishing was skipped."],
    }


def build_graph(checkpointer: SqliteSaver):
    builder = StateGraph(IncidentState)

    builder.add_node("resolve_service", resolve_service)
    builder.add_node("logs_specialist", investigate_logs)
    builder.add_node("deployment_specialist", investigate_deployments)
    builder.add_node("metrics_specialist", investigate_metrics)
    builder.add_node("analyze_incident", analyze_incident)
    builder.add_node("policy_check", policy_check)
    builder.add_node("approval_gate", approval_gate)
    builder.add_node("publish_runbook", publish_runbook)
    builder.add_node("reject_runbook", reject_runbook)

    # Resolve the incident, then run the three specialists in parallel.
    builder.add_edge(START, "resolve_service")
    builder.add_edge("resolve_service", "logs_specialist")
    builder.add_edge("resolve_service", "deployment_specialist")
    builder.add_edge("resolve_service", "metrics_specialist")

    # Do not analyze until all three specialists have completed.
    builder.add_edge(
        ["logs_specialist", "deployment_specialist", "metrics_specialist"],
        "analyze_incident",
    )

    # Preserve the original policy, approval, rejection, and publishing flow.
    builder.add_edge("analyze_incident", "policy_check")
    builder.add_conditional_edges("policy_check", policy_route)
    builder.add_conditional_edges("approval_gate", approval_route)
    builder.add_edge("publish_runbook", END)
    builder.add_edge("reject_runbook", END)

    return builder.compile(checkpointer=checkpointer)

def display_stream(stream):
    final_state = stream.output
    if stream.interrupted:
        print("WORKFLOW PAUSED")
        print(json.dumps(stream.interrupts[0].value, indent=2))
        return

    print("WORKFLOW COMPLETE")
    print(json.dumps(final_state, indent=2))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run a resumable incident-triage workflow."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--thread", required=True)
    start_parser.add_argument("--incident", required=True)

    resume_parser = subparsers.add_parser("resume")
    resume_parser.add_argument("--thread", required=True)
    resume_parser.add_argument(
        "--decision",
        choices=["approve", "reject"],
        required=True,
    )
    resume_parser.add_argument(
        "--reviewer",
        default=getpass.getuser(),
        help="Reviewer identifier recorded in the audit log.",
    )
    resume_parser.add_argument(
        "--reason",
        default="",
        help="Required explanation when rejecting a proposal.",
    )

    return parser.parse_args()


def main():
    args = parse_args()
    config = {"configurable": {"thread_id": args.thread}}

    with SqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        graph = build_graph(checkpointer)

        if args.command == "start":
            graph_input = {
                "incident_id": args.thread,
                "incident": args.incident,
                "status": "new",
                "audit_log": [],
            }
        else:
            if not args.reviewer.strip():
                raise SystemExit("--reviewer must not be empty.")
            if args.decision == "reject" and not args.reason.strip():
                raise SystemExit(
                    "--reason is required when --decision is reject."
                )
            graph_input = Command(
                resume={
                    "decision": args.decision,
                    "reviewer": args.reviewer.strip(),
                    "reason": args.reason.strip(),
                }
            )

        stream = graph.stream_events(
            graph_input,
            config=config,
            durability="sync",
            version="v3",
        )
        display_stream(stream)


if __name__ == "__main__":
    main()

