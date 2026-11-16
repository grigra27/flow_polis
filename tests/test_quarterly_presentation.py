"""Квартальная презентация для лизинговой компании: слайд 1, PDF и доступ.

Цифры слайда сверяются с подробным имущественным отчётом на ту же дату
(все филиалы, «Все сделки», без лимитов ответственности).
"""

from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from PIL import Image as PILImage
from pypdf import PdfReader

from apps.clients.models import Client
from apps.insurers.models import Branch, InsuranceType, Insurer, LeasingManager
from apps.policies.models import PaymentSchedule, Policy
from apps.reports.services.property_report import build_property_report
from apps.reports.services.quarterly_presentation import (
    build_insurer_slide,
    build_quarterly_presentation,
    last_completed_quarter,
    quarter_end,
)
from apps.reports.services.quarterly_pdf import build_quarterly_pdf

AS_OF = date(2026, 9, 30)  # конец III квартала 2026
M = Decimal("1000000")


@pytest.mark.unit
@pytest.mark.parametrize(
    "year, quarter, expected",
    [
        (2026, 1, date(2026, 3, 31)),
        (2026, 2, date(2026, 6, 30)),
        (2026, 3, date(2026, 9, 30)),
        (2026, 4, date(2026, 12, 31)),
        (2024, 1, date(2024, 3, 31)),
        (2025, 1, date(2025, 3, 31)),
    ],
)
def test_quarter_end(year, quarter, expected):
    assert quarter_end(year, quarter) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "today, expected",
    [
        (date(2026, 11, 16), (2026, 3)),
        (date(2026, 10, 1), (2026, 3)),
        (date(2026, 1, 5), (2025, 4)),
        (date(2026, 4, 1), (2026, 1)),
        (date(2026, 7, 31), (2026, 2)),
    ],
)
def test_last_completed_quarter(today, expected):
    assert last_completed_quarter(today) == expected


@pytest.fixture
def refs(db):
    branch = Branch.objects.create(branch_name="Псков")
    return {
        "client": Client.objects.create(
            client_name="ООО Лизинг", client_inn="7700000301"
        ),
        "a": Insurer.objects.create(insurer_name="СК А"),
        "b": Insurer.objects.create(insurer_name="СК Б"),
        "branch": branch,
        "kasko": InsuranceType.objects.create(name="КАСКО (и)"),
        "osago": InsuranceType.objects.create(name="ОСАГО (и)", is_osago=True),
        "liability": InsuranceType.objects.create(name="Ответственность"),
        "manager": LeasingManager.objects.create(name="Бурак", branch=branch),
    }


@pytest.fixture
def make(refs):
    counter = {"n": 0}

    def make_policy(
        sums,
        start=date(2025, 11, 1),
        years=3,
        insurer="a",
        kind="kasko",
        client="client",
        dfa_active=True,
        broker=True,
    ):
        counter["n"] += 1
        policy = Policy.objects.create(
            policy_number=f"QP-{counter['n']}",
            dfa_number=f"D-QP-{counter['n']}",
            client=refs[client],
            insurer=refs[insurer] if isinstance(insurer, str) else insurer,
            branch=refs["branch"],
            insurance_type=refs[kind] if isinstance(kind, str) else kind,
            property_description="Автомобиль LADA Vesta (нов.)",
            property_year=2024,
            start_date=start,
            end_date=date(start.year + years, start.month, start.day),
            dfa_active=dfa_active,
            broker_participation=broker,
            leasing_manager=refs["manager"],
        )
        PaymentSchedule.objects.bulk_create(
            [
                PaymentSchedule(
                    policy=policy,
                    year_number=year,
                    installment_number=1,
                    due_date=date(start.year + year - 1, start.month, start.day),
                    insurance_sum=None if kind == "osago" else value,
                    amount=Decimal("1000"),
                    kv_rub=Decimal("100"),
                )
                for year, value in enumerate(sums, 1)
            ]
        )
        return policy

    return make_policy


