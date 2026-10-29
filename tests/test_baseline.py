from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(ROOT / "app.py"), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_python_source_compiles():
    for filename in ("app.py", "specialists.py", "status_page.py"):
        source = ROOT / filename
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(source)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


def test_cli_help_lists_workflow_commands():
    result = run_cli("--help")
    assert result.returncode == 0, result.stderr
    assert "start" in result.stdout
    assert "resume" in result.stdout


def test_incident_fixtures_exist():
    expected = (
        "alerts.json",
        "logs.jsonl",
        "deploys.json",
        "metrics.json",
        "services.json",
    )
    for filename in expected:
        assert (ROOT / "data" / filename).is_file(), filename
