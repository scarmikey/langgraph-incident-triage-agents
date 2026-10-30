# LangGraph Incident Triage Agents

A Python-based incident triage workflow built with LangGraph. It coordinates parallel specialist investigations, uses Gemini for structured incident analysis, applies policy-based human approval, and generates Markdown runbooks.

This project extends the [NextWork LangGraph Incident Triage starter](https://github.com/nextwork-projects/langgraph-incident-triage) with additional workflow engineering, authorization safeguards, recovery behavior, testing, and continuous integration.

## Engineering Highlights

- **Parallel investigation:** Independent specialists investigate application logs, recent deployments, and service metrics.
- **Checkpoint-backed recovery:** SQLite checkpointing preserves workflow state, allowing investigation to resume after a specialist failure without repeating completed work.
- **Structured AI analysis:** Gemini produces structured incident findings, including severity, summary, proposed action, risk, and rationale.
- **Policy-based approval:** High-severity incidents and proposals containing restricted operational terms are routed through a human approval gate.
- **Reviewer authorization:** Approval and rejection decisions require a reviewer ID configured through `TRIAGE_APPROVED_REVIEWERS`.
- **Audit trail:** Investigation and decision details are recorded as part of the workflow.
- **Runbook generation:** Approved or policy-cleared proposals can produce Markdown runbooks. Rejected proposals do not proceed to publication.
- **Automated testing:** Pytest covers workflow behavior, recovery, authorization, and runbook outcomes.
- **Continuous integration:** GitHub Actions runs the test suite on pushes and pull requests.

## Architecture

Incident input → Service resolution → Parallel log, deployment, and metrics investigations → Structured Gemini analysis → Policy check → Human approval when required → Runbook generation.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Application implementation |
| LangGraph | Workflow orchestration and checkpointing |
| LangChain | Agent and tool integration |
| Google Gemini | Structured AI incident analysis |
| Vertex AI | Model access |
| SQLite | Workflow checkpoint persistence |
| Pytest | Automated testing |
| GitHub Actions | Continuous integration |

## Repository Structure

| Path | Description |
|---|---|
| `app.py` | Main incident triage workflow and CLI |
| `investigation.py` | Specialist investigation workflow and recovery logic |
| `specialists.py` | Specialist tools, model configuration, and fixture access |
| `status_page.py` | Incident status page application |
| `data/` | Sample incident, log, deployment, metric, and service data |
| `tests/` | Automated tests |
| `.github/workflows/` | GitHub Actions CI configuration |
| `requirements.txt` | Python dependencies |

The included incident and monitoring data are local sample fixtures, intended for development and testing rather than live production monitoring.

## Requirements

- Python 3.12
- A Google Cloud project
- Vertex AI API enabled
- Appropriate Google Cloud permissions and billing configuration
- Dependencies listed in `requirements.txt`

## Installation

Clone the repository:

```bash
git clone https://github.com/scarmikey/langgraph-incident-triage-agents.git
cd langgraph-incident-triage-agents
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

On Linux or macOS:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pytest
```

## Configuration

Set your Google Cloud project.

Windows PowerShell:

```powershell
$env:GOOGLE_CLOUD_PROJECT = "YOUR_PROJECT_ID"
```

Linux or macOS:

```bash
export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"
```

Ensure Google Cloud authentication and Vertex AI permissions are configured.

## Run the Workflow

Start an incident:

```bash
python app.py start --thread INC-2041 --incident "Checkout API returns HTTP 500 errors after a configuration deployment."
```

When policy requires human review, execution pauses at the approval gate.

Approve a proposal:

```bash
python app.py resume --thread INC-2041 --decision approve --reviewer reviewer-123
```

Reject a proposal:

```bash
python app.py resume --thread INC-2041 --decision reject --reviewer reviewer-123 --reason "The proposed remediation requires further investigation."
```

Use the same thread identifier when resuming a workflow.

## Reviewer Authorization

The workflow uses `TRIAGE_APPROVED_REVIEWERS` to define permitted reviewer identifiers.

Windows PowerShell:

```powershell
$env:TRIAGE_APPROVED_REVIEWERS = "reviewer-123,reviewer-456"
```

Linux or macOS:

```bash
export TRIAGE_APPROVED_REVIEWERS="reviewer-123,reviewer-456"
```

Authorization behavior:

- An unset or empty allowlist denies approval and rejection decisions.
- A reviewer ID not included in the allowlist is denied.
- Rejection decisions require a reason.

### Security Limitation

The allowlist validates a submitted reviewer identifier. It does not independently authenticate the person's real identity.

This is an interim authorization safeguard, not production-grade identity management. A production deployment should integrate a trusted identity provider and enforce authorization at a trusted security boundary.

Do not commit API keys, credentials, or sensitive environment configuration.

## Run the Tests

```bash
python -m pytest -q
```

The project has previously passed all 23 tests locally.

GitHub Actions runs the test suite automatically on pushes and pull requests.

[View GitHub Actions](https://github.com/scarmikey/langgraph-incident-triage-agents/actions)

## Current Scope and Limitations

- Incident records and telemetry are represented by local sample fixtures.
- The workflow investigates incidents and proposes remediation; it does not automatically execute infrastructure changes.
- Model analysis requires valid Google Cloud and Vertex AI configuration.
- Reviewer allowlist validation does not replace authenticated identity management.
- This is an engineering demonstration, not a production-ready incident management platform.

## Project Attribution

This repository builds on the [NextWork Build a Multi-Agent Incident Triage System with LangGraph](https://github.com/nextwork-projects/langgraph-incident-triage) starter project.

The current implementation adds workflow orchestration, specialist investigations, checkpoint-backed recovery, reviewer authorization, auditability, runbook generation, automated testing, and CI.