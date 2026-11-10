import os
import stat
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


def test_init_keeps_credentials_private_and_refuses_to_replace_them(tmp_path):
    command = [sys.executable, "-m", "qinzora.cli", "init"]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0
    environment = tmp_path / ".env"
    original = environment.read_bytes()
    token = original.decode().splitlines()[0].split("=", 1)[1]
    assert len(token) >= 32 and token not in result.stdout + result.stderr
    if os.name != "nt":
        assert stat.S_IMODE(environment.stat().st_mode) == 0o600
    again = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert again.returncode == 1
    assert environment.read_bytes() == original
    assert token not in again.stdout + again.stderr
    assert "Traceback" not in again.stderr
