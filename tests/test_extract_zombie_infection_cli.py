from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_module_mode_smoke_help() -> None:
    result = _run('-m', 'tools.extract_zombie_infection', '--help')
    assert result.returncode == 0, result.stderr
    assert 'Full extractor for 240x320-rus-zombie-infection.jar' in result.stdout


def test_cli_direct_run_smoke_help() -> None:
    result = _run('tools/extract_zombie_infection.py', '--help')
    assert result.returncode == 0, result.stderr
    assert 'Full extractor for 240x320-rus-zombie-infection.jar' in result.stdout
