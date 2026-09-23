"""
Wording/formatting review (2026-09-23): daily_digest's _format_message()
was rewritten — no more ALL-CAPS headers, no more "|"-separated one-line
cards, and section spacing is now always exactly one blank line regardless
of what ran (or didn't run) above it. These tests pin the new shape down
directly against the Command's own formatting method, with hand-built
policies_data/payments_data dicts rather than the full DB-querying
pipeline (that's already covered by test_daily_digest_logging.py's
call_command tests).

Self-contained in apps/core/tests/ (not apps/policies/tests/) — builds its
own minimal Policy/PaymentSchedule directly via the ORM rather than
importing apps.policies.tests.conftest's factories, which aren't visible
here (they're registered in a sibling app's conftest, not a shared root
one).
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.clients.models import Client
from apps.core.management.commands.daily_digest import Command
from apps.insurers.models import Branch, Insurer, InsuranceType
from apps.policies.models import Policy, PaymentSchedule

EMPTY_POLICIES_DATA = {
    "created": [],
    "updated": [],
    "payment_changes": [],
    "statistics": {
        "total_created": 0,
        "total_updated": 0,
        "total_payment_changes": 0,
        "premium_sum_created": Decimal("0"),
        "kv_sum_created": Decimal("0"),
        "premium_sum_payments": Decimal("0"),
        "kv_sum_payments": Decimal("0"),
    },
}

EMPTY_PAYMENTS_DATA = {
    "due_payments": [],
    "paid_payments": [],
    "overdue_payments": [],
    "tomorrow_payments": [],
    "statistics": {
        "due_count": 0,
        "paid_count": 0,
        "paid_sum": Decimal("0"),
        "paid_kv_sum": Decimal("0"),
        "overdue_count": 0,
        "overdue_sum": Decimal("0"),
        "tomorrow_count": 0,
        "tomorrow_sum": Decimal("0"),
    },
}


@pytest.fixture
def command():
    return Command()


@pytest.fixture
def sample_policy(db):
    client = Client.objects.create(
        client_name="ООО «Ромашка»", client_inn="7700000000", notes=""
    )
    insurer = Insurer.objects.create(insurer_name="Югория", contacts="", notes="")
    branch = Branch.objects.create(branch_name="Москва")
    insurance_type = InsuranceType.objects.create(name="КАСКО")
    policy = Policy.objects.create(
        client=client,
        insurer=insurer,
        branch=branch,
        insurance_type=insurance_type,
        policy_number="POL-001",
        dfa_number="ДФА-001",
        property_description="",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=365),
        leasing_manager=None,
        franchise=Decimal("0"),
        info3="",
        info4="",
        policy_active=True,
        dfa_active=True,
    )
    PaymentSchedule.objects.create(
        policy=policy,
        year_number=1,
        installment_number=1,
        due_date=date.today(),
        amount=Decimal("196320.00"),
        insurance_sum=Decimal("1000000.00"),
        kv_rub=Decimal("58896.00"),
        payment_info="",
    )
    return policy


def _created_policies_data(policy, url):
    return {
        **EMPTY_POLICIES_DATA,
        "created": [
            {"policy": policy, "url": url, "changes": [], "change_details": []}
        ],
        "statistics": {**EMPTY_POLICIES_DATA["statistics"], "total_created": 1},
    }


@pytest.mark.django_db
def test_headers_are_not_shouting(command):
    message = command._format_message(
        "23.09.2026", [], EMPTY_POLICIES_DATA, EMPTY_PAYMENTS_DATA
    )

    assert "📊 Сводка" in message
    assert "👥 Входы" in message
    assert "📋 Полисы" in message
    # старые капс-заголовки не должны встречаться нигде
    assert "СВОДНАЯ СТАТИСТИКА" not in message
    assert "АКТИВНОСТЬ ПОЛЬЗОВАТЕЛЕЙ" not in message
    assert "ДЕТАЛИ ПО ПОЛИСАМ" not in message


@pytest.mark.django_db
def test_no_pipe_separated_dense_lines(command, sample_policy):
    url = f"https://polis.insflow.ru/policies/{sample_policy.pk}/"
    message = command._format_message(
        "23.09.2026",
        [],
        _created_policies_data(sample_policy, url),
        EMPTY_PAYMENTS_DATA,
    )

    assert "|" not in message, f"pipe-separated line survived: {message!r}"


@pytest.mark.django_db
def test_created_policy_renders_as_three_line_card(command, sample_policy):
    url = f"https://polis.insflow.ru/policies/{sample_policy.pk}/"
    message = command._format_message(
        "23.09.2026",
        [],
        _created_policies_data(sample_policy, url),
        EMPTY_PAYMENTS_DATA,
    )
    lines = message.split("\n")

    header_idx = lines.index("🆕 Созданы:")
    card = lines[header_idx + 1 : header_idx + 4]

    assert card[0] == "• ДФА-001 — ООО «Ромашка»"
    assert card[1].startswith("↳ Югория")
    assert "премия" in card[1] and "КВ" in card[1]
    assert card[2] == f"↳ 🔗 {url}"


@pytest.mark.django_db
def test_section_spacing_is_always_exactly_one_blank_line(command, sample_policy):
    """No matter what optional blocks ran above it, a section header is
    preceded by exactly one blank line — this used to depend on which
    blocks happened to run before it (the payments section, in particular,
    only appends its own separator when it has anything to show)."""
    url = f"https://polis.insflow.ru/policies/{sample_policy.pk}/"
    message = command._format_message(
        "23.09.2026",
        [],
        _created_policies_data(sample_policy, url),
        EMPTY_PAYMENTS_DATA,
    )
    lines = message.split("\n")

    for i in range(len(lines) - 1):
        assert not (lines[i] == "" and lines[i + 1] == ""), (
            f"double blank line around index {i}: " f"{lines[max(0, i - 1) : i + 3]!r}"
        )

    idx = lines.index("📋 Полисы")
    assert lines[idx - 1] == ""
    assert lines[idx - 2] != ""


@pytest.mark.django_db
def test_empty_digest_has_no_double_blank_lines(command):
    """Same spacing guarantee on the quiet, no-activity path — every
    section still renders (Сводка/Входы/Полисы), just with placeholder
    lines ('Активности не было' etc.) instead of item cards."""
    message = command._format_message(
        "23.09.2026", [], EMPTY_POLICIES_DATA, EMPTY_PAYMENTS_DATA
    )
    lines = message.split("\n")

    for i in range(len(lines) - 1):
        assert not (lines[i] == "" and lines[i + 1] == ""), (
            f"double blank line around index {i}: " f"{lines[max(0, i - 1) : i + 3]!r}"
        )
