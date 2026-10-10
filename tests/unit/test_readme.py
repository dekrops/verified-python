"""The README's Python examples run as written."""

from __future__ import annotations

import re
import subprocess
import sys

from ..conftest import ROOT


def test_readme_examples_run() -> None:
    blocks = re.findall(r"```python\n(.*?)```", (ROOT / "README.md").read_text(), flags=re.DOTALL)
    assert len(blocks) == 4
    for block in blocks:
        done = subprocess.run(
            [sys.executable, "-c", block],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert done.returncode == 0, f"{block}\n---\n{done.stdout}{done.stderr}"
        assert done.stdout.strip()
