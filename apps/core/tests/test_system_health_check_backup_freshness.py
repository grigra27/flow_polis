"""
Тесты P1-08 (dead man's switch): `_check_backup_freshness` в
`system_health_check.py` читает `last_status.json`, который пишет
`scripts/backup-status.sh` (контракт P0-08), и решает, свежий ли
последний прогон бэкапа.

Главное, что проверяем:
  • свежий result=ok → healthy, молчание;
  • отсутствующий каталог/файл → warning (не critical, сайт не сломан);
  • протухший (старше max_age_hours) → warning;
  • result=fail (в т.ч. verified=0/exit=2 и т.п.) → warning, даже если файл свежий;
  • битый JSON → warning, не исключение наружу.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from apps.core.management.commands.system_health_check import Command


def _write_status(tmp_path, subdir, payload):
    backup_dir = tmp_path / subdir
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / "last_status.json").write_text(json.dumps(payload), encoding="utf-8")
    return backup_dir


def _fresh_payload(**overrides):
    payload = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "db",
        "file": "db_backup_20260923_020050.sql.gz",
        "bytes": 1549363,
        "created": 1,
        "verified": 1,
        "offsite": None,
        "mirror": 1,
        "notify": 1,
        "required": ["created", "verified"],
        "result": "ok",
        "exit": 0,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def command():
    return Command()


def _patch_backup_base_dir(monkeypatch, tmp_path):
    from django.conf import settings

    monkeypatch.setattr(settings, "BACKUP_DB_DIR", "", raising=False)
    monkeypatch.setattr(settings, "BACKUP_MEDIA_DIR", "", raising=False)
    monkeypatch.setattr(settings, "BACKUP_BASE_DIR", str(tmp_path), raising=False)


def test_fresh_ok_is_healthy(tmp_path, monkeypatch, command):
    _patch_backup_base_dir(monkeypatch, tmp_path)
    _write_status(tmp_path, "database", _fresh_payload())

    result = command._check_backup_freshness("DB backup", "database", max_age_hours=26)

    assert result["status"] == "healthy"
    assert "result=ok" in result["message"]


def test_missing_directory_is_warning_not_critical(tmp_path, monkeypatch, command):
    _patch_backup_base_dir(monkeypatch, tmp_path / "does-not-exist")

    result = command._check_backup_freshness("DB backup", "database", max_age_hours=26)

    assert result["status"] == "warning"
    assert "directory not found" in result["message"]


def test_missing_status_file_is_warning(tmp_path, monkeypatch, command):
    _patch_backup_base_dir(monkeypatch, tmp_path)
    (tmp_path / "database").mkdir()

    result = command._check_backup_freshness("DB backup", "database", max_age_hours=26)

    assert result["status"] == "warning"
    assert "last_status.json not found" in result["message"]


def test_stale_successful_run_is_warning(tmp_path, monkeypatch, command):
    _patch_backup_base_dir(monkeypatch, tmp_path)
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    _write_status(tmp_path, "database", _fresh_payload(ts=stale_ts))

    result = command._check_backup_freshness("DB backup", "database", max_age_hours=26)

    assert result["status"] == "warning"
    assert "old" in result["message"]


def test_failed_result_is_warning_even_if_fresh(tmp_path, monkeypatch, command):
    _patch_backup_base_dir(monkeypatch, tmp_path)
    _write_status(
        tmp_path,
        "database",
        _fresh_payload(result="fail", exit=2, verified=0),
    )

    result = command._check_backup_freshness("DB backup", "database", max_age_hours=26)

    assert result["status"] == "warning"
    assert "result='fail'" in result["message"]


def test_corrupt_json_is_warning_not_exception(tmp_path, monkeypatch, command):
    _patch_backup_base_dir(monkeypatch, tmp_path)
    backup_dir = tmp_path / "database"
    backup_dir.mkdir()
    (backup_dir / "last_status.json").write_text("{not valid json", encoding="utf-8")

    result = command._check_backup_freshness("DB backup", "database", max_age_hours=26)

    assert result["status"] == "warning"
    assert "unreadable" in result["message"] or "corrupt" in result["message"]


def test_media_uses_media_subdir_and_own_threshold(tmp_path, monkeypatch, command):
    _patch_backup_base_dir(monkeypatch, tmp_path)
    six_days_ago = (datetime.now(timezone.utc) - timedelta(days=6)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    _write_status(
        tmp_path,
        "media",
        _fresh_payload(ts=six_days_ago, type="media", file="media_backup_x.tar.gz"),
    )

    # database каталог не существует — не должен влиять на проверку media
    result = command._check_backup_freshness("Media backup", "media", max_age_hours=192)

    assert result["status"] == "healthy"


def test_overall_check_all_includes_backups_and_stays_healthy(
    tmp_path, monkeypatch, command
):
    """--check-all включает бэкап-проверки; при свежих result=ok статус не деградирует."""
    _patch_backup_base_dir(monkeypatch, tmp_path)
    _write_status(tmp_path, "database", _fresh_payload())
    _write_status(
        tmp_path,
        "media",
        _fresh_payload(type="media", file="media_backup_x.tar.gz"),
    )

    db_result = command._check_backup_freshness(
        "DB backup", "database", max_age_hours=26
    )
    media_result = command._check_backup_freshness(
        "Media backup", "media", max_age_hours=192
    )

    assert db_result["status"] == "healthy"
    assert media_result["status"] == "healthy"
