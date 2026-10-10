"""Every example runs, offline, and its checked-in fixtures are current."""

from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest

from ..conftest import ROOT

EXAMPLES = ROOT / "examples"
SCRIPTS = [
    "standalone-verification/verify_packages.py",
    "invoice-posting/invoice_agent.py",
    "chatbot-compliance/support_chatbot.py",
    "enterprise-evidence/order_gateway.py",
]


@pytest.mark.parametrize("script", SCRIPTS)
def test_example_runs(script: str) -> None:
    done = subprocess.run(
        [sys.executable, str(EXAMPLES / script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.strip()


def test_invoice_example_shows_all_three_decisions() -> None:
    out = subprocess.run(
        [sys.executable, str(EXAMPLES / "invoice-posting" / "invoice_agent.py")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for decision in ("SUPPORTED", "UNDETERMINED", "CONTRADICTED", "SOURCE_NOT_AUTHORIZED"):
        assert decision in out
    assert out.count("agent reports          accepted") == 3


def test_checked_in_fixtures_are_what_the_generator_produces() -> None:
    path = EXAMPLES / "standalone-verification" / "make_fixtures.py"
    spec = importlib.util.spec_from_file_location("make_fixtures", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, content in module.build().items():
        assert (path.parent / name).read_bytes() == content, f"{name} is stale"
