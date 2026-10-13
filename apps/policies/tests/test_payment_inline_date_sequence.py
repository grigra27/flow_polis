"""
H-02 (2026-10-13): HTTP 500 в админке полиса при сохранении графика платежей.

PaymentSchedule.save() вызывает full_clean(), а clean() сверяет порядок дат
с платежами, УЖЕ сохранёнными в БД. Inline-formset сохраняет строки по одной,
поэтому ValidationError вылетал из save() (а не из валидации формы):
  - при создании полиса (policy_id на этапе формы ещё None — проверка
    пропускалась), прод: 2026-04-22, 2026-04-23, 2026-05-27;
  - при правке, когда новая дата строки проходила проверку против СТАРОЙ
    даты предыдущей строки в БД, но не против НОВОЙ, сохранённой первой,
    прод: policy 1100 (2026-06-23), policy 1183 (2026-08-28).

Теперь порядок проверяется в PaymentScheduleInlineFormSet.clean() по
итоговому набору строк, а ошибка показывается в форме.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from apps.policies.admin import PaymentScheduleInline
from apps.policies.models import PaymentSchedule, Policy


def _payment_row(year, installment, due_date, **extra):
    row = {
        "year_number": year,
        "installment_number": installment,
        "due_date": due_date.isoformat(),
        "insurance_sum": "1000000.00",
        "amount": "10000.00",
        "kv_rub": "1000.00",
        "paid_date": "",
        "insurer_date": "",
        "payment_info": "",
    }
    row.update(extra)
    return row


def _build_formset(admin_user, policy, rows, existing=()):
    """
    Собирает inline-formset так же, как его собирает админка полиса.
    `existing` — сохранённые платежи в порядке initial-форм, `rows` — данные
    для них (первые len(existing) строк) и для новых строк (остальные).
    """
    request = RequestFactory().post("/")
    request.user = admin_user
    inline = PaymentScheduleInline(Policy, admin.site)
    formset_class = inline.get_formset(request, policy)
    prefix = formset_class.get_default_prefix()

    data = {
        f"{prefix}-TOTAL_FORMS": str(len(rows)),
        f"{prefix}-INITIAL_FORMS": str(len(existing)),
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }
    for i, row in enumerate(rows):
        if i < len(existing):
            data[f"{prefix}-{i}-id"] = str(existing[i].pk)
        for key, value in row.items():
            data[f"{prefix}-{i}-{key}"] = value

    return formset_class(data, instance=policy, prefix=prefix)


@pytest.mark.django_db
def test_new_policy_with_out_of_order_dates_gives_form_error_not_500(
    admin_user, policy_factory
):
    """(a) Новый полис, две строки с одинаковой датой (как 2026-05-27)."""
    template = policy_factory()
    policy = Policy(
        client=template.client,
        insurer=template.insurer,
        branch=template.branch,
        insurance_type=template.insurance_type,
        policy_number="NEW-POL",
        dfa_number="NEW-DFA",
        start_date=date(2026, 5, 1),
        end_date=date(2027, 5, 1),
    )
    formset = _build_formset(
        admin_user,
        policy,
        [
            _payment_row(1, 1, date(2026, 5, 23)),
            _payment_row(1, 2, date(2026, 5, 23)),
        ],
    )

    assert not formset.is_valid()
    assert "due_date" in formset.forms[1].errors
    assert not formset.forms[0].errors


@pytest.mark.django_db
def test_moving_two_payments_earlier_with_consistent_result_saves(
    admin_user, policy_factory, payment_schedule_factory
):
    """
    (b) Обе даты сдвигаются раньше, итог корректен. Построчная проверка
    против БД отвергала вторую строку (новая дата ≤ старой даты первой).
    """
    policy = policy_factory()
    first = payment_schedule_factory(
        policy=policy, year_number=1, installment_number=1, due_date=date(2026, 9, 10)
    )
    second = payment_schedule_factory(
        policy=policy, year_number=1, installment_number=2, due_date=date(2026, 10, 10)
    )

    formset = _build_formset(
        admin_user,
        policy,
        [
            _payment_row(1, 1, date(2026, 8, 1)),
            _payment_row(1, 2, date(2026, 9, 5)),
        ],
        existing=[first, second],
    )

    assert formset.is_valid(), formset.errors
    formset.save()

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.due_date == date(2026, 8, 1)
    assert second.due_date == date(2026, 9, 5)


@pytest.mark.django_db
def test_inconsistent_result_after_editing_gives_form_error_not_500(
    admin_user, policy_factory, payment_schedule_factory
):
    """
    (c) Как policy 1183: вторая дата больше СТАРОЙ первой, но меньше НОВОЙ.
    Раньше форма проходила, а save() второй строки падал 500.
    """
    policy = policy_factory()
    first = payment_schedule_factory(
        policy=policy, year_number=1, installment_number=1, due_date=date(2026, 9, 1)
    )
    second = payment_schedule_factory(
        policy=policy, year_number=1, installment_number=2, due_date=date(2026, 10, 1)
    )

    formset = _build_formset(
        admin_user,
        policy,
        [
            _payment_row(1, 1, date(2026, 9, 5)),
            _payment_row(1, 2, date(2026, 9, 4)),
        ],
        existing=[first, second],
    )

    assert not formset.is_valid()
    assert "due_date" in formset.forms[1].errors
    assert not formset.forms[0].errors

    first.refresh_from_db()
    assert first.due_date == date(2026, 9, 1)


@pytest.mark.django_db
def test_deleted_row_is_ignored_in_sequence_check(
    admin_user, policy_factory, payment_schedule_factory
):
    """Удаляемая строка не участвует в проверке итогового порядка."""
    policy = policy_factory()
    first = payment_schedule_factory(
        policy=policy, year_number=1, installment_number=1, due_date=date(2026, 9, 1)
    )
    second = payment_schedule_factory(
        policy=policy, year_number=1, installment_number=2, due_date=date(2026, 10, 1)
    )

    formset = _build_formset(
        admin_user,
        policy,
        [
            _payment_row(1, 1, date(2026, 9, 1)),
            _payment_row(1, 2, date(2026, 10, 1), DELETE="on"),
            _payment_row(1, 3, date(2026, 9, 20)),
        ],
        existing=[first, second],
    )

    assert formset.is_valid(), formset.errors
    formset.save()

    assert list(
        PaymentSchedule.objects.filter(policy=policy)
        .order_by("installment_number")
        .values_list("installment_number", "due_date")
    ) == [(1, date(2026, 9, 1)), (3, date(2026, 9, 20))]


@pytest.mark.django_db
def test_paid_and_insurer_dates_checked_across_rows(
    admin_user, policy_factory, payment_schedule_factory
):
    """Как 2026-04-22: равные paid_date/insurer_date у соседних строк."""
    policy = policy_factory()
    first = payment_schedule_factory(
        policy=policy, year_number=3, installment_number=1, due_date=date(2025, 5, 1)
    )

    formset = _build_formset(
        admin_user,
        policy,
        [
            _payment_row(
                3,
                1,
                date(2025, 5, 1),
                paid_date="2025-05-15",
                insurer_date="2025-05-31",
            ),
            _payment_row(
                3,
                2,
                date(2025, 6, 1),
                paid_date="2025-05-15",
                insurer_date="2025-05-31",
            ),
        ],
        existing=[first],
    )

    assert not formset.is_valid()
    assert set(formset.forms[1].errors) == {"paid_date", "insurer_date"}


@pytest.mark.django_db
def test_model_save_outside_formset_still_validates_sequence(
    payment_schedule_factory,
):
    """Вне админки (скрипты, shell, другие view) модель по-прежнему защищает порядок."""
    first = payment_schedule_factory(
        year_number=1, installment_number=1, due_date=date(2026, 9, 1)
    )
    with pytest.raises(ValidationError) as exc_info:
        PaymentSchedule.objects.create(
            policy=first.policy,
            year_number=1,
            installment_number=2,
            due_date=date(2026, 8, 1),
            amount=Decimal("10000.00"),
            insurance_sum=Decimal("1000000.00"),
        )
    assert "due_date" in exc_info.value.message_dict
