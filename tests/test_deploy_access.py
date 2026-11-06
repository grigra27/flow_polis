"""The restricted deploy key must never gain arbitrary privileged arguments."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


SPEC = importlib.util.spec_from_file_location(
    "deploy_gate", Path(__file__).resolve().parents[1] / "scripts/deploy/gate.py"
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

REVISION = "a" * 40
UPLOAD = (
    f"upload 42278908785-1 {REVISION} insurance-broker:{REVISION}-42278908785-1 "
    f"sha256:{'b' * 64} {'c' * 64} 1073741824"
)


@pytest.mark.parametrize(
    "command",
    [
        "status",
        "activate 42278908785-1",
        "health 42278908785-1",
        "rollback 42278908785-1",
        UPLOAD,
    ],
)
def test_allowed_protocol(command):
    assert gate.parse_command(command) == command.split()


@pytest.mark.parametrize(
    "command",
    [
        None,
        "",
        "bash",
        "status; id",
        "status $(id)",
        "status `id`",
        "status\nid",
        "status\x00",
        "status\t",
        "status " + "x" * 1024,
        "'status",
        "sudo status",
        "status --help",
        "activate ../../root",
        "activate 0-1",
        "activate 1-0",
        "health 1-1 extra",
        UPLOAD.replace(REVISION, REVISION.upper()),
        UPLOAD.replace(f"insurance-broker:{REVISION}", f"insurance-broker:{'d' * 40}"),
        UPLOAD.replace("insurance-broker:", "evil:"),
        UPLOAD.replace("sha256:", "sha512:"),
        UPLOAD.replace("1073741824", "1073741825"),
        UPLOAD.replace("1073741824", "0"),
        UPLOAD.replace("1073741824", "+1"),
        UPLOAD.replace("1073741824", "01"),
    ],
)
def test_rejects_shell_and_invalid_metadata(command):
    with pytest.raises((ValueError, UnicodeError)):
        gate.parse_command(command)


def test_only_executes_fixed_sudo_controller(monkeypatch):
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", UPLOAD)
    calls = []
    monkeypatch.setattr(gate.os, "execv", lambda path, args: calls.append((path, args)))
    gate.main()
    assert calls == [
        (
            "/usr/bin/sudo",
            ["sudo", "-n", "--", gate.CONTROLLER, *UPLOAD.split()],
        )
    ]


def test_rejection_never_echoes_untrusted_command(monkeypatch, capsys):
    marker = "private-looking-untrusted-input"
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "bash " + marker)
    monkeypatch.setattr(gate.os, "execv", lambda *args: pytest.fail("execv called"))
    assert gate.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Deployment command rejected.\n"
    assert marker not in captured.err


def test_exec_failure_does_not_reveal_exception(monkeypatch, capsys):
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "status")

    def fail(*args):
        raise OSError("untrusted diagnostic")

    monkeypatch.setattr(gate.os, "execv", fail)
    assert gate.main() == 126
    assert capsys.readouterr().err == "Deployment controller unavailable.\n"


def test_isolated_gate_rejection_exposes_neither_command_nor_upload():
    result = subprocess.run(
        [sys.executable, "-I", str(Path(gate.__file__))],
        input=b"private-looking-upload-bytes",
        capture_output=True,
        env={**os.environ, "SSH_ORIGINAL_COMMAND": "bash private-looking-command"},
        timeout=5,
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == b"Deployment command rejected.\n"


def test_installer_shell_syntax():
    subprocess.run(
        ["bash", "-n", str(Path(gate.__file__).with_name("install.sh"))],
        check=True,
        capture_output=True,
        timeout=5,
    )