@pytest.mark.django_db
def test_slide_matches_property_report(make):
    make([10 * M, 9 * M, 8 * M])
    make([4 * M, 3 * M, 2 * M], insurer="b")
    make([2 * M], start=date(2026, 1, 15), years=1)
    report = build_property_report(as_of=AS_OF, property_only=True)
    slide = build_insurer_slide(AS_OF)
    assert slide["total_sum"] == report["totals"]["sum"] == 16 * M
    full = {row["name"]: row["sum"] for row in report["insurers"]}
    shown = {row["name"]: row["sum"] for row in slide["rows"]}
    assert shown == full
    for row in slide["rows"]:
        assert row["share"] == next(
            r["share"] for r in report["insurers"] if r["name"] == row["name"]
        )


@pytest.mark.django_db
def test_policy_without_payments_in_quarter_is_included(make):
    # Взносы только 1 ноября: в III квартале 2026 платежей нет, полис в силе.
    make([7 * M])
    slide = build_insurer_slide(AS_OF)
    assert slide["total_sum"] == 7 * M
    assert slide["record_count"] == 1


@pytest.mark.django_db
def test_direct_deals_are_included(make):
    make([5 * M])
    make([3 * M], broker=False)
    slide = build_insurer_slide(AS_OF)
    assert slide["total_sum"] == 8 * M


@pytest.mark.django_db
def test_osago_and_liability_are_excluded(make):
    make([6 * M])
    make([Decimal("0")], kind="osago", years=1, start=date(2026, 3, 1))
    make([50 * M], kind="liability", years=1, start=date(2026, 2, 1))
    slide = build_insurer_slide(AS_OF)
    assert slide["total_sum"] == 6 * M
    assert slide["record_count"] == 1


@pytest.mark.django_db
def test_unknown_current_sum_is_not_counted(make):
    # Год 2 начался 01.08.2026, его СС не заполнена: прошлый год не подставляем.
    make([10 * M, None], start=date(2025, 8, 1), years=2)
    make([4 * M])
    report = build_property_report(as_of=AS_OF, property_only=True)
    slide = build_insurer_slide(AS_OF)
    assert report["totals"]["missing_sum_count"] == 1
    assert slide["total_sum"] == report["totals"]["sum"] == 4 * M


@pytest.mark.django_db
def test_closed_dfa_and_expired_are_excluded(make):
    make([5 * M])
    make([5 * M], dfa_active=False)
    make([5 * M], start=date(2022, 1, 1), years=1)
    assert build_insurer_slide(AS_OF)["total_sum"] == 5 * M


@pytest.fixture
def many_insurers(refs, make):
    insurers = []
    for i in range(14):
        insurer = Insurer.objects.create(insurer_name=f"СК {i:02d}")
        make([(14 - i) * M], insurer=insurer)
        insurers.append(insurer)
    return insurers


@pytest.mark.django_db
def test_other_group_keeps_all_hidden_sum(many_insurers):
    slide = build_insurer_slide(AS_OF)
    assert len(slide["rows"]) == 12
    assert slide["other_count"] == 3
    assert slide["insurer_count"] == 14
    top = slide["rows"][:11]
    assert [r["name"] for r in top] == [f"СК {i:02d}" for i in range(11)]
    assert [r["sum"] for r in top] == [(14 - i) * M for i in range(11)]
    other = slide["rows"][-1]
    assert other["name"] == "Иные"
    assert other["sum"] == 6 * M  # 3 + 2 + 1 млн скрытых
    assert other["share"] == Decimal(6) / 105 * 100
    assert other["share_display"] == "5,71%"
    assert slide["total_sum"] == 105 * M
    assert slide["total_share_display"] == "100,00%"
    # Суммы до объединения совпадают с полным отчётом.
    report = build_property_report(as_of=AS_OF, property_only=True)
    assert {r["name"]: r["sum"] for r in report["insurers"]} == {
        f"СК {i:02d}": (14 - i) * M for i in range(14)
    }


@pytest.mark.django_db
def test_twelve_insurers_fit_without_other(refs, make):
    for i in range(12):
        insurer = Insurer.objects.create(insurer_name=f"СК {i:02d}")
        make([(i + 1) * M], insurer=insurer)
    slide = build_insurer_slide(AS_OF)
    assert len(slide["rows"]) == 12
    assert slide["other_count"] == 0
    assert all(r["name"] != "Иные" for r in slide["rows"])


