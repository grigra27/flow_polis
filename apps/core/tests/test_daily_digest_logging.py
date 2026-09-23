"""
P2-04 (2026-09-23): daily_digest's per-item DEBUG tracing used bare
print("DEBUG: ...") calls, which land in daily-digest.log on every cron
run regardless of any log level — 2.4MB of noise drowning the actually
useful summary lines. Converted to logger.debug(), silent by default
(root logger is INFO in production) and surfaced only with --verbose.

Deliberately NOT using pytest's caplog.at_level()/set_level(): both
force the target (or root) logger's effective level to the requested
value, which would make "is DEBUG suppressed by default?" untestable —
the fixture itself would be the thing enabling it. Attaching a plain
logging.Handler instead observes exactly what the app's own level
configuration actually lets through.
"""
import logging

import pytest
from django.core.management import call_command

COMMAND_LOGGER = "apps.core.management.commands.daily_digest"


class _RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.NOTSET)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def recorder():
    handler = _RecordingHandler()
    cmd_logger = logging.getLogger(COMMAND_LOGGER)
    cmd_logger.addHandler(handler)
    try:
        yield handler
    finally:
        cmd_logger.removeHandler(handler)


def _run(*extra_args):
    call_command("daily_digest", "--test", "--no-telegram", "--no-vk", *extra_args)


@pytest.mark.django_db
def test_default_run_emits_no_debug_records(recorder):
    _run()

    debug_records = [r for r in recorder.records if r.levelno == logging.DEBUG]
    assert not debug_records, (
        "default run must not emit DEBUG-level log records (root logger is "
        f"INFO in production): {[r.getMessage() for r in debug_records]}"
    )


@pytest.mark.django_db
def test_verbose_flag_emits_debug_records(recorder):
    _run("--verbose")

    debug_records = [r for r in recorder.records if r.levelno == logging.DEBUG]
    assert debug_records, "expected --verbose to produce DEBUG log records"
    assert any("Getting logins from" in r.getMessage() for r in debug_records)


@pytest.mark.django_db
def test_verbose_does_not_leak_into_next_run(recorder):
    """
    logger = logging.getLogger(__name__) is a process-wide singleton — if
    handle() didn't restore the previous level in `finally`, a --verbose
    run would leave DEBUG enabled for every subsequent call in the same
    process (real risk: cron's daily_digest and a manual --verbose
    diagnostic run sharing a long-lived shell/worker).
    """
    _run("--verbose")
    recorder.records.clear()

    _run()

    debug_records = [r for r in recorder.records if r.levelno == logging.DEBUG]
    assert not debug_records, (
        "a prior --verbose run must not leave DEBUG enabled for later runs: "
        f"{[r.getMessage() for r in debug_records]}"
    )


def test_logger_level_restored_after_verbose_run(db):
    cmd_logger = logging.getLogger(COMMAND_LOGGER)
    original_level = cmd_logger.level

    _run("--verbose")

    assert cmd_logger.level == original_level, (
        "handle() must restore the logger's original level in finally, "
        f"got {cmd_logger.level!r} instead of {original_level!r}"
    )
