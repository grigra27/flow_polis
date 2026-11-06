"""Run real historical migrations in a separate, empty SQLite database.

The normal suite disables migrations. These subprocesses configure Django
directly, so they neither import runtime settings/read .env nor share its DB.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


pytestmark = [pytest.mark.migration, pytest.mark.integration]
ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = """
import contextlib
import io
import json
from pathlib import Path
import socket
import sys

root, database, installed_apps = sys.argv[1:]
sys.path.insert(0, root)

def forbid_network(*args, **kwargs):
    raise AssertionError('Migration tests must not access the network')

socket.socket.connect = forbid_network
socket.socket.connect_ex = forbid_network
socket.create_connection = forbid_network
socket.getaddrinfo = forbid_network

from django.conf import settings
installed_apps = [
    'django.contrib.admin.apps.SimpleAdminConfig'
    if app == 'django.contrib.admin' else app
    for app in json.loads(installed_apps)
]
settings.configure(
    SECRET_KEY='migration-bootstrap-test-only',  # pragma: allowlist secret
    # Skip admin autodiscovery/Excel imports; retain the same apps and graph.
    INSTALLED_APPS=installed_apps,
    DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': database}},
    MIGRATION_MODULES={},
    DEFAULT_AUTO_FIELD='django.db.models.BigAutoField',
    USE_TZ=True,
    TIME_ZONE='Europe/Moscow',
    BASE_DIR=Path(root),
    LOGGING_CONFIG=None,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
import django
django.setup()
assert 'config.settings' not in sys.modules

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

def migrate_to(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps

def quiet_command(*args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        call_command(*args, verbosity=0, stdout=io.StringIO(), **kwargs)

"""


def run_migrations(tmp_path, settings, scenario):
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            BOOTSTRAP + textwrap.dedent(scenario),
            str(ROOT),
            str(tmp_path / "migration.sqlite3"),
            json.dumps(settings.INSTALLED_APPS),
        ],
        cwd=tmp_path,
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_empty_database_migrates_and_initial_fixture_can_be_loaded_twice(
    tmp_path, settings
):
    run_migrations(
        tmp_path,
        settings,
        """
        quiet_command('migrate', interactive=False)
        from apps.insurers.models import Branch, InsuranceType, LeasingManager
        assert not Branch.objects.exists()
        assert not LeasingManager.objects.exists()
        executor = MigrationExecutor(connection)
        assert not executor.migration_plan(executor.loader.graph.leaf_nodes())

        fixture = Path(root) / 'fixtures/initial_data.json'
        expected_branches = {
            row['pk']: row['fields']['branch_name']
            for row in json.loads(fixture.read_text())
            if row['model'].lower() == 'insurers.branch'
        }
        expected_types = {
            row['pk']: (row['fields']['name'], row['fields']['is_osago'])
            for row in json.loads(fixture.read_text())
            if row['model'].lower() == 'insurers.insurancetype'
        }
        for _ in range(2):
            quiet_command('loaddata', str(fixture))
            assert dict(Branch.objects.values_list('pk', 'branch_name')) == expected_branches
            assert {
                pk: (name, is_osago)
                for pk, name, is_osago in InsuranceType.objects.values_list('pk', 'name', 'is_osago')
            } == expected_types
            assert InsuranceType.objects.get(name='ОСАГО').is_osago is True
            assert InsuranceType.objects.get(name='КАСКО').is_osago is False
            assert not LeasingManager.objects.exists()
            quiet_command('migrate', interactive=False)
        """,
    )


def test_existing_policies_keep_managers_and_branch_backfill_rules(tmp_path, settings):
    run_migrations(
        tmp_path,
        settings,
        """
        apps = migrate_to([
            ('policies', '0006_policy_policies_po_policy__44a6bf_idx'),
            ('insurers', '0007_leasingmanager'),
        ])
        Branch = apps.get_model('insurers', 'Branch')
        Manager = apps.get_model('insurers', 'LeasingManager')
        Policy = apps.get_model('policies', 'Policy')
        # The alphabetical fallback deliberately has neither the smallest PK
        # nor the most policies; each selection rule must stand on its own.
        for pk, name in [(101, 'Ярославль'), (202, 'Архангельск'), (303, 'Казань')]:
            Branch.objects.create(pk=pk, branch_name=name)
        orphan = Manager.objects.create(name='Фикстура без полисов', notes='Сохранить')
        client = apps.get_model('clients', 'Client').objects.create(client_name='Фикстура клиента')
        insurer = apps.get_model('insurers', 'Insurer').objects.create(insurer_name='Фикстура страховщика')
        insurance_type = apps.get_model('insurers', 'InsuranceType').objects.create(name='Фикстура вида')
        today = timezone.localdate()
        expected = []
        for index, (branch, manager) in enumerate([
            (101, '  Фикстура менеджера  '),
            (101, 'Фикстура менеджера'),
            (303, 'Фикстура менеджера'),
            (303, ''),
            (303, '   '),
        ]):
            number = f'FIXTURE-{index}'
            Policy.objects.create(
                policy_number=number,
                client=client,
                insurer=insurer,
                insurance_type=insurance_type,
                branch_id=branch,
                leasing_manager=manager,
                start_date=today,
                end_date=today,
                property_description='Фикстура имущества',
            )
            expected.append((number, branch, manager.strip() or 'Не указан'))

        apps = migrate_to([('policies', '0007_migrate_leasing_manager')])
        Policy = apps.get_model('policies', 'Policy')
        assert sorted(Policy.objects.values_list(
            'policy_number', 'branch_id', 'leasing_manager__name'
        )) == expected

        apps = migrate_to([('insurers', '0012_leasingmanager_branch')])
        Manager = apps.get_model('insurers', 'LeasingManager')
        assert dict(Manager.objects.values_list('name', 'branch_id')) == {
            'Фикстура менеджера': 101,
            'Не указан': 303,
            'Фикстура без полисов': 202,
        }
        assert Manager.objects.get(pk=orphan.pk).notes == 'Сохранить'
        assert set(apps.get_model('insurers', 'Branch').objects.values_list('pk', flat=True)) == {101, 202, 303}
        assert sorted(apps.get_model('policies', 'Policy').objects.values_list(
            'policy_number', 'branch_id', 'leasing_manager__name'
        )) == expected
        """,
    )


def test_real_manager_without_branches_still_requires_explicit_data_fix(
    tmp_path, settings
):
    run_migrations(
        tmp_path,
        settings,
        """
        apps = migrate_to([
            ('insurers', '0011_insurer_email_primary_insurer_email_secondary'),
            ('policies', '0020_paymentschedule_alliance_paid'),
        ])
        Manager = apps.get_model('insurers', 'LeasingManager')
        manager = Manager.objects.create(name='Существующий менеджер', notes='Не удалять')
        try:
            migrate_to([('insurers', '0012_leasingmanager_branch')])
        except RuntimeError as error:
            assert 'нет ни одной записи' in str(error)
        else:
            raise AssertionError('A real manager without a branch must not be silently modified')
        assert not apps.get_model('insurers', 'Branch').objects.exists()
        assert Manager.objects.get(pk=manager.pk).notes == 'Не удалять'
        assert ('insurers', '0012_leasingmanager_branch') not in MigrationExecutor(connection).loader.applied_migrations
        """,
    )
