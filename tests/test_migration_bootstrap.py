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


def test_commission_versions_preserve_every_existing_field_and_payment(
    tmp_path, settings
):
    run_migrations(
        tmp_path,
        settings,
        """
        from datetime import date
        from decimal import Decimal
        apps = migrate_to([
            ('insurers', '0015_insurancetype_needs_prolongation'),
            ('policies', '0025_flow_dfa_groups'),
        ])
        Insurer = apps.get_model('insurers', 'Insurer')
        Kind = apps.get_model('insurers', 'InsuranceType')
        Rate = apps.get_model('insurers', 'CommissionRate')
        Policy = apps.get_model('policies', 'Policy')
        Payment = apps.get_model('policies', 'PaymentSchedule')
        client = apps.get_model('clients', 'Client').objects.create(client_name='Миграция', client_inn='1234567890')
        branch = apps.get_model('insurers', 'Branch').objects.create(branch_name='Миграция')
        vsk = Insurer.objects.create(insurer_name='ВСК')
        other = Insurer.objects.create(insurer_name='Другая СК')
        old = {}
        for name, percent in [('КАСКО','25'),('Имущество','20'),('Спецтехника','25')]:
            kind = Kind.objects.create(name=name)
            old[name] = Rate.objects.create(insurer=vsk, insurance_type=kind, kv_percent=Decimal(percent))
        wrong = Rate.objects.create(insurer=other, insurance_type=old['КАСКО'].insurance_type, kv_percent=Decimal('12'))
        policies = []
        for i, start in enumerate([date(2026,8,1), date(2026,10,28), date(2026,10,30), date(2026,11,1)]):
            policy = Policy.objects.create(policy_number=f'LEGACY-{i}', client=client, branch=branch, insurer=vsk, insurance_type=old['КАСКО'].insurance_type, start_date=start, end_date=date(2027,11,1), property_description='Сохранить', info3='Исходный текст')
            policies.append(policy)
            Payment.objects.create(policy=policy, year_number=1, installment_number=1, due_date=start, insurance_sum=100000, amount=10000, commission_rate=old['КАСКО'] if i != 3 else None, kv_rub=Decimal('1234.56'), payment_info='Индивидуальная КВ', insurer_date=start if i == 0 else None)
        Payment.objects.create(policy=policies[2], year_number=2, installment_number=1, due_date=date(2027,10,30), insurance_sum=100000, amount=10000, commission_rate=wrong, kv_rub=Decimal('999.99'))
        policy_fields = [f.attname for f in Policy._meta.concrete_fields]
        payment_fields = [f.attname for f in Payment._meta.concrete_fields]
        before_policies = list(Policy.objects.order_by('pk').values(*policy_fields))
        before_payments = list(Payment.objects.order_by('pk').values(*payment_fields))
        before_rates = list(Rate.objects.order_by('pk').values('pk','insurer_id','insurance_type_id','kv_percent','created_at','updated_at'))
        apps = migrate_to([('insurers', '0017_vsk_commission_versions')])
        Policy = apps.get_model('policies', 'Policy')
        Payment = apps.get_model('policies', 'PaymentSchedule')
        Rate = apps.get_model('insurers', 'CommissionRate')
        assert list(Policy.objects.order_by('pk').values(*policy_fields)) == before_policies
        assert list(Payment.objects.order_by('pk').values(*payment_fields)) == before_payments
        assert list(Rate.objects.filter(pk__in=[r['pk'] for r in before_rates]).order_by('pk').values(*before_rates[0].keys())) == before_rates
        for policy in policies[:2]:
            migrated = Policy.objects.get(pk=policy.pk)
            assert migrated.commission_rate_id == old['КАСКО'].pk
            assert migrated.commission_rate_origin == 'legacy'
        ambiguous = Policy.objects.get(pk=policies[2].pk)
        assert ambiguous.commission_rate_id is None and ambiguous.commission_rate_origin == 'review'
        assert Payment.objects.get(policy_id=policies[3].pk).commission_rate_id is None
        assert dict(Rate.objects.filter(insurer=vsk.pk, effective_from=date(2026,9,1)).values_list('insurance_type__name','kv_percent')) == {'КАСКО':Decimal('30'),'Имущество':Decimal('25'),'Спецтехника':Decimal('30')}
        assert Rate.objects.filter(insurer=other.pk).count() == 1
        # Runtime post_save также использует billing; устанавливаем оставшийся граф.
        quiet_command('migrate', interactive=False)
        # Новый взнос старого осеннего полиса наследует 25%, новый полис — 30%.
        from apps.policies.models import Policy as LivePolicy, PaymentSchedule as LivePayment
        saved = LivePolicy.objects.get(pk=policies[1].pk)
        payment = LivePayment.objects.create(policy=saved, year_number=2, installment_number=1, due_date=date(2027,10,28), insurance_sum=100000, amount=10000)
        assert payment.commission_rate_id == old['КАСКО'].pk and payment.kv_rub == Decimal('2500')
        fresh = LivePolicy.objects.create(policy_number='NEW', client_id=client.pk, branch_id=branch.pk, insurer_id=vsk.pk, insurance_type_id=old['КАСКО'].insurance_type_id, start_date=date(2026,10,28), end_date=date(2027,10,28), property_description='Новый')
        assert fresh.commission_rate.kv_percent == Decimal('30')
    """,
    )
