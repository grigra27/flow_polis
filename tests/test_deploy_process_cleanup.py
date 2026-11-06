"""A timed-out Docker CLI must not leave a Compose child racing recovery."""

import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


SPEC = importlib.util.spec_from_file_location(
    "deploy_process_cleanup_controller",
    Path(__file__).resolve().parents[1] / "scripts/deploy/controller.py",
)
controller = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = controller
SPEC.loader.exec_module(controller)

PARENT_PROGRAM = r"""
import os, pathlib, subprocess, sys, time
directory = pathlib.Path(sys.argv[1])
(directory / "parent.pid").write_text(str(os.getpid()))
child_program = "import os,pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
subprocess.Popen([sys.executable, "-I", "-c", child_program, str(directory / "child.pid")])
while not (directory / "child.pid").exists():
    time.sleep(0.01)
time.sleep(30)
"""


def _process_info(pid):
    result = subprocess.run(
        ["/bin/ps", "-ww", "-p", str(pid), "-o", "stat=", "-o", "args="],
        capture_output=True,
        text=True,
        timeout=5,
    )
    fields = result.stdout.strip().split(maxsplit=1)
    if result.returncode or not fields:
        return False, ""
    # An orphan zombie has terminated and cannot continue a Compose operation.
    return not fields[0].startswith("Z"), fields[1] if len(fields) > 1 else ""


@pytest.mark.parametrize("capture", [False, True])
def test_timeout_terminates_cli_parent_and_its_descendant(tmp_path, capture):
    pid_files = [tmp_path / "parent.pid", tmp_path / "child.pid"]
    try:
        with pytest.raises(Exception):
            controller.command(
                [sys.executable, "-I", "-c", PARENT_PROGRAM, str(tmp_path)],
                capture=capture,
                timeout=2,
            )
        assert all(
            path.is_file() for path in pid_files
        ), "Both probe processes must start"
        pids = [int(path.read_text()) for path in pid_files]
        deadline = time.monotonic() + 2
        while (
            any(_process_info(pid)[0] for pid in pids) and time.monotonic() < deadline
        ):
            time.sleep(0.02)

        assert not any(_process_info(pid)[0] for pid in pids)
    finally:
        # Run even against the unfixed controller or after a failed assertion.
        # Verify our unique argv marker so a reused PID is never killed blindly.
        for path in reversed(pid_files):
            if path.is_file():
                pid = int(path.read_text())
                alive, arguments = _process_info(pid)
                if alive and str(tmp_path) in arguments:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