@pytest.mark.django_db
def test_shares_rounded_to_two_places(make):
    for _ in range(3):
        insurer = Insurer.objects.create(insurer_name=f"СК {_}")
        make([M], insurer=insurer)
    slide = build_insurer_slide(AS_OF)
    assert [r["share_display"] for r in slide["rows"]] == ["33,33%"] * 3
    assert slide["total_share_display"] == "100,00%"


@pytest.mark.django_db
def test_empty_slice(refs):
    slide = build_insurer_slide(AS_OF)
    assert slide["empty"]
    assert slide["rows"] == []
    assert slide["total_sum"] == 0
    assert slide["total_share_display"] == "—"
    presentation = build_quarterly_presentation(2026, 3)
    data = build_quarterly_pdf(presentation)
    reader = PdfReader(BytesIO(data))
    assert len(reader.pages) == 1
    assert "пусто" in reader.pages[0].extract_text()


@pytest.mark.django_db
def test_presentation_quarter_label_and_as_of():
    presentation = build_quarterly_presentation(2026, 3)
    assert presentation["as_of"] == AS_OF
    assert presentation["quarter_label"] == "III квартал 2026 года"
    assert presentation["slides"][0]["as_of"] == AS_OF


def read_pdf(data):
    assert data.startswith(b"%PDF-")
    return PdfReader(BytesIO(data))


@pytest.mark.integration
@pytest.mark.django_db
def test_view_requires_login(client, make):
    make([5 * M])
    url = reverse("reports:quarterly_presentation")
    assert client.get(url).status_code == 302
    response = client.get(url, {"format": "pdf"})
    assert response.status_code == 302
    assert "application/pdf" not in response.get("Content-Type", "")


@pytest.mark.integration
@pytest.mark.django_db
def test_view_default_quarter_and_preview(client, make):
    make([5 * M])
    client.force_login(User.objects.create_user("qp", "qp@u.ru", "x"))
    response = client.get(reverse("reports:quarterly_presentation"))
    assert response.status_code == 200
    year, quarter = last_completed_quarter(timezone.localdate())
    assert response.context["year"] == year
    assert response.context["quarter"] == quarter
    assert response.context["as_of"] == quarter_end(year, quarter)
    html = response.content.decode()
    assert "Распределение имущества по страховщикам" in html
    assert "Скачать PDF" in html
    assert "format=pdf" in html


@pytest.mark.integration
@pytest.mark.django_db
def test_view_invalid_params_fall_back_to_default(client):
    client.force_login(User.objects.create_user("qp", "qp@u.ru", "x"))
    response = client.get(
        reverse("reports:quarterly_presentation"), {"year": "abc", "quarter": "9"}
    )
    assert response.status_code == 200
    year, quarter = last_completed_quarter(timezone.localdate())
    assert (response.context["year"], response.context["quarter"]) == (year, quarter)


