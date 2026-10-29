# LangGraph Incident Triage Agents

A Python incident-triage workflow built with LangGraph. The project combines parallel specialist investigations, structured AI analysis, policy-based human approval, checkpoint-backed recovery, and runbook generation.

## Engineering Highlights

- **Parallel investigation:** Independent specialists investigate application logs, recent deployments, and service metrics.
- **Failure recovery:** SQLite checkpointing preserves completed investigation results so a failed specialist can be retried without rerunning successful specialists.
- **Structured AI analysis:** Gemini generates an incident severity, summary, proposed action, risk assessment, and rationale.
- **Human approval safeguards:** High-severity incidents and proposals containing restricted operational terms are routed through an approval gate.
- **Reviewer allowlist:** Approval decisions require a reviewer ID configured in `TRIAGE_APPROVED_REVIEWERS`. Rejections require a reason.
- **Audit trail and runbooks:** The workflow records investigation and decision details and generates a Markdown runbook for approved or policy-cleared proposals.
- **Automated testing:** Pytest tests cover investigation behavior, recovery, authorization, and runbook outcomes. GitHub Actions runs the test suite on pushes and pull requests.

## Technologies

Python · LangGraph · LangChain · Google Gemini via Vertex AI · SQLite · Pytest · GitHub Actions

## Project Attribution

This repository builds on the [NextWork LangGraph incident-triage starter project](https://github.com/nextwork-projects/langgraph-incident-triage). The implementation and tests in this repository document the additional engineering work beyond the starter baseline.

## Security Note

The reviewer allowlist validates a submitted reviewer identifier; it does not independently authenticate the person's identity. Production deployments require a trusted identity provider and authorization enforced at a trusted boundary.
