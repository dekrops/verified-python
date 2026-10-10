"""The build says what it is made of, and the pins agree with each other."""

from __future__ import annotations

import re
import subprocess
import tomllib

import verified

from ..conftest import ROOT


def test_one_upstream_revision_is_pinned_everywhere() -> None:
    cargo = tomllib.loads((ROOT / "rust" / "Cargo.toml").read_text())
    revisions = {
        spec["rev"] for name, spec in cargo["dependencies"].items() if name.startswith("verified-")
    }
    info = verified.build_info()
    assert revisions == {info["upstreamRevision"]}
    assert info["verifier"] == f"verified-verifier-{info['upstreamRevision']}"
    assert re.fullmatch(r"[0-9a-f]{40}", str(info["upstreamRevision"]))
    assert info["protocols"] == ["wvp-0.1", "wvp-0.2"]
    compatibility = (ROOT / "docs" / "protocol-compatibility.md").read_text()
    assert str(info["upstreamRevision"]) in compatibility


def test_versions_agree() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    cargo = tomllib.loads((ROOT / "rust" / "Cargo.toml").read_text())["package"]
    assert project["version"] == cargo["version"] == verified.__version__


def test_the_corpus_pin_is_the_documented_one() -> None:
    done = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-s", "conformance/wvp"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if not done.stdout.strip():
        return  # an sdist or an export without git metadata
    commit = done.stdout.split()[1]
    assert commit in (ROOT / "docs" / "protocol-compatibility.md").read_text()


def test_public_names_exist() -> None:
    for name in verified.__all__:
        assert hasattr(verified, name), name