@pytest.mark.integration
@pytest.mark.django_db
def test_pdf_is_single_landscape_16x9_page(client, make):
    make([10 * M, 9 * M, 8 * M])
    make([4 * M], insurer="b")
    client.force_login(User.objects.create_user("qp", "qp@u.ru", "x"))
    response = client.get(
        reverse("reports:quarterly_presentation"),
        {"year": 2026, "quarter": 3, "format": "pdf"},
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == (
        'attachment; filename="quarterly_presentation_2026_Q3.pdf"'
    )
    assert response["X-Content-Type-Options"] == "nosniff"
    reader = read_pdf(response.content)
    assert len(reader.pages) == 1
    box = reader.pages[0].mediabox
    assert float(box.width) > float(box.height)
    assert float(box.width) / float(box.height) == pytest.approx(16 / 9)
    text = reader.pages[0].extract_text()
    assert "Распределение имущества по страховщикам" in text
    assert "По состоянию на 30.09.2026" in text
    assert "Итого" in text and "100,00%" in text
    assert "14 000 000" in text
    assert "флоу//полисы" in text


@pytest.mark.integration
@pytest.mark.django_db
def test_preview_and_pdf_use_same_numbers(client, make):
    make([10 * M, 9 * M, 8 * M])
    make([4 * M], insurer="b")
    client.force_login(User.objects.create_user("qp", "qp@u.ru", "x"))
    url = reverse("reports:quarterly_presentation")
    html = client.get(url, {"year": 2026, "quarter": 3}).content.decode()
    pdf = client.get(url, {"year": 2026, "quarter": 3, "format": "pdf"})
    text = read_pdf(pdf.content).pages[0].extract_text()
    slide = build_insurer_slide(AS_OF)
    for row in slide["rows"]:
        assert row["sum_display"] in html
        assert row["sum_display"] in text
    assert slide["total_sum_display"] in html and slide["total_sum_display"] in text


@pytest.mark.integration
@pytest.mark.django_db
def test_pdf_max_rows_with_long_names_stays_one_page(client, refs, make):
    for i in range(14):
        insurer = Insurer.objects.create(
            insurer_name=f"СК «Длинное название {i:02d}» "
            + "страхования имущества " * 3
        )
        make([(14 - i) * M], insurer=insurer)
    client.force_login(User.objects.create_user("qp", "qp@u.ru", "x"))
    response = client.get(
        reverse("reports:quarterly_presentation"),
        {"year": 2026, "quarter": 3, "format": "pdf"},
    )
    reader = read_pdf(response.content)
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    for i in range(11):
        assert f"СК «Длинное название {i:02d}»" in text
    assert "Иные" in text
    assert "СК «Длинное название 13»" not in text
    assert "100,00%" in text


@pytest.mark.integration
@pytest.mark.django_db
def test_exports_page_links_presentation(client):
    client.force_login(User.objects.create_user("qp", "qp@u.ru", "x"))
    html = client.get(reverse("reports:index")).content.decode()
    assert reverse("reports:quarterly_presentation") in html


@pytest.fixture
def logos(settings, tmp_path):
    """Реальные PNG-логотипы во временном MEDIA_ROOT, которые загрузит PDF."""
    settings.MEDIA_ROOT = str(tmp_path)
    settings.MEDIA_URL = "/media/"

    def make_logo(i):
        relative = f"insurer_logos/logo{i}.png"
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        PILImage.new("RGB", (64, 64), (200, 40 + i * 12, 60)).save(path)
        return relative

    return make_logo


def _pdf_page(client, **params):
    client.force_login(User.objects.create_user("qp", "qp@u.ru", "x"))
    response = client.get(
        reverse("reports:quarterly_presentation"),
        {"year": 2026, "quarter": 3, "format": "pdf", **params},
    )
    assert response.status_code == 200
    reader = read_pdf(response.content)
    assert len(reader.pages) == 1
    box = reader.pages[0].mediabox
    assert float(box.width) / float(box.height) == pytest.approx(16 / 9)
    return reader.pages[0].extract_text()


@pytest.mark.integration
@pytest.mark.django_db
def test_pdf_twelve_short_names_with_real_logos_one_page(client, refs, make, logos):
    # Регрессия: с реальными логотипами примечание уходило на вторую страницу.
    for i in range(12):
        insurer = Insurer.objects.create(insurer_name=f"СК {i:02d}", logo=logos(i))
        make([(i + 1) * M], insurer=insurer)
    text = _pdf_page(client)
    for i in range(12):
        assert f"СК {i:02d}" in text
    assert "Итого" in text and "100,00%" in text
    assert "Распределение имущества по страховщикам" in text
    assert "По состоянию на 30.09.2026" in text
    assert "без ОСАГО и лимитов ответственности." in text


@pytest.mark.integration
@pytest.mark.django_db
def test_pdf_long_names_with_logos_one_page(client, refs, make, logos):
    # Регрессия: длинные названия уводили «Итого» и примечание на вторую страницу.
    for i in range(14):
        insurer = Insurer.objects.create(
            insurer_name=f"СК «Длинное название {i:02d}» "
            + "страхования имущества " * 10,
            logo=logos(i),
        )
        make([(14 - i) * M], insurer=insurer)
    text = _pdf_page(client)
    for i in range(11):
        assert f"СК «Длинное название {i:02d}»" in text
    assert "Иные" in text
    assert "СК «Длинное название 13»" not in text
    assert "…" in text  # отображаемое название обрезано с многоточием
    assert "Итого" in text and "100,00%" in text
    assert "без ОСАГО и лимитов ответственности." in text
    slide = build_insurer_slide(AS_OF)
    for row in slide["rows"]:
        assert row["sum_display"] in text
        assert row["share_display"] in text
