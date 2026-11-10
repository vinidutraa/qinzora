import subprocess
import sys
from importlib.metadata import version

import pytest


def test_version_reports_installed_distribution_without_starting_service(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "qinzora.cli", "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"Qinzora {version('qinzora')}"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("flags", [["--model", "unused"], ["--continuity", "--present"]])
def test_incompatible_demo_flags_fail_before_startup(tmp_path, flags):
    result = subprocess.run(
        [sys.executable, "-m", "qinzora.cli", "demo", *flags],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert not list(tmp_path.iterdir())
