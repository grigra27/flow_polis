"""Квартальная презентация для лизинговой компании: четыре слайда, PDF и доступ.

Цифры слайдов 1–2 сверяются с подробным имущественным отчётом и полной
матрицей филиал × страховщик на ту же дату (все филиалы, «Все сделки»,
без лимитов ответственности). Слайд 3 считается по фактическим оплатам
взносов за квартал, слайд 4 раскладывает «Без брокера» слайда 3 по
филиалам и лизингополучателям на тех же парах. PDF — ровно четыре
страницы 16:9.
"""

from datetime import date
from decimal import Decimal
from io import BytesIO
from collections import Counter
from unittest import mock
import re

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from PIL import Image as PILImage
from pypdf import PdfReader

from apps.clients.models import Client
from apps.insurers.models import Branch, InsuranceType, Insurer, LeasingManager
from apps.policies.models import PaymentSchedule, Policy
from apps.reports.services import quarterly_presentation as qp_service
from apps.reports.services import quarterly_payments as qp_payments
from apps.reports.services import quarterly_pdf as qp_pdf
from apps.reports.services.property_report import (
    _matrix,
    _portfolio,
    build_property_report,
)
from apps.reports.services.quarterly_presentation import (
    HEAT_COLORS,
    build_branch_matrix_slide,
    build_insurer_slide,
    build_quarterly_presentation,
    last_completed_quarter,
    quarter_end,
)
from apps.reports.services.quarterly_pdf import build_quarterly_pdf
from apps.reports.services.quarterly_payments import (
    broker_payment_pairs,
    build_broker_slide,
    build_distribution_slide,
)

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
        branch="branch",
        renewal=False,
        termination=None,
        dfa_deactivation=None,
        policy_active=True,
        payments=None,
    ):
        counter["n"] += 1
        policy = Policy.objects.create(
            policy_number=f"QP-{counter['n']}",
            dfa_number=f"D-QP-{counter['n']}",
            client=refs[client] if isinstance(client, str) else client,
            insurer=refs[insurer] if isinstance(insurer, str) else insurer,
            branch=refs[branch] if isinstance(branch, str) else branch,
            insurance_type=refs[kind] if isinstance(kind, str) else kind,
            property_description="Автомобиль LADA Vesta (нов.)",
            property_year=2024,
            start_date=start,
            end_date=date(start.year + years, start.month, start.day),
            dfa_active=dfa_active,
            broker_participation=broker,
            renewal_to_old_dfa=renewal,
            termination_date=termination,
            dfa_deactivation_date=dfa_deactivation,
            policy_active=policy_active,
            leasing_manager=refs["manager"],
        )

        def year_sum(year):
            if kind == "osago":
                return None
            return sums[year - 1] if year - 1 < len(sums) else None

        # payments — явные строки графика: year, inst, due, paid, sum, amount, act.
        # Без него создаётся прежний график: первый взнос каждого года, без оплат.
        rows = (
            payments
            if payments is not None
            else [{"year": year} for year in range(1, len(sums) + 1)]
        )
        PaymentSchedule.objects.bulk_create(
            [
                PaymentSchedule(
                    policy=policy,
                    year_number=row.get("year", 1),
                    installment_number=row.get("inst", 1),
                    due_date=row.get(
                        "due",
                        date(
                            start.year + row.get("year", 1) - 1, start.month, start.day
                        ),
                    ),
                    insurance_sum=row.get("sum", year_sum(row.get("year", 1))),
                    amount=row.get("amount", Decimal("1000")),
                    kv_rub=Decimal("100"),
                    paid_date=row.get("paid"),
                    insurer_date=row.get("act"),
                )
                for row in rows
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
def test_portfolio_slides_report_unknown_sum_count(make):
    # Оба портфельных слайда считают одни и те же записи без СС.
    make([10 * M, None], start=date(2025, 8, 1), years=2)
    make([4 * M], insurer="b")
    assert build_insurer_slide(AS_OF)["unknown_sum_count"] == 1
    assert build_branch_matrix_slide(AS_OF)["unknown_sum_count"] == 1


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
def test_indicators_and_bars_fewer_than_five_insurers(make):
    # Топ считается по фактическому числу страховщиков: 3 вместо 5.
    for i, value in enumerate([5 * M, 3 * M, 2 * M]):
        insurer = Insurer.objects.create(insurer_name=f"СК {i}")
        make([value], insurer=insurer)
    slide = build_insurer_slide(AS_OF)
    assert slide["portfolio_display"] == "10 млн ₽"
    assert slide["top_count"] == 3
    assert slide["top_label"] == "Доля трёх крупнейших страховщиков"
    assert slide["top_share_display"] == "100,0%"
    # Полосы пропорциональны долям от наибольшей; шкала одна на слайд.
    assert [r["bar_css"] for r in slide["rows"]] == ["100.0", "60.0", "40.0"]


@pytest.mark.django_db
def test_portfolio_indicator_in_billions(make):
    make([5_330_000_000])
    slide = build_insurer_slide(AS_OF)
    assert slide["portfolio_display"] == "5,33 млрд ₽"
    assert slide["top_count"] == 1
    assert slide["top_label"] == "Доля крупнейшего страховщика"
    assert slide["top_share_display"] == "100,0%"


@pytest.mark.django_db
def test_bars_only_for_real_insurers(many_insurers):
    slide = build_insurer_slide(AS_OF)
    assert all(r["bar_css"] for r in slide["rows"][:11])
    assert slide["rows"][0]["bar_css"] == "100.0"  # наибольшая доля — вся шкала
    assert slide["rows"][-1]["bar_css"] == ""  # «Иные» и «Итого» без полос


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
    matrix_slide = build_branch_matrix_slide(AS_OF)
    assert matrix_slide["empty"]
    assert matrix_slide["rows"] == []
    assert matrix_slide["columns"] == []
    assert matrix_slide["total_sum"] == 0
    assert matrix_slide["total_sum_display"] == "—"
    presentation = build_quarterly_presentation(2026, 3)
    data = build_quarterly_pdf(presentation)
    reader = PdfReader(BytesIO(data))
    assert len(reader.pages) == 4
    assert "распределение по страховщикам пусто" in reader.pages[0].extract_text()
    assert (
        "распределение по филиалам и страховщикам пусто"
        in reader.pages[1].extract_text()
    )
    assert (
        "Нет подходящих фактических оплат за квартал" in reader.pages[2].extract_text()
    )
    assert (
        "Нет подходящих фактических оплат без участия брокера за квартал"
        in reader.pages[3].extract_text()
    )
    broker_slide = build_broker_slide(2026, 3)
    assert broker_slide["empty"]
    assert broker_slide["share_display"] == "—"
    assert broker_slide["total_display"] == "—"
    assert broker_slide["without_display"] == "—"
    assert [m["name"] for m in broker_slide["months"]] == ["Июль", "Август", "Сентябрь"]
    assert all(
        row["total_display"] == "—" and row["share_display"] == "—"
        for row in broker_slide["quarter_block"]["rows"]
    )
    distribution = build_distribution_slide(2026, 3)
    assert distribution["empty"] and not distribution["no_sums"]
    assert distribution["sum_display"] == "—"
    assert distribution["tables"] == []


@pytest.mark.django_db
def test_presentation_quarter_label_and_as_of():
    presentation = build_quarterly_presentation(2026, 3)
    assert presentation["as_of"] == AS_OF
    assert presentation["quarter_label"] == "III квартал 2026 года"
    assert [s["kind"] for s in presentation["slides"]] == [
        "insurers",
        "branch_matrix",
        "broker",
        "broker_distribution",
    ]
    assert all(s["as_of"] == AS_OF for s in presentation["slides"])


@pytest.mark.django_db
def test_presentation_order_and_single_portfolio_load(make):
    make([5 * M])
    with mock.patch.object(
        qp_service, "_portfolio", wraps=qp_service._portfolio
    ) as spy:
        presentation = build_quarterly_presentation(2026, 3)
    assert spy.call_count == 1
    slide1, slide2, slide3, slide4 = presentation["slides"]
    assert slide1["kind"] == "insurers"
    assert slide2["kind"] == "branch_matrix"
    assert slide3["kind"] == "broker"
    assert slide4["kind"] == "broker_distribution"
    assert slide1["total_sum"] == slide2["total_sum"] == 5 * M


def read_pdf(data):
    assert data.startswith(b"%PDF-")
    return PdfReader(BytesIO(data))


def _page_images(page):
    """XObject-изображения страницы: логотип бренда и логотипы страховщиков."""
    return page["/Resources"].get("/XObject", {})


def _full_matrix():
    """Полная матрица филиал × страховщик без ограничений — эталон сверки."""
    objects = _portfolio(AS_OF, None, "all", property_only=True)
    return _matrix(
        objects,
        lambda o: o.branch_id,
        lambda o: o.branch,
        lambda o: o.insurer_id,
        lambda o: o.insurer,
    )


def _matrix_cells(full):
    return {
        (row["name"], header): cell["sum"]
        for row in full["rows"]
        for header, cell in zip(full["headers"], row["cells"])
    }


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
def test_pdf_is_four_landscape_16x9_pages(client, make):
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
    assert len(reader.pages) == 4
    for page in reader.pages:
        box = page.mediabox
        assert float(box.width) > float(box.height)
        assert float(box.width) / float(box.height) == pytest.approx(16 / 9)
    first = reader.pages[0].extract_text()
    assert "Распределение имущества по страховщикам" in first
    assert "По состоянию на 30.09.2026" in first
    assert "Итого" in first and "100,00%" in first
    assert "14 000 000" in first
    second = reader.pages[1].extract_text()
    third = reader.pages[2].extract_text()
    fourth = reader.pages[3].extract_text()
    # Марка «флоу//полисы» заменена логотипом: он — картинка, а не текст,
    # и должен лежать на каждой из четырёх страниц.
    assert "флоу//полисы" not in first + second + third + fourth
    for page in reader.pages:
        assert len(_page_images(page)) == 1
    assert "Распределение имущества по филиалам и страховщикам" in second
    assert "Распределение имущества по филиалам" not in first
    assert "По состоянию на 30.09.2026" in second
    assert "Филиал" in second and "Итого" in second
    assert "14,0" in second  # общий итог в млн ₽ совпадает со слайдом 1
    assert "млн ₽" in second
    assert "Страхование с участием и без участия брокера" in third
    assert "III квартал 2026 года · По фактической дате оплаты взносов" in third
    assert "Нет подходящих фактических оплат за квартал" in third
    assert "Распределение страхования без участия брокера" in fourth
    assert "Нет подходящих фактических оплат без участия брокера за квартал" in fourth
    assert "Распределение имущества" not in third


@pytest.mark.integration
@pytest.mark.django_db
def test_preview_and_pdf_use_same_numbers(client, make):
    make([10 * M, 9 * M, 8 * M])
    make([4 * M], insurer="b")
    client.force_login(User.objects.create_user("qp", "qp@u.ru", "x"))
    url = reverse("reports:quarterly_presentation")
    html = client.get(url, {"year": 2026, "quarter": 3}).content.decode()
    pdf = client.get(url, {"year": 2026, "quarter": 3, "format": "pdf"})
    pages = [page.extract_text() for page in read_pdf(pdf.content).pages]
    slide = build_insurer_slide(AS_OF)
    for row in slide["rows"]:
        assert row["sum_display"] in html
        assert row["sum_display"] in pages[0]
    assert slide["total_sum_display"] in html and slide["total_sum_display"] in pages[0]
    matrix_slide = build_branch_matrix_slide(AS_OF)
    for row in matrix_slide["rows"]:
        assert row["total_display"] in html
        assert row["total_display"] in pages[1]
        for cell in row["cells"]:
            assert escape(cell["display"]) in html
            assert cell["display"] in pages[1]
    assert matrix_slide["total_sum_display"] in html
    assert matrix_slide["total_sum_display"] in pages[1]


@pytest.mark.integration
@pytest.mark.django_db
def test_pdf_max_rows_with_long_names_stay_within_four_pages(client, refs, make):
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
    assert len(reader.pages) == 4
    text = reader.pages[0].extract_text()
    for i in range(11):
        assert f"СК «Длинное название {i:02d}»" in text
    assert "Иные" in text
    assert "СК «Длинное название 13»" not in text
    assert "100,00%" in text
    second = reader.pages[1].extract_text()
    assert "Распределение имущества по филиалам и страховщикам" in second
    assert "Иные" in second and "страховщики" in second  # шапка без обрезки
    assert "Итого" in second


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


def _pdf_pages(client, **params):
    client.force_login(User.objects.create_user("qp", "qp@u.ru", "x"))
    response = client.get(
        reverse("reports:quarterly_presentation"),
        {"year": 2026, "quarter": 3, "format": "pdf", **params},
    )
    assert response.status_code == 200
    reader = read_pdf(response.content)
    assert len(reader.pages) == 4
    texts = []
    for page in reader.pages:
        box = page.mediabox
        assert float(box.width) > float(box.height)
        assert float(box.width) / float(box.height) == pytest.approx(16 / 9)
        texts.append(page.extract_text())
    return texts


@pytest.mark.integration
@pytest.mark.django_db
def test_pdf_twelve_short_names_with_real_logos_on_first_page(
    client, refs, make, logos
):
    # Регрессия: с реальными логотипами примечание уходило на вторую страницу.
    # Таблица слайда 1 с 12 страховщиками целиком помещается на первой странице.
    for i in range(12):
        insurer = Insurer.objects.create(insurer_name=f"СК {i:02d}", logo=logos(i))
        make([(i + 1) * M], insurer=insurer)
    pages = _pdf_pages(client)
    text = pages[0]
    for i in range(12):
        assert f"СК {i:02d}" in text
    assert "Итого" in text and "100,00%" in text
    assert "Распределение имущества по страховщикам" in text
    assert "По состоянию на 30.09.2026" in text
    assert "Страховая сумма портфеля" in text
    # Методика осталась только на сайте — из PDF её убрали.
    assert "без ОСАГО и лимитов ответственности." not in text
    assert "Распределение имущества по филиалам и страховщикам" in pages[1]


@pytest.mark.integration
@pytest.mark.django_db
def test_pdf_long_names_with_logos_on_first_page(client, refs, make, logos):
    # Регрессия: длинные названия уводили «Итого» и примечание на вторую страницу.
    for i in range(14):
        insurer = Insurer.objects.create(
            insurer_name=f"СК «Длинное название {i:02d}» "
            + "страхования имущества " * 10,
            logo=logos(i),
        )
        make([(14 - i) * M], insurer=insurer)
    pages = _pdf_pages(client)
    text = pages[0]
    for i in range(11):
        assert f"СК «Длинное название {i:02d}»" in text
    assert "Иные" in text
    assert "СК «Длинное название 13»" not in text
    assert "…" in text  # отображаемое название обрезано с многоточием
    assert "Итого" in text and "100,00%" in text
    assert "без ОСАГО и лимитов ответственности." not in text
    slide = build_insurer_slide(AS_OF)
    for row in slide["rows"]:
        assert row["sum_display"] in text
        assert row["share_display"] in text
    assert "Распределение имущества по филиалам и страховщикам" in pages[1]


# --- Слайд 2: матрица филиал × страховщик -------------------------------------


@pytest.fixture
def matrix_data(refs, make):
    """3 филиала × 3 страховщика: известные суммы, неизвестная СС и «<0,1»."""
    moscow = Branch.objects.create(branch_name="Москва")
    kazan = Branch.objects.create(branch_name="Казань")
    v = Insurer.objects.create(insurer_name="СК В")
    make([10 * M])  # Псков × А
    make([4 * M], insurer="b")  # Псков × Б
    make([6 * M], branch=moscow)  # Москва × А
    make([Decimal("2500000")], insurer=v, branch=moscow)  # Москва × В
    make([M], insurer="b", branch=kazan)  # Казань × Б
    make([Decimal("40000")], insurer=v, branch=kazan)  # Казань × В → «<0,1»
    # Казань × А: текущий страховой год без СС — прочерк, сумма не подменяется.
    make([10 * M, None], start=date(2025, 8, 1), years=2, branch=kazan)
    return {"moscow": moscow, "kazan": kazan, "v": v}


@pytest.fixture
def big_grid(refs, make):
    """12 филиалов × 9 страховщиков: ячейка (i, j) = (12−i)·(9−j) млн ₽."""
    branches = [Branch.objects.create(branch_name=f"Филиал {i:02d}") for i in range(12)]
    insurers = [Insurer.objects.create(insurer_name=f"СК {j:02d}") for j in range(9)]
    for i, branch in enumerate(branches):
        for j, insurer in enumerate(insurers):
            make([(12 - i) * (9 - j) * M], insurer=insurer, branch=branch)
    return branches, insurers


@pytest.mark.django_db
def test_branch_matrix_reconciles_with_full_matrix(matrix_data):
    full = _full_matrix()
    cells = _matrix_cells(full)
    row_totals = {r["name"]: r["total"] for r in full["rows"]}
    slide = build_branch_matrix_slide(AS_OF)
    assert [c["name"] for c in slide["columns"]] == full["headers"]
    assert [r["name"] for r in slide["rows"]] == [r["name"] for r in full["rows"]]
    for row in slide["rows"]:
        assert row["total"] == row_totals[row["name"]]
        for col, cell in zip(slide["columns"], row["cells"]):
            assert cell["sum"] == cells[(row["name"], col["name"])]
    for col in slide["columns"]:
        assert col["total"] == sum(
            (cells[(r["name"], col["name"])] for r in full["rows"]), Decimal(0)
        )
    report = build_property_report(as_of=AS_OF, property_only=True)
    assert (
        slide["total_sum"]
        == build_insurer_slide(AS_OF)["total_sum"]
        == report["totals"]["sum"]
        == Decimal("23540000")
    )
    assert {c["name"]: c["total"] for c in slide["columns"]} == {
        r["name"]: r["sum"] for r in report["insurers"]
    }


@pytest.mark.django_db
def test_branch_matrix_cell_displays_and_totals(matrix_data):
    slide = build_branch_matrix_slide(AS_OF)
    assert [c["name"] for c in slide["columns"]] == ["СК А", "СК Б", "СК В"]
    assert [c["total_display"] for c in slide["columns"]] == ["16,0", "5,0", "2,5"]
    rows = {r["name"]: r for r in slide["rows"]}
    assert [r["name"] for r in slide["rows"]] == ["Псков", "Москва", "Казань"]
    assert [c["display"] for c in rows["Псков"]["cells"]] == ["10,0", "4,0", "—"]
    assert [c["display"] for c in rows["Москва"]["cells"]] == ["6,0", "—", "2,5"]
    assert [c["display"] for c in rows["Казань"]["cells"]] == ["—", "1,0", "<0,1"]
    assert rows["Псков"]["total_display"] == "14,0"
    assert rows["Москва"]["total_display"] == "8,5"
    assert rows["Казань"]["total_display"] == "1,0"
    assert slide["total_sum_display"] == "23,5"
    assert slide["other_insurer_count"] == 0
    assert slide["other_branch_count"] == 0
    assert "7 крупнейших" not in slide["note"]
    assert "млн ₽" in slide["note"]


@pytest.mark.django_db
def test_top_combos_pick_two_largest_visible_cells(matrix_data):
    slide = build_branch_matrix_slide(AS_OF)
    assert slide["top_combos"] == [
        {"branch": "Псков", "insurer": "СК А", "display": "10,0 млн ₽"},
        {"branch": "Москва", "insurer": "СК А", "display": "6,0 млн ₽"},
    ]
    assert slide["top_combos_label"] == "Крупнейшие сочетания филиал × страховщик"


@pytest.mark.django_db
def test_top_combos_ignore_other_insurers_column(refs, make):
    # Колонка «Иные страховщики» (120 млн ₽ из 490) крупнее любой отдельной
    # ячейки, но в выводе участвуют только показанные отдельно страховщики.
    moscow = Branch.objects.create(branch_name="Москва")
    mixed = Insurer.objects.create(insurer_name="СК 01")
    make([50 * M], insurer=mixed)
    make([50 * M], insurer=mixed, branch=moscow)
    for i in range(2, 8):
        insurer = Insurer.objects.create(insurer_name=f"СК {i:02d}")
        make([45 * M], insurer=insurer)
    for i in range(8, 11):
        insurer = Insurer.objects.create(insurer_name=f"СК {i:02d}")
        make([40 * M], insurer=insurer)
    slide = build_branch_matrix_slide(AS_OF)
    assert slide["columns"][-1]["name"] == "Иные страховщики"
    assert slide["columns"][-1]["total"] == 120 * M
    assert slide["other_insurer_count"] == 3
    assert slide["top_combos"] == [
        {"branch": "Москва", "insurer": "СК 01", "display": "50,0 млн ₽"},
        {"branch": "Псков", "insurer": "СК 01", "display": "50,0 млн ₽"},
    ]
    assert slide["top_combos_label"] == "Крупнейшие сочетания филиал × страховщик"


@pytest.mark.django_db
def test_top_combos_ignore_other_branches_row(refs, make):
    # Строка «Иные филиалы» (80 млн ₽) крупнее любой отдельной ячейки,
    # но в выводе участвуют только показанные отдельно филиалы.
    wide = Branch.objects.create(branch_name="Филиал 01")
    make([50 * M], branch=wide)
    make([50 * M], branch=wide, insurer="b")
    for i in range(2, 10):
        branch = Branch.objects.create(branch_name=f"Филиал {i:02d}")
        make([45 * M], branch=branch)
    for name in ("Филиал 10", "Скрытый филиал"):
        branch = Branch.objects.create(branch_name=name)
        make([40 * M], branch=branch)
    slide = build_branch_matrix_slide(AS_OF)
    assert slide["rows"][-1]["name"] == "Иные филиалы"
    assert slide["rows"][-1]["total"] == 80 * M
    assert slide["other_branch_count"] == 2
    assert all(c["branch"] != "Скрытый филиал" for c in slide["top_combos"])
    assert slide["top_combos"] == [
        {"branch": "Филиал 01", "insurer": "СК А", "display": "50,0 млн ₽"},
        {"branch": "Филиал 01", "insurer": "СК Б", "display": "50,0 млн ₽"},
    ]


@pytest.mark.django_db
def test_top_combos_absent_without_positive_cells(refs):
    slide = build_branch_matrix_slide(AS_OF)
    assert slide["top_combos"] == []
    assert slide["top_combos_label"] == ""


@pytest.mark.django_db
def test_branch_matrix_heat_levels_and_neutral_cells(matrix_data):
    slide = build_branch_matrix_slide(AS_OF)
    expected = {"Псков": [1, 1, 0], "Москва": [1, 0, 1], "Казань": [0, 1, 1]}
    for row in slide["rows"]:
        assert [c["heat"] for c in row["cells"]] == expected[row["name"]]
    # «<0,1» — положительная сумма, первый уровень шкалы.
    kazan = next(r for r in slide["rows"] if r["name"] == "Казань")
    assert kazan["cells"][2]["display"] == "<0,1"
    assert kazan["cells"][2]["heat"] == 1


@pytest.mark.django_db
def test_branch_matrix_other_groups_and_intersection(big_grid):
    slide = build_branch_matrix_slide(AS_OF)
    assert slide["branch_count"] == 12
    assert slide["other_branch_count"] == 3
    assert slide["insurer_count"] == 9
    assert slide["other_insurer_count"] == 2
    assert len(slide["rows"]) == 10
    assert slide["rows"][-1]["name"] == "Иные филиалы"
    assert len(slide["columns"]) == 8
    assert slide["columns"][-1]["name"] == "Иные страховщики"

    full = _full_matrix()
    cells = _matrix_cells(full)
    shown_branches = [r["name"] for r in full["rows"][:9]]
    hidden_branches = [r["name"] for r in full["rows"][9:]]
    shown_insurers = full["headers"][:7]
    hidden_insurers = full["headers"][7:]
    assert [r["name"] for r in slide["rows"][:9]] == shown_branches
    assert [c["name"] for c in slide["columns"][:7]] == shown_insurers

    for row in slide["rows"][:9]:
        for col, cell in zip(slide["columns"][:7], row["cells"][:7]):
            assert cell["sum"] == cells[(row["name"], col["name"])]
        # «Иные страховщики» в строке филиала — сумма скрытых страховщиков.
        assert row["cells"][7]["sum"] == sum(
            (cells[(row["name"], h)] for h in hidden_insurers), Decimal(0)
        )
        assert row["total"] == sum(
            (cells[(row["name"], h)] for h in full["headers"]), Decimal(0)
        )
    other_row = slide["rows"][9]
    for col, cell in zip(slide["columns"][:7], other_row["cells"][:7]):
        assert cell["sum"] == sum(
            (cells[(b, col["name"])] for b in hidden_branches), Decimal(0)
        )
    # Пересечение обеих групп «Иные»: скрытые филиалы × скрытые страховщики.
    assert (
        other_row["cells"][7]["sum"]
        == sum(
            (cells[(b, h)] for b in hidden_branches for h in hidden_insurers),
            Decimal(0),
        )
        == 18 * M
    )
    assert other_row["total"] == 270 * M
    for col in slide["columns"][:7]:
        assert col["total"] == sum(
            (cells[(b, col["name"])] for b in shown_branches + hidden_branches),
            Decimal(0),
        )
    assert slide["columns"][7]["total"] == 234 * M
    assert slide["total_sum"] == 3510 * M
    assert sum((r["total"] for r in slide["rows"]), Decimal(0)) == slide["total_sum"]
    assert sum((c["total"] for c in slide["columns"]), Decimal(0)) == slide["total_sum"]
    report = build_property_report(as_of=AS_OF, property_only=True)
    assert (
        slide["total_sum"]
        == report["totals"]["sum"]
        == build_insurer_slide(AS_OF)["total_sum"]
    )
    assert "7 крупнейших" in slide["note"]
    assert "ещё 2" in slide["note"]
    assert "3 филиалов" in slide["note"]
    # «Иные» остаются нейтральными и в строках, и в столбце.
    assert all(c["heat"] == 0 for c in other_row["cells"])
    assert all(r["cells"][7]["heat"] == 0 for r in slide["rows"])


@pytest.mark.django_db
def test_other_composition_differs_between_slides(refs, make):
    moscow = Branch.objects.create(branch_name="Москва")
    for j in range(14):
        insurer = Insurer.objects.create(insurer_name=f"СК {j:02d}")
        make([(14 - j) * M], insurer=insurer)
        make([(14 - j) * M], insurer=insurer, branch=moscow)
    slide1, slide2, *_ = build_quarterly_presentation(2026, 3)["slides"]
    assert slide1["other_count"] == 3  # на слайде 1 скрыты СК 11–13
    assert slide2["other_insurer_count"] == 7  # на слайде 2 скрыты СК 07–13
    assert slide1["rows"][-1]["sum"] == 12 * M
    assert slide2["columns"][-1]["total"] == 56 * M
    assert slide1["total_sum"] == slide2["total_sum"] == 210 * M


@pytest.mark.django_db
def test_matrix_limits_exact_seven_and_ten(refs, make):
    branches = [Branch.objects.create(branch_name=f"Ф {i}") for i in range(10)]
    insurers = [Insurer.objects.create(insurer_name=f"СК {j}") for j in range(7)]
    for branch in branches:
        for insurer in insurers:
            make([M], insurer=insurer, branch=branch)
    slide = build_branch_matrix_slide(AS_OF)
    assert len(slide["columns"]) == 7
    assert slide["other_insurer_count"] == 0
    assert len(slide["rows"]) == 10
    assert slide["other_branch_count"] == 0
    assert all(c["name"] != "Иные страховщики" for c in slide["columns"])
    assert all(r["name"] != "Иные филиалы" for r in slide["rows"])
    assert slide["total_sum"] == 70 * M
    assert "7 крупнейших" not in slide["note"]


@pytest.mark.django_db
def test_matrix_groups_one_hidden_branch_and_insurer(refs, make):
    branches = [Branch.objects.create(branch_name=f"Ф {i}") for i in range(11)]
    insurers = [Insurer.objects.create(insurer_name=f"СК {j}") for j in range(8)]
    for branch in branches:
        for insurer in insurers:
            make([M], insurer=insurer, branch=branch)
    slide = build_branch_matrix_slide(AS_OF)
    assert len(slide["rows"]) == 10
    assert slide["rows"][-1]["name"] == "Иные филиалы"
    assert slide["other_branch_count"] == 2  # 11 филиалов → топ-9 + 2 скрытых
    assert len(slide["columns"]) == 8
    assert slide["columns"][-1]["name"] == "Иные страховщики"
    assert slide["rows"][-1]["cells"][-1]["sum"] == 2 * M  # 2 филиала × 1 СК
    assert slide["rows"][-1]["total"] == 16 * M
    assert slide["columns"][-1]["total"] == 11 * M
    assert slide["total_sum"] == 88 * M


@pytest.mark.django_db
def test_branch_matrix_cell_display_rules(refs, make):
    c = Insurer.objects.create(insurer_name="СК В")
    d = Insurer.objects.create(insurer_name="СК Г")
    zero_branch = Branch.objects.create(branch_name="Нулевой")
    make([Decimal("1250000")])  # 1,25 → «1,3» (ROUND_HALF_UP, не «1,2»)
    make([Decimal("40000")], insurer="b")  # положительная сумма → «<0,1»
    make([Decimal("1234560000")], insurer=c)  # разряды тысяч → «1 234,6»
    make([10 * M, None], start=date(2025, 8, 1), years=2, insurer=d)  # прочерк
    make([10 * M, None], start=date(2025, 8, 1), years=2, branch=zero_branch)
    slide = build_branch_matrix_slide(AS_OF)
    row = next(r for r in slide["rows"] if r["name"] == "Псков")
    displays = {
        col["name"]: cell["display"]
        for col, cell in zip(slide["columns"], row["cells"])
    }
    assert displays["СК А"] == "1,3"
    assert displays["СК Б"] == "<0,1"
    assert displays["СК В"] == "1 234,6"
    assert displays["СК Г"] == "—"
    assert row["total_display"] == "1 235,9"
    assert slide["total_sum_display"] == "1 235,9"
    zero = next(r for r in slide["rows"] if r["name"] == "Нулевой")
    assert zero["total_display"] == "—"
    assert all(cell["display"] == "—" for cell in zero["cells"])
    assert all(cell["heat"] == 0 for cell in zero["cells"])


@pytest.mark.unit
@pytest.mark.parametrize(
    "rub, level",
    [
        (0, 0),
        (1, 1),
        (49_999_999, 1),
        (50_000_000, 2),
        (99_999_999, 2),
        (100_000_000, 3),
        (199_999_999, 3),
        (200_000_000, 4),
        (299_999_999, 4),
        (300_000_000, 5),
        (1_000_000_000, 5),
    ],
)
def test_heat_level_boundaries(rub, level):
    assert qp_service._heat_level(Decimal(rub)) == level


@pytest.mark.django_db
def test_heat_same_sum_same_level_in_different_branches(refs, make):
    moscow = Branch.objects.create(branch_name="Москва")
    make([120 * M])  # Псков × А
    make([250 * M], insurer="b")  # Псков × Б
    make([120 * M], branch=moscow)  # Москва × А
    make([40 * M], insurer="b", branch=moscow)  # Москва × Б
    slide = build_branch_matrix_slide(AS_OF)
    rows = {r["name"]: r for r in slide["rows"]}
    # Столбцы отсортированы по убыванию итогов: СК Б (290 млн) перед СК А.
    assert [c["heat"] for c in rows["Псков"]["cells"]] == [4, 3]
    assert [c["heat"] for c in rows["Москва"]["cells"]] == [1, 3]
    assert rows["Псков"]["cells"][1]["heat"] == rows["Москва"]["cells"][1]["heat"]


def _pdf_fill_colors(page):
    data = page.get_contents().get_data()
    rects = re.findall(
        rb"([0-9.]+) ([0-9.]+) ([0-9.]+) rg\s+n?\s*[-0-9.]+ [-0-9.]+ [-0-9.]+ [-0-9.]+ re\s+f\*?",
        data,
    )
    return Counter(
        "#%02X%02X%02X" % tuple(round(float(c) * 255) for c in rgb)
        for rgb in rects
        if "#%02X%02X%02X" % tuple(round(float(c) * 255) for c in rgb) in HEAT_COLORS
    )


@pytest.mark.integration
@pytest.mark.django_db
def test_html_and_pdf_use_same_heat_levels_and_colors(client, refs, make):
    moscow = Branch.objects.create(branch_name="Москва")
    insurers = [Insurer.objects.create(insurer_name=f"СК {j}") for j in range(5)]
    unknown = Insurer.objects.create(insurer_name="СК Ж")
    for insurer, value in zip(insurers, [30 * M, 60 * M, 150 * M, 250 * M, 400 * M]):
        make([value], insurer=insurer)
        make([value], insurer=insurer, branch=moscow)
    make([10 * M, None], start=date(2025, 8, 1), years=2, insurer=unknown)
    make(
        [10 * M, None], start=date(2025, 8, 1), years=2, insurer=unknown, branch=moscow
    )

    slide = build_branch_matrix_slide(AS_OF)
    levels = Counter(c["heat"] for r in slide["rows"] for c in r["cells"] if c["heat"])
    assert levels == Counter({1: 2, 2: 2, 3: 2, 4: 2, 5: 2})

    client.force_login(User.objects.create_user("qp", "qp@u.ru", "x"))
    url = reverse("reports:quarterly_presentation")
    html = client.get(url, {"year": 2026, "quarter": 3}).content.decode()
    # Ячейки и легенда берут цвет из одной серверной палитры — инлайн-стиль.
    for color in HEAT_COLORS:
        assert html.count(f'style="background: {color};"') == 3  # 2 ячейки + легенда
    assert "qp-heat-" not in html  # HEX-дублей палитры в CSS больше нет

    response = client.get(url, {"year": 2026, "quarter": 3, "format": "pdf"})
    reader = read_pdf(response.content)
    assert len(reader.pages) == 4
    fills = _pdf_fill_colors(reader.pages[1])
    # Ячейки матрицы плюс по одному образцу каждого уровня в легенде.
    assert fills == Counter({color: 3 for color in HEAT_COLORS})
    second = reader.pages[1].extract_text()
    for item in slide["legend"]:
        assert item["label"] in second


@pytest.mark.integration
@pytest.mark.django_db
def test_pdf_header_keeps_short_names_whole(client, refs, make):
    insurer = Insurer.objects.create(insurer_name="Росгосстрах")
    make([500 * M], insurer=insurer)
    for j in range(7):
        other = Insurer.objects.create(insurer_name=f"СК {j}")
        make([(10 + j) * M], insurer=other)
    pages = _pdf_pages(client)
    lines = [line.strip() for line in pages[1].splitlines()]
    assert "Росгосстрах" in lines
    assert "Иные" in lines
    assert "страховщики" in lines


@pytest.mark.integration
@pytest.mark.django_db
def test_pdf_second_page_matrix_totals_and_note(client, matrix_data):
    pages = _pdf_pages(client)
    assert "Распределение имущества по страховщикам" in pages[0]
    second = pages[1]
    assert "Распределение имущества по филиалам и страховщикам" in second
    assert "По состоянию на 30.09.2026" in second
    assert "Филиал" in second
    slide = build_branch_matrix_slide(AS_OF)
    for col in slide["columns"]:
        assert col["name"] in second
        assert col["total_display"] in second
    for row in slide["rows"]:
        assert row["name"] in second
        assert row["total_display"] in second
        for cell in row["cells"]:
            assert cell["display"] in second
    assert slide["total_sum_display"] in second
    assert second.count("Итого") >= 2
    assert "млн ₽" in second
    assert "сочетани" in second.lower()  # вывод о крупнейших сочетаниях
    # Методика осталась только на сайте — из PDF её убрали.
    assert "без ОСАГО и лимитов ответственности." not in second


@pytest.mark.integration
@pytest.mark.django_db
def test_pdf_max_filled_matrix_stays_four_pages(client, refs, make):
    branches = [refs["branch"]] + [
        Branch.objects.create(
            branch_name=f"Филиал с длинным названием {i:02d} "
            + "обслуживания лизинга " * 4
        )
        for i in range(11)
    ]
    insurers = [
        Insurer.objects.create(
            insurer_name=f"СК «Длинное название {j:02d}» "
            + "страхования имущества " * 6
        )
        for j in range(9)
    ]
    for i, branch in enumerate(branches):
        for j, insurer in enumerate(insurers):
            make([(12 - i) * (9 - j) * M], insurer=insurer, branch=branch)
    pages = _pdf_pages(client)
    assert "Распределение имущества по страховщикам" in pages[0]
    second = pages[1]
    assert "Распределение имущества по филиалам и страховщикам" in second
    assert "Иные филиалы" in second
    assert "Иные" in second and "страховщики" in second  # шапка без обрезки
    assert "…" in second  # длинные названия обрезаны только для отображения
    slide = build_branch_matrix_slide(AS_OF)
    assert slide["total_sum_display"] in second
    assert slide["rows"][-1]["total_display"] in second
    assert slide["columns"][-1]["total_display"] in second
    assert "сочетани" in second.lower()  # вывод о крупнейших сочетаниях
    assert "млн ₽" in second
    assert "без ОСАГО и лимитов ответственности." not in second
    for label in ("до 50", "50–100", "100–200", "200–300", "от 300"):
        assert label in second  # легенда шкалы на второй странице
    # «Иные страховщики» — самый широкий обязательный заголовок шапки;
    # проверяем, что сжатие не съело его целиком.
    assert "Иные" in second


@pytest.mark.integration
@pytest.mark.django_db
def test_preview_shows_both_slides_with_same_numbers(client, matrix_data):
    client.force_login(User.objects.create_user("qp", "qp@u.ru", "x"))
    html = client.get(
        reverse("reports:quarterly_presentation"), {"year": 2026, "quarter": 3}
    ).content.decode()
    assert "Распределение имущества по страховщикам" in html
    assert "Распределение имущества по филиалам и страховщикам" in html
    assert "четыре альбомные страницы 16:9" in html
    slide = build_branch_matrix_slide(AS_OF)
    for col in slide["columns"]:
        assert col["name"] in html
        assert col["total_display"] in html
    for row in slide["rows"]:
        assert row["name"] in html
        assert row["total_display"] in html
        for cell in row["cells"]:
            assert escape(cell["display"]) in html
    assert escape(slide["note"]) in html
    assert slide["total_sum_display"] in html


# --- Слайд 3: страхование с участием и без участия брокера --------------------


def _row(slide, label, month=None):
    """Строка категории: month=None — «Итого за квартал», 0..2 — месяцы."""
    rows = (
        slide["quarter_block"]["rows"]
        if month is None
        else slide["months"][month]["rows"]
    )
    return next(r for r in rows if r["label"] == label)


def _flat(text):
    return " ".join(text.split())


def _strip_csrf(text):
    return re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', "", text)


def _pay(make, value, paid, year=1, inst=1, due=None, **policy_kwargs):
    """Полис с оплаченным взносом; СС года лежит на взносе №1 того же года."""
    first = {"year": year, "inst": 1, "sum": value, "due": due or paid}
    rows = [first]
    if inst == 1:
        first["paid"] = paid
    else:
        rows.append({"year": year, "inst": inst, "due": due or paid, "paid": paid})
    return make([value], payments=rows, **policy_kwargs)


@pytest.mark.django_db
def test_broker_quarter_boundaries_are_inclusive(make):
    _pay(make, M, date(2026, 6, 30))  # II квартал
    _pay(make, M, date(2026, 7, 1))  # первый день III
    _pay(make, M, date(2026, 9, 30))  # последний день III
    _pay(make, M, date(2026, 10, 1))  # IV квартал
    slide = build_broker_slide(2026, 3)
    assert [m["name"] for m in slide["months"]] == ["Июль", "Август", "Сентябрь"]
    assert _row(slide, "Все договоры")["total"] == 2 * M
    assert [_row(slide, "Все договоры", m)["total"] for m in range(3)] == [
        M,
        Decimal(0),
        M,
    ]
    assert _row(build_broker_slide(2026, 2), "Все договоры")["total"] == M
    assert _row(build_broker_slide(2026, 4), "Все договоры")["total"] == M


@pytest.mark.django_db
def test_broker_period_is_paid_date_not_due_or_act(make):
    # due 29.09 и акт 30.09 — III квартал, фактическая оплата 02.10 — IV.
    make(
        [10 * M],
        start=date(2026, 9, 1),
        years=1,
        payments=[
            {
                "year": 1,
                "inst": 1,
                "due": date(2026, 9, 29),
                "paid": date(2026, 10, 2),
                "act": date(2026, 9, 30),
                "sum": 10 * M,
            }
        ],
    )
    assert build_broker_slide(2026, 3)["empty"]
    slide = build_broker_slide(2026, 4)
    assert [m["name"] for m in slide["months"]] == ["Октябрь", "Ноябрь", "Декабрь"]
    assert _row(slide, "Все договоры", 0)["total"] == 10 * M
    assert _row(slide, "Все договоры")["total"] == 10 * M
    assert _row(slide, "Новые договоры")["total"] == 10 * M


@pytest.mark.django_db
def test_broker_unpaid_rows_are_excluded(make):
    make(
        [10 * M],
        payments=[{"year": 1, "inst": 1, "due": date(2026, 8, 1), "sum": 10 * M}],
    )
    _pay(make, 5 * M, date(2026, 8, 1))
    assert len(broker_payment_pairs(2026, 3)) == 1
    assert _row(build_broker_slide(2026, 3), "Все договоры")["total"] == 5 * M


@pytest.mark.django_db
def test_broker_termination_date_cuts_payments_on_and_after_it(make):
    policy = make(
        [10 * M],
        termination=date(2026, 8, 15),
        payments=[
            {"year": 1, "inst": 1, "paid": date(2026, 8, 10), "sum": 10 * M},
            {"year": 1, "inst": 2, "paid": date(2026, 8, 15), "sum": 10 * M},
            {"year": 1, "inst": 3, "paid": date(2026, 8, 20), "sum": 10 * M},
        ],
    )
    closed = make(
        [5 * M],
        termination=date(2026, 8, 15),
        payments=[{"year": 1, "inst": 1, "paid": date(2026, 8, 15), "sum": 5 * M}],
    )
    pairs = broker_payment_pairs(2026, 3)
    assert [p["policy_id"] for p in pairs] == [policy.pk]
    assert closed.pk not in {p["policy_id"] for p in pairs}
    # Оплата до расторжения остаётся в историческом квартале, месяц — первый.
    assert pairs[0]["month"] == 2
    assert (
        pairs[0]["payment_id"] == policy.payment_schedule.get(installment_number=1).pk
    )
    assert _row(build_broker_slide(2026, 3), "Все договоры")["total"] == 10 * M


@pytest.mark.django_db
def test_broker_dfa_closure_date_cuts_payments_on_and_after_it(make):
    before = make(
        [10 * M],
        dfa_active=False,
        dfa_deactivation=date(2026, 8, 15),
        payments=[
            {"year": 1, "inst": 1, "paid": date(2026, 7, 10), "sum": 10 * M},
            {"year": 1, "inst": 2, "paid": date(2026, 8, 20), "sum": 10 * M},
        ],
    )
    make(
        [5 * M],
        dfa_active=False,
        dfa_deactivation=date(2026, 8, 15),
        payments=[{"year": 1, "inst": 1, "paid": date(2026, 8, 15), "sum": 5 * M}],
    )
    pairs = broker_payment_pairs(2026, 3)
    assert [p["policy_id"] for p in pairs] == [before.pk]
    assert pairs[0]["month"] == 1
    slide = build_broker_slide(2026, 3)
    assert _row(slide, "Все договоры")["total"] == 10 * M
    # На конец квартала ДФА закрыт: слайды 1–2 пусты, слайд 3 считает оплату.
    assert build_insurer_slide(AS_OF)["empty"]


@pytest.mark.django_db
def test_broker_cleared_flags_without_date_are_excluded(make):
    _pay(make, 10 * M, date(2026, 8, 1), policy_active=False)
    _pay(make, 10 * M, date(2026, 8, 1), dfa_active=False)
    _pay(make, 3 * M, date(2026, 8, 1))
    assert _row(build_broker_slide(2026, 3), "Все договоры")["total"] == 3 * M


@pytest.mark.django_db
def test_broker_does_not_require_policy_in_force_at_quarter_end(make):
    # Плановое окно закрылось 01.07.2026, оплата 05.07 — в квартале учитывается.
    make(
        [10 * M],
        start=date(2025, 7, 1),
        years=1,
        payments=[
            {"year": 1, "inst": 1, "due": date(2026, 7, 1), "paid": date(2026, 7, 5)}
        ],
    )
    assert _row(build_broker_slide(2026, 3), "Все договоры")["total"] == 10 * M
    assert build_insurer_slide(AS_OF)["empty"]


@pytest.mark.django_db
def test_broker_osago_and_liability_are_excluded(refs, make):
    weird = InsuranceType.objects.create(name="  ОТВЕТСТВЕННОСТЬ  ")
    _pay(make, 10 * M, date(2026, 8, 1))
    _pay(make, None, date(2026, 8, 1), kind="osago", years=1)
    _pay(make, 50 * M, date(2026, 8, 1), kind="liability", years=1)
    _pay(make, 7 * M, date(2026, 8, 1), kind=weird, years=1)
    assert len(broker_payment_pairs(2026, 3)) == 1
    assert _row(build_broker_slide(2026, 3), "Все договоры")["total"] == 10 * M


@pytest.mark.django_db
def test_broker_new_vs_prolongation_classification(make):
    _pay(make, 10 * M, date(2026, 7, 5))  # год 1 без флага → новые
    _pay(make, 20 * M, date(2026, 8, 5), broker=False, renewal=True)  # год 1 + флаг
    _pay(make, 30 * M, date(2026, 9, 5), year=2, inst=3, broker=False)  # год 2
    slide = build_broker_slide(2026, 3)
    assert _row(slide, "Все договоры")["total"] == 60 * M
    assert _row(slide, "Все договоры")["without"] == 50 * M
    assert _row(slide, "Новые договоры")["total"] == 10 * M
    assert _row(slide, "Новые договоры")["without"] == 0
    assert _row(slide, "Новые договоры")["share_display"] == "0,00%"
    assert _row(slide, "Пролонгации")["total"] == 50 * M
    assert _row(slide, "Пролонгации")["without"] == 50 * M
    assert _row(slide, "Пролонгации")["share_display"] == "100,00%"
    assert slide["share_display"] == "83,33%"


@pytest.mark.django_db
def test_broker_control_example_forty_mln_in_each_quarter(make):
    # Контрольный пример ТЗ: год 2, СС 40 млн, квартальные взносы без брокера.
    make(
        [40 * M, 40 * M],
        start=date(2025, 7, 1),
        years=2,
        broker=False,
        payments=[
            {
                "year": 2,
                "inst": 1,
                "due": date(2026, 7, 1),
                "paid": date(2026, 7, 10),
                "sum": 40 * M,
            },
            {"year": 2, "inst": 2, "due": date(2026, 10, 1), "paid": date(2026, 10, 5)},
        ],
    )
    for quarter, month_index in ((3, 0), (4, 0)):
        slide = build_broker_slide(2026, quarter)
        assert _row(slide, "Пролонгации")["without"] == 40 * M
        assert _row(slide, "Пролонгации")["total"] == 40 * M
        assert _row(slide, "Пролонгации")["share_display"] == "100,00%"
        assert _row(slide, "Пролонгации", month_index)["without"] == 40 * M
        assert _row(slide, "Все договоры")["without"] == 40 * M
        assert _row(slide, "Новые договоры")["total"] == 0
        assert slide["without_display"] == "40,0"
        assert slide["share_display"] == "100,00%"


@pytest.mark.django_db
def test_broker_control_example_both_payments_in_quarter_counted_once(make):
    make(
        [40 * M, 40 * M],
        start=date(2025, 7, 1),
        years=2,
        broker=False,
        payments=[
            {
                "year": 2,
                "inst": 1,
                "due": date(2026, 7, 1),
                "paid": date(2026, 7, 10),
                "sum": 40 * M,
            },
            {
                "year": 2,
                "inst": 2,
                "due": date(2026, 10, 1),
                "paid": date(2026, 9, 20),
                "sum": 40 * M,
            },
        ],
    )
    slide = build_broker_slide(2026, 3)
    assert _row(slide, "Пролонгации")["without"] == 40 * M
    assert [_row(slide, "Пролонгации", m)["without"] for m in range(3)] == [
        40 * M,
        Decimal(0),
        Decimal(0),
    ]
    assert build_broker_slide(2026, 4)["empty"]


@pytest.mark.django_db
def test_broker_multi_year_policy_uses_sum_of_paid_year(make):
    # Год 3 начался до квартала; взнос №1 оплачен в II квартале, №2 — в III.
    make(
        [100 * M, 90 * M, 80 * M],
        start=date(2024, 5, 1),
        years=3,
        payments=[
            {
                "year": 3,
                "inst": 1,
                "due": date(2026, 5, 1),
                "paid": date(2026, 5, 2),
                "sum": 80 * M,
            },
            {
                "year": 3,
                "inst": 2,
                "due": date(2026, 8, 1),
                "paid": date(2026, 8, 5),
                "sum": 70 * M,
                "amount": Decimal("5000000"),
            },
        ],
    )
    slide = build_broker_slide(2026, 3)
    assert _row(slide, "Все договоры")["total"] == 80 * M  # не 100, не 70, не премия
    assert _row(slide, "Все договоры", 1)["total"] == 80 * M  # август
    assert _row(slide, "Пролонгации")["total"] == 80 * M
    assert _row(slide, "Новые договоры")["total"] == 0


@pytest.mark.django_db
def test_broker_same_year_two_months_counted_once_in_first_month(make):
    policy = make(
        [10 * M],
        payments=[
            {"year": 1, "inst": 2, "due": date(2026, 9, 1), "paid": date(2026, 9, 15)},
            {"year": 1, "inst": 1, "due": date(2026, 7, 1), "paid": date(2026, 7, 20)},
        ],
    )
    pairs = broker_payment_pairs(2026, 3)
    assert len(pairs) == 1
    assert pairs[0]["month"] == 1
    assert (
        pairs[0]["payment_id"] == policy.payment_schedule.get(installment_number=1).pk
    )
    slide = build_broker_slide(2026, 3)
    assert [_row(slide, "Все договоры", m)["total"] for m in range(3)] == [
        10 * M,
        Decimal(0),
        Decimal(0),
    ]
    assert _row(slide, "Все договоры")["total"] == 10 * M


@pytest.mark.django_db
def test_broker_same_paid_date_tie_breaks_by_payment_pk(make):
    policy = make(
        [10 * M],
        payments=[
            {"year": 1, "inst": 1, "paid": date(2026, 8, 1), "sum": 10 * M},
            {"year": 1, "inst": 2, "paid": date(2026, 8, 1), "sum": 10 * M},
        ],
    )
    pairs = broker_payment_pairs(2026, 3)
    assert len(pairs) == 1
    assert pairs[0]["payment_id"] == policy.payment_schedule.order_by("pk").first().pk


@pytest.mark.django_db
def test_broker_pair_reappears_in_next_quarter(make):
    make(
        [10 * M],
        payments=[
            {"year": 1, "inst": 1, "paid": date(2026, 7, 20), "sum": 10 * M},
            {"year": 1, "inst": 2, "paid": date(2026, 10, 20), "sum": 10 * M},
        ],
    )
    q3 = build_broker_slide(2026, 3)
    q4 = build_broker_slide(2026, 4)
    assert (
        _row(q3, "Все договоры")["total"] == _row(q4, "Все договоры")["total"] == 10 * M
    )
    assert _row(q3, "Все договоры", 0)["total"] == 10 * M
    assert _row(q4, "Все договоры", 0)["total"] == 10 * M
    assert _row(q3, "Новые договоры")["total"] == 10 * M


@pytest.mark.django_db
def test_broker_two_years_of_same_policy_are_not_merged(make):
    policy = make(
        [10 * M, 8 * M],
        start=date(2025, 7, 1),
        years=2,
        payments=[
            {
                "year": 1,
                "inst": 1,
                "due": date(2025, 7, 1),
                "paid": date(2025, 7, 10),
                "sum": 10 * M,
            },
            {"year": 1, "inst": 2, "due": date(2026, 7, 1), "paid": date(2026, 7, 10)},
            {"year": 2, "inst": 1, "due": date(2026, 8, 1), "paid": date(2026, 8, 10)},
        ],
    )
    pairs = broker_payment_pairs(2026, 3)
    assert {(p["policy_id"], p["year_number"]) for p in pairs} == {
        (policy.pk, 1),
        (policy.pk, 2),
    }
    slide = build_broker_slide(2026, 3)
    assert _row(slide, "Все договоры")["total"] == 18 * M
    assert _row(slide, "Новые договоры")["total"] == 10 * M
    assert _row(slide, "Пролонгации")["total"] == 8 * M
    assert [_row(slide, "Все договоры", m)["total"] for m in range(3)] == [
        10 * M,
        8 * M,
        Decimal(0),
    ]


@pytest.fixture
def broker_data(refs, make):
    """Оба канала, два филиала, три месяца, «<0,1» и неизвестная СС."""
    moscow = Branch.objects.create(branch_name="Москва")
    _pay(make, 10 * M, date(2026, 7, 5))
    _pay(make, 4 * M, date(2026, 7, 20), broker=False)
    _pay(make, 6 * M, date(2026, 8, 10), year=2, broker=False, branch=moscow)
    _pay(make, 3 * M, date(2026, 9, 15), renewal=True)
    _pay(make, Decimal("40000"), date(2026, 9, 20), broker=False)
    _pay(make, None, date(2026, 8, 25), broker=False)
    return moscow


@pytest.mark.django_db
def test_broker_months_and_categories_add_up(broker_data):
    slide = build_broker_slide(2026, 3)
    for label in ("Все договоры", "Новые договоры", "Пролонгации"):
        quarter = _row(slide, label)
        for key in ("total", "without"):
            assert (
                sum((_row(slide, label, m)[key] for m in range(3)), Decimal(0))
                == quarter[key]
            )
    all_row = _row(slide, "Все договоры")
    new_row = _row(slide, "Новые договоры")
    old_row = _row(slide, "Пролонгации")
    for key in ("total", "without"):
        assert all_row[key] == new_row[key] + old_row[key]
    assert all_row["total"] == Decimal("23040000")
    assert all_row["without"] == Decimal("10040000")
    assert all_row["total_display"] == "23,0"
    assert all_row["without_display"] == "10,0"
    assert all_row["share_display"] == slide["share_display"] == "43,58%"
    assert new_row["total"] == Decimal("14040000")  # 10 + 4 + «<0,1» — год 1
    assert old_row["total"] == 9 * M  # 6 (год 2) + 3 (перезаключение)
    assert slide["unknown_count"] == 1
    assert slide["unknown_without_count"] == 1


@pytest.mark.django_db
def test_broker_quarter_share_is_not_mean_of_month_shares(make):
    _pay(make, 2 * M, date(2026, 7, 5))
    _pay(make, M, date(2026, 7, 6), broker=False)
    _pay(make, M, date(2026, 8, 5))
    slide = build_broker_slide(2026, 3)
    assert _row(slide, "Все договоры", 0)["share_display"] == "33,33%"
    assert _row(slide, "Все договоры", 1)["share_display"] == "0,00%"
    assert _row(slide, "Все договоры", 2)["share_display"] == "—"
    assert _row(slide, "Все договоры")["share_display"] == "25,00%"  # 1/4, не 16,67
    assert slide["share_display"] == "25,00%"


@pytest.mark.django_db
def test_broker_share_uses_unrounded_sums(make):
    _pay(make, Decimal("834560"), date(2026, 7, 5))
    _pay(make, Decimal("400000"), date(2026, 7, 6), broker=False)
    row = _row(build_broker_slide(2026, 3), "Все договоры")
    assert row["total_display"] == "1,2"
    assert row["without_display"] == "0,4"
    assert row["share_display"] == "32,40%"  # не 0,4 / 1,2 = 33,33%


@pytest.mark.django_db
def test_broker_zero_denominator_and_small_positive(make):
    _pay(make, 10 * M, date(2026, 7, 5))
    _pay(make, Decimal("40000"), date(2026, 8, 5), broker=False)
    slide = build_broker_slide(2026, 3)
    july = _row(slide, "Все договоры", 0)
    assert july["without_display"] == "—"
    assert july["share_display"] == "0,00%"
    august = _row(slide, "Все договоры", 1)
    assert august["total_display"] == august["without_display"] == "<0,1"
    assert august["share_display"] == "100,00%"
    september = _row(slide, "Все договоры", 2)
    assert september["total_display"] == "—"
    assert september["share_display"] == "—"
    assert len(slide["months"]) == 3  # пустой месяц не скрыт


@pytest.mark.django_db
def test_broker_unknown_sums_are_excluded_and_noted(make):
    _pay(make, 10 * M, date(2026, 7, 5))
    _pay(make, None, date(2026, 7, 6), broker=False)
    _pay(make, None, date(2026, 8, 6))
    slide = build_broker_slide(2026, 3)
    assert slide["unknown_count"] == 2
    assert slide["unknown_without_count"] == 1
    assert _row(slide, "Все договоры")["total"] == 10 * M
    assert "Пар полис–год с неопределённой СС: 2 (без брокера — 1)" in slide["note"]
    assert not slide["empty"]
    assert len(broker_payment_pairs(2026, 3)) == 3  # пары сохранены для слайда 4


@pytest.mark.django_db
def test_broker_pairs_keep_branch_and_client_ids(refs, make):
    moscow = Branch.objects.create(branch_name="Москва")
    other = Client.objects.create(client_name="ООО Другой", client_inn="7700000302")
    policy = _pay(
        make,
        10 * M,
        date(2026, 8, 5),
        year=2,
        broker=False,
        branch=moscow,
        client=other,
    )
    pair = broker_payment_pairs(2026, 3)[0]
    assert pair["policy_id"] == policy.pk
    assert pair["branch_id"] == moscow.pk
    assert pair["client_id"] == other.pk
    assert pair["year_number"] == 2
    assert pair["broker"] is False
    assert pair["prolongation"] is True
    assert pair["month"] == 2
    assert pair["insured_sum"] == 10 * M


@pytest.mark.django_db
def test_broker_selection_query_count_does_not_grow(make, django_assert_num_queries):
    _pay(make, 10 * M, date(2026, 8, 5))
    with django_assert_num_queries(2):
        broker_payment_pairs(2026, 3)
    for i in range(20):
        _pay(make, (i + 1) * M, date(2026, 8, 6), broker=i % 2 == 0)
    with django_assert_num_queries(2):
        pairs = broker_payment_pairs(2026, 3)
    assert len(pairs) == 21


@pytest.mark.django_db
def test_broker_slide_does_not_change_first_two_slides(make):
    _pay(make, 10 * M, date(2026, 8, 5))
    _pay(make, 4 * M, date(2026, 8, 6), broker=False, insurer="b")
    slide1, slide2, slide3, slide4 = build_quarterly_presentation(2026, 3)["slides"]
    assert slide1 == build_insurer_slide(AS_OF)
    assert slide2 == build_branch_matrix_slide(AS_OF)
    assert slide3["kind"] == "broker"
    assert slide3["total_display"] == "14,0"
    assert slide4["kind"] == "broker_distribution"
    assert slide4["sum_display"] == "4,0 млн ₽"  # только полис без брокера
    assert slide4["tables"][0]["total"]["sum"] == 4 * M


@pytest.mark.integration
@pytest.mark.django_db
def test_broker_slide_ignores_branch_and_scope_filters(client, refs, make):
    moscow = Branch.objects.create(branch_name="Москва")
    _pay(make, 10 * M, date(2026, 8, 5))
    _pay(make, 4 * M, date(2026, 8, 6), broker=False, branch=moscow)
    client.force_login(User.objects.create_user("qp", "qp@u.ru", "x"))
    url = reverse("reports:quarterly_presentation")
    base = client.get(url, {"year": 2026, "quarter": 3}).content.decode()
    filtered = client.get(
        url,
        {"year": 2026, "quarter": 3, "branch": moscow.pk, "scope": "direct"},
    ).content.decode()
    # CSRF-токен меняется от запроса к запросу, остальная страница — нет.
    assert _strip_csrf(base) == _strip_csrf(filtered)
    assert "14,0" in base


@pytest.mark.integration
@pytest.mark.django_db
def test_broker_html_and_pdf_use_same_numbers(client, broker_data):
    url = reverse("reports:quarterly_presentation")
    third = _pdf_pages(client)[2]  # помощник сам авторизует клиента
    html = client.get(url, {"year": 2026, "quarter": 3}).content.decode()
    slide = build_broker_slide(2026, 3)
    caption = "III квартал 2026 года · По фактической дате оплаты взносов"
    assert slide["title"] in html and slide["title"] in third
    assert caption in html and caption in _flat(third)
    # Логотип бренда — картинка вместо текстовой марки «флоу//полисы».
    assert "флоу//полисы" not in third
    for block in slide["months"] + [slide["quarter_block"]]:
        assert block["name"] in html and block["name"] in third
        for row in block["rows"]:
            assert row["label"] in html and row["label"] in third
            for key in ("total_display", "without_display", "share_display"):
                assert escape(row[key]) in html
                assert row[key] in third
    for key in ("share_display", "without_display", "total_display"):
        assert slide[key] in html and slide[key] in third
    assert escape(slide["note"]) in html  # методика осталась на сайте
    assert _flat(slide["note"]) not in _flat(third)  # и убрана из PDF
    assert "Распределение имущества" not in third


@pytest.mark.integration
@pytest.mark.django_db
def test_broker_empty_quarter_renders_in_html_and_pdf(client, refs):
    url = reverse("reports:quarterly_presentation")
    pages = _pdf_pages(client)  # помощник сам авторизует клиента
    html = client.get(url, {"year": 2026, "quarter": 3}).content.decode()
    assert "Страхование с участием и без участия брокера" in html
    assert "Нет подходящих фактических оплат за квартал" in html
    assert "Нет подходящих фактических оплат без участия брокера за квартал" in html
    assert "Страхование с участием и без участия брокера" in pages[2]
    assert "Нет подходящих фактических оплат за квартал" in pages[2]
    assert "Нет подходящих фактических оплат без участия брокера за квартал" in pages[3]
    assert "распределение по страховщикам пусто" in pages[0]


@pytest.mark.integration
@pytest.mark.django_db
def test_broker_pdf_third_page_fits_with_large_sums(client, refs, make):
    for i in range(30):
        _pay(
            make,
            Decimal("1234567890") - i * M,
            date(2026, 7 + i % 3, 5),
            year=1 + i % 2,
            broker=i % 2 == 0,
        )
    third = _pdf_pages(client)[2]
    slide = build_broker_slide(2026, 3)
    assert "Итого за квартал" in third
    for row in slide["quarter_block"]["rows"]:
        assert row["total_display"] in third
        assert row["without_display"] in third
        assert row["share_display"] in third
    assert _flat(slide["note"]) not in _flat(third)  # методика — только в HTML
    for data in (slide, build_broker_slide(2026, 1)):
        flowables = qp_pdf._broker_slide(data)
        height = sum(f.wrap(qp_pdf.SLIDE_WIDTH, 10000)[1] for f in flowables)
        assert height <= qp_pdf.SLIDE_HEIGHT


# --- Диаграмма и сравнение слайда 3 -------------------------------------------


@pytest.mark.django_db
def test_chart_values_match_table_blocks(make):
    _pay(make, 10 * M, date(2026, 7, 5), broker=False)  # июль, новый
    _pay(
        make, 6 * M, date(2026, 8, 5), broker=False, renewal=True
    )  # август, пролонгация
    _pay(make, 4 * M, date(2026, 9, 5), broker=False)  # сентябрь, новый
    slide = build_broker_slide(2026, 3)
    chart = slide["chart"]
    assert [e["name"] for e in chart["months"]] == ["Июль", "Август", "Сентябрь"]
    # Шесть значений — те же доли, что у строк «Новые» и «Пролонгации» таблицы.
    bars = [bar for e in chart["months"] for bar in (e["new"], e["prolong"])]
    assert [bar["value"] for bar in bars] == [
        Decimal(100),
        None,
        None,
        Decimal(100),
        Decimal(100),
        None,
    ]
    assert [bar["display"] for bar in bars] == [
        "100,00%",
        "—",
        "—",
        "100,00%",
        "100,00%",
        "—",
    ]
    # Высоты от шкалы с запасом 15% над максимумом; неопределённым столбца нет.
    assert chart["scale_max"] == Decimal(100) * Decimal("1.15")
    assert [bar["height_css"] for bar in bars] == ["87.0", "", "", "87.0", "87.0", ""]


@pytest.mark.django_db
def test_chart_zero_share_differs_from_undefined(make):
    # Июль: единственная пара — новый договор с брокером: у «Новых» ноль
    # при ненулевом знаменателе, у «Пролонгаций» доля не определена.
    _pay(make, 5 * M, date(2026, 7, 5), broker=True)
    slide = build_broker_slide(2026, 3)
    new, prolong = (
        slide["chart"]["months"][0]["new"],
        slide["chart"]["months"][0]["prolong"],
    )
    assert new["value"] == Decimal(0)
    assert new["display"] == "0,00%"
    assert new["height_css"] == "0.0"
    assert prolong["value"] is None
    assert prolong["display"] == "—"
    assert prolong["height_pct"] is None
    # И в таблице те же подписи.
    assert _row(slide, "Новые договоры", 0)["share_display"] == "0,00%"
    assert _row(slide, "Пролонгации", 0)["share_display"] == "—"


@pytest.mark.django_db
def test_share_bold_only_for_defined_shares(make):
    _pay(make, 10 * M, date(2026, 7, 5))  # июль: доля 0,00%
    _pay(make, 8 * M, date(2026, 8, 5), broker=False)  # август: 100,00%
    _pay(make, None, date(2026, 9, 5), broker=False)  # сентябрь: прочерк
    slide = build_broker_slide(2026, 3)
    all_row = next(r for r in slide["table_rows"] if r["label"] == "Все договоры")
    july, august, september, quarter = all_row["cells"]
    assert july["share_display"] == "0,00%" and july["share_bold"]
    assert august["share_display"] == "100,00%" and august["share_bold"]
    assert september["share_display"] == "—" and not september["share_bold"]
    assert quarter["share_display"] == "44,44%" and quarter["share_bold"]


@pytest.mark.unit
def test_broker_widest_cell_measures_bold_share():
    # «100,00%» в жирном начертании шире обычного: подбор шрифта должен
    # мерить долю именно жирным, иначе колонка обрежет значение.
    from reportlab.pdfbase import pdfmetrics

    from apps.reports.services.property_pdf import _fonts

    _fonts()
    row = {
        "total_display": "1,0",
        "without_display": "1,0",
        "share_display": "100,00%",
        "share_bold": True,
    }
    slide = {
        "months": [{"rows": [dict(row)]}],
        "quarter_block": {"rows": [dict(row)]},
    }
    widest = qp_pdf._broker_widest_cell(slide, 11)
    assert widest == pdfmetrics.stringWidth("100,00%", "PropertyInterBold", 11)
    assert widest > pdfmetrics.stringWidth("100,00%", "PropertyInter", 11)


@pytest.mark.integration
@pytest.mark.django_db
def test_share_column_bold_in_html_and_fits_pdf(client, make):
    _pay(make, 10 * M, date(2026, 7, 5))
    _pay(make, 8 * M, date(2026, 8, 5), broker=False)
    _pay(make, None, date(2026, 9, 5), broker=False)
    third = _pdf_pages(client)[2]
    html = client.get(
        reverse("reports:quarterly_presentation"), {"year": 2026, "quarter": 3}
    ).content.decode()
    # Определённые доли жирны во всех четырёх блоках: в июле, августе и
    # квартале по две (строки «Все» и «Новые»), в сентябре одни прочерки.
    assert html.count(' qp-share-bold"') == 6
    assert "0,00%" in third and "100,00%" in third and "44,44%" in third


@pytest.mark.django_db
def test_comparison_across_year_boundary(make):
    # I квартал 2027 сравнивается с завершённым IV кварталом 2026.
    _pay(make, 8 * M, date(2026, 12, 5), broker=False)
    _pay(make, 4 * M, date(2026, 12, 6), broker=True)
    _pay(make, 3 * M, date(2027, 2, 5), broker=False)
    with mock.patch.object(
        qp_payments.timezone, "localdate", return_value=date(2027, 4, 10)
    ):
        slide = build_broker_slide(2027, 1)
    comparison = slide["comparison"]
    assert comparison["label"] == "к IV кварталу 2026 года"
    # Доля IV квартала 66,67%, доля I квартала 100% → сдвиг +33,33 п.п.
    assert comparison["display"] == "+33,33 п.п."


@pytest.mark.django_db
def test_comparison_hidden_for_incomplete_quarter(make):
    _pay(make, 5 * M, date(2027, 1, 5), broker=False)
    # Квартал не закончился — сравнения нет, даже если оплаты уже есть.
    with mock.patch.object(
        qp_payments.timezone, "localdate", return_value=date(2027, 2, 10)
    ):
        slide = build_broker_slide(2027, 1)
    assert slide["comparison"] is None


@pytest.mark.django_db
def test_comparison_hidden_when_previous_quarter_empty(make):
    _pay(make, 5 * M, date(2027, 1, 5), broker=False)
    # Квартал закончился, но у предыдущего нет данных — сравнения тоже нет.
    with mock.patch.object(
        qp_payments.timezone, "localdate", return_value=date(2027, 4, 10)
    ):
        slide = build_broker_slide(2027, 1)
    assert slide["comparison"] is None


@pytest.mark.django_db
def test_comparison_appears_only_day_after_quarter_end(make):
    # Обе доли определены; 30.09 — последний день квартала, сравнения ещё нет.
    _pay(make, 6 * M, date(2026, 6, 5), broker=False)
    _pay(make, 6 * M, date(2026, 6, 6), broker=True)
    _pay(make, 8 * M, date(2026, 9, 5), broker=False)
    with mock.patch.object(
        qp_payments.timezone, "localdate", return_value=date(2026, 9, 30)
    ):
        assert build_broker_slide(2026, 3)["comparison"] is None
    with mock.patch.object(
        qp_payments.timezone, "localdate", return_value=date(2026, 10, 1)
    ):
        comparison = build_broker_slide(2026, 3)["comparison"]
    assert comparison["label"] == "ко II кварталу 2026 года"
    # Доля II квартала 50%, доля III квартала 100% → сдвиг +50,00 п.п.
    assert comparison["display"] == "+50,00 п.п."


@pytest.mark.integration
@pytest.mark.django_db
def test_comparison_lives_in_details_not_in_card_or_pdf(client, make):
    # Сравнение убрано из карточки слайда 3 и из PDF: осталось только в
    # раскрываемом блоке «Как рассчитано» под слайдом.
    _pay(make, 6 * M, date(2026, 6, 5), broker=False)
    _pay(make, 6 * M, date(2026, 6, 6), broker=True)
    _pay(make, 8 * M, date(2026, 9, 5), broker=False)
    with mock.patch.object(
        qp_payments.timezone, "localdate", return_value=date(2026, 10, 1)
    ):
        third = _pdf_pages(client)[2]
        html = client.get(
            reverse("reports:quarterly_presentation"), {"year": 2026, "quarter": 3}
        ).content.decode()
    assert "+50,00 п.п." not in _flat(third)
    assert "ко II кварталу 2026 года" not in _flat(third)
    assert "Изменение доли без брокера: +50,00 п.п. ко II кварталу 2026 года." in html
    # В карточке сравнения нет: текст встречается один раз, внутри details.
    assert html.count("+50,00 п.п.") == 1


# --- Слайд 4: распределение страхования без участия брокера --------------------


@pytest.mark.django_db
def test_distribution_uses_single_pairs_selection_for_slides_3_and_4(refs, make):
    _pay(make, 6 * M, date(2026, 7, 5), broker=False)
    _pay(make, 2 * M, date(2026, 8, 5))
    with mock.patch(
        "apps.reports.services.quarterly_payments.broker_payment_pairs",
        wraps=qp_payments.broker_payment_pairs,
    ) as spy:
        presentation = build_quarterly_presentation(2026, 3)
    # Слайды 3 и 4 питает один расчёт пар текущего квартала; отдельный вызов
    # нужен только сравнению с предыдущим кварталом на слайде 3.
    assert [call.args for call in spy.call_args_list].count((2026, 3)) == 1
    slide3, slide4 = presentation["slides"][2:]
    assert slide3["without_display"] == "6,0"
    assert slide4["sum_display"] == "6,0 млн ₽"


@pytest.mark.django_db
def test_distribution_totals_match_broker_slide_without(broker_data):
    slide3 = build_broker_slide(2026, 3)
    without = _row(slide3, "Все договоры")["without"]
    slide4 = build_distribution_slide(2026, 3, pairs=broker_payment_pairs(2026, 3))
    branch_total = slide4["tables"][0]["total"]
    client_total = slide4["tables"][1]["total"]
    # До округления итог каждой таблицы = «Без брокера» слайда 3 (не суммы двух таблиц).
    assert branch_total["sum"] == client_total["sum"] == without == Decimal("10040000")
    assert branch_total["sum_display"] == slide3["without_display"] == "10,0"
    assert branch_total["share_display"] == client_total["share_display"] == "100,00%"
    assert slide4["sum_display"] == "10,0 млн ₽"
    pskov = next(r for r in slide4["tables"][0]["rows"] if r["name"] == "Псков")
    moscow = next(r for r in slide4["tables"][0]["rows"] if r["name"] == "Москва")
    assert (pskov["sum"], pskov["share_display"]) == (Decimal("4040000"), "40,24%")
    assert (moscow["sum"], moscow["share_display"]) == (6 * M, "59,76%")
    client_row = slide4["tables"][1]["rows"][0]
    assert client_row["name"] == "ООО Лизинг"
    assert client_row["share_display"] == "100,00%"  # доля от «Без брокера»


@pytest.mark.django_db
def test_distribution_excludes_broker_and_unknown_sums(refs, make):
    _pay(make, 50 * M, date(2026, 7, 5), broker=True)  # канал с брокером не входит
    _pay(make, 7 * M, date(2026, 7, 6), broker=False)
    _pay(make, None, date(2026, 8, 6), broker=False)  # без СС — только примечание
    slide = build_distribution_slide(2026, 3)
    assert slide["unknown_count"] == 1
    assert not slide["empty"] and not slide["no_sums"]
    assert slide["tables"][0]["total"]["sum"] == 7 * M
    row = slide["tables"][0]["rows"][0]
    assert row["sum"] == 7 * M
    # Доля считается от 7 млн без брокера, а не от 57 млн всех сделок.
    assert row["share_display"] == "100,00%"
    assert "Пар полис–год с неопределённой СС: 1" in slide["note"]


@pytest.mark.django_db
def test_distribution_same_names_different_ids_are_separate_rows(refs, make):
    b1 = Branch.objects.create(branch_name="Северо-Запад")
    b2 = Branch.objects.create(branch_name="Северо-Запад")
    c1 = Client.objects.create(client_name="ООО Ромашка", client_inn="7801000001")
    c2 = Client.objects.create(client_name="ООО Ромашка", client_inn="7801000002")
    _pay(make, 5 * M, date(2026, 7, 5), broker=False, branch=b1, client=c1)
    _pay(make, 3 * M, date(2026, 7, 6), broker=False, branch=b2, client=c2)
    slide = build_distribution_slide(2026, 3)
    assert [(r["id"], r["sum"]) for r in slide["tables"][0]["rows"]] == [
        (b1.pk, 5 * M),
        (b2.pk, 3 * M),
    ]
    assert [(r["id"], r["sum"]) for r in slide["tables"][1]["rows"]] == [
        (c1.pk, 5 * M),
        (c2.pk, 3 * M),
    ]


@pytest.mark.django_db
def test_distribution_sorted_by_sum_then_id(refs, make):
    branches = [Branch.objects.create(branch_name=f"Ф {i}") for i in range(4)]
    _pay(make, 2 * M, date(2026, 7, 5), broker=False, branch=branches[3])
    _pay(make, 9 * M, date(2026, 7, 5), broker=False, branch=branches[1])
    _pay(make, 2 * M, date(2026, 7, 5), broker=False, branch=branches[0])
    slide = build_distribution_slide(2026, 3)
    assert [(r["id"], r["sum"]) for r in slide["tables"][0]["rows"]] == [
        (branches[1].pk, 9 * M),
        (branches[0].pk, 2 * M),
        (branches[3].pk, 2 * M),
    ]


@pytest.mark.django_db
def test_distribution_eight_groups_show_all_without_other(refs, make):
    branches = [Branch.objects.create(branch_name=f"Ф {i:02d}") for i in range(8)]
    for i, branch in enumerate(branches):
        _pay(make, (i + 1) * M, date(2026, 7, 5), broker=False, branch=branch)
    slide = build_distribution_slide(2026, 3)
    rows = slide["tables"][0]["rows"]
    assert len(rows) == 8
    assert [r["sum"] for r in rows] == [(8 - i) * M for i in range(8)]
    assert all(not r.get("is_other") for r in rows)
    assert "Иные филиалы" not in slide["note"]
    assert slide["tables"][0]["total"]["sum"] == 36 * M


@pytest.mark.django_db
def test_distribution_nine_groups_top_seven_plus_other(refs, make):
    branches = [Branch.objects.create(branch_name=f"Ф {i:02d}") for i in range(9)]
    for i, branch in enumerate(branches):
        _pay(make, (i + 1) * M, date(2026, 7, 5), broker=False, branch=branch)
    slide = build_distribution_slide(2026, 3)
    rows = slide["tables"][0]["rows"]
    assert len(rows) == 8
    assert [r["sum"] for r in rows[:7]] == [(i + 1) * M for i in range(8, 1, -1)]
    other = rows[-1]
    assert other["name"] == "Иные филиалы" and other["id"] is None
    assert other["sum"] == 3 * M  # суммы скрытых групп не потеряны
    assert other["share_display"] == "6,67%"
    assert slide["tables"][0]["other_count"] == 2
    assert slide["tables"][0]["total"]["sum"] == 45 * M
    assert "«Иные филиалы» — ещё 2 филиалов" in slide["note"]


@pytest.mark.django_db
def test_distribution_empty_without_broker_slice(refs, make):
    _pay(make, 10 * M, date(2026, 7, 5), broker=True)
    slide = build_distribution_slide(2026, 3)
    assert slide["empty"] and not slide["no_sums"]
    assert slide["unknown_count"] == 0
    assert slide["sum_display"] == "—"
    assert slide["tables"] == []


@pytest.mark.django_db
def test_distribution_all_unknown_sums_is_separate_state(refs, make):
    _pay(make, 10 * M, date(2026, 7, 5), broker=True)
    _pay(make, None, date(2026, 7, 6), broker=False)
    _pay(make, None, date(2026, 8, 6), broker=False)
    slide = build_distribution_slide(2026, 3)
    assert not slide["empty"] and slide["no_sums"]
    assert slide["unknown_count"] == 2
    assert slide["sum_display"] == "—"
    assert slide["tables"] == []


@pytest.mark.django_db
def test_distribution_small_positive_and_total_share(refs, make):
    _pay(make, Decimal("40000"), date(2026, 7, 5), broker=False)
    slide = build_distribution_slide(2026, 3)
    row = slide["tables"][0]["rows"][0]
    assert row["sum_display"] == "<0,1"
    assert row["share_display"] == "100,00%"
    assert slide["tables"][0]["total"]["share_display"] == "100,00%"


@pytest.mark.django_db
def test_distribution_names_batch_queries(refs, make, django_assert_num_queries):
    branches = [Branch.objects.create(branch_name=f"Ф {i}") for i in range(3)]
    clients = [
        Client.objects.create(client_name=f"ООО {i}", client_inn=f"780200000{i}")
        for i in range(3)
    ]
    for i in range(12):
        _pay(
            make,
            (i + 1) * M,
            date(2026, 7, 5),
            broker=False,
            branch=branches[i % 3],
            client=clients[i % 3],
        )
    pairs = broker_payment_pairs(2026, 3)
    with django_assert_num_queries(2):  # по одному запросу на справочник
        slide = build_distribution_slide(2026, 3, pairs=pairs)
    assert len(slide["tables"][0]["rows"]) == 3
    assert len(slide["tables"][1]["rows"]) == 3


@pytest.mark.django_db
def test_branches_conclusion_two_largest(refs, make):
    moscow = Branch.objects.create(branch_name="Москва")
    kazan = Branch.objects.create(branch_name="Казань")
    _pay(make, 6 * M, date(2026, 7, 5), broker=False)
    _pay(make, 4 * M, date(2026, 7, 6), broker=False, branch=moscow)
    _pay(make, 2 * M, date(2026, 7, 7), broker=False, branch=kazan)
    slide = build_distribution_slide(2026, 3)
    assert slide["sum_display"] == "12,0 млн ₽"  # единица у крупной цифры
    assert slide["branches_conclusion"]["names"] == "Псков и Москва"
    # Доля по неокруглённым суммам: 10 из 12 млн ₽.
    assert slide["branches_conclusion"]["share_display"] == "83,33%"


@pytest.mark.django_db
def test_branches_conclusion_single_branch(refs, make):
    _pay(make, 7 * M, date(2026, 7, 5), broker=False)
    slide = build_distribution_slide(2026, 3)
    assert slide["branches_conclusion"]["names"] == "Псков"
    assert slide["branches_conclusion"]["share_display"] == "100,00%"


@pytest.mark.django_db
def test_branches_conclusion_absent_without_known_sums(refs, make):
    _pay(make, None, date(2026, 7, 5), broker=False)
    slide = build_distribution_slide(2026, 3)
    assert slide["no_sums"]
    assert slide["branches_conclusion"] is None


@pytest.mark.integration
@pytest.mark.django_db
def test_html_keeps_methodology_scope_and_warns_unknown_sums(client, refs, make):
    _pay(make, 7 * M, date(2026, 7, 6), broker=False)
    _pay(make, None, date(2026, 8, 6), broker=False)
    client.force_login(User.objects.create_user("qp", "qp@u.ru", "x"))
    html = client.get(
        reverse("reports:quarterly_presentation"), {"year": 2026, "quarter": 3}
    ).content.decode()
    # Методика — в раскрываемых блоках под каждым слайдом, не внутри карточек.
    assert html.count("Как рассчитано") == 4
    assert "Страховая сумма текущего страхового года действующих полисов" in html
    assert "qp-slide-note" not in html
    # Число неучтённых пар — рядом со слайдом, а не спрятано в методике.
    assert (
        "Пар полис–год с неопределённой страховой суммой: 1 (без брокера — 1)" in html
    )
    assert "Пар полис–год без брокера с неопределённой страховой суммой: 1" in html
    # Скоуп-строки: слайды 1–2 про портфель, слайды 3–4 про оплаты.
    assert "Портфель на дату среза" in html
    assert "Страховые суммы по фактическим оплатам за квартал" in html
    # Логотип ООО «ОН-ЛАЙН БРОКЕР» из static вместо текстовой марки.
    assert "onlayn-broker.png" in html


@pytest.mark.integration
@pytest.mark.django_db
def test_unknown_sum_warning_on_portfolio_slides_only(client, make):
    make([10 * M, None], start=date(2025, 8, 1), years=2)
    make([4 * M], insurer="b")
    pages = _pdf_pages(client)  # помощник сам авторизует клиента
    html = client.get(
        reverse("reports:quarterly_presentation"), {"year": 2026, "quarter": 3}
    ).content.decode()
    # Предупреждение видно под обоими портфельными слайдами, вне details.
    assert (
        html.count('class="qp-warn">Записей без определённой страховой суммы — 1.') == 2
    )
    # В PDF предупреждений о СС нет.
    for page in pages:
        assert "Записей без определённой страховой суммы" not in page


@pytest.mark.integration
@pytest.mark.django_db
def test_unknown_sum_warning_absent_when_all_known(client, make):
    make([10 * M, 9 * M, 8 * M])
    make([4 * M], insurer="b")
    pages = _pdf_pages(client)
    html = client.get(
        reverse("reports:quarterly_presentation"), {"year": 2026, "quarter": 3}
    ).content.decode()
    assert "Записей без определённой страховой суммы" not in html
    for page in pages:
        assert "Записей без определённой страховой суммы" not in page


@pytest.mark.integration
@pytest.mark.django_db
def test_distribution_html_and_pdf_use_same_numbers(client, broker_data):
    url = reverse("reports:quarterly_presentation")
    fourth = _pdf_pages(client)[3]  # помощник сам авторизует клиента
    html = client.get(url, {"year": 2026, "quarter": 3}).content.decode()
    slide = build_distribution_slide(2026, 3)
    caption = "III квартал 2026 года · По фактической дате оплаты взносов"
    assert slide["title"] in html and slide["title"] in fourth
    assert caption in html and caption in _flat(fourth)
    assert "флоу//полисы" not in fourth  # логотип — картинка
    assert slide["sum_display"] in html and slide["sum_display"] in fourth
    assert slide["sum_label"] in html and slide["sum_label"] in _flat(fourth)
    for table in slide["tables"]:
        assert table["name"] in html and table["name"] in fourth
        for row in table["rows"] + [table["total"]]:
            assert row["name"] in html and row["name"] in fourth
            assert row["sum_display"] in html and row["sum_display"] in fourth
            assert row["share_display"] in html and row["share_display"] in fourth
    assert escape(slide["note"]) in html  # методика осталась на сайте
    assert _flat(slide["note"]) not in _flat(fourth)  # и убрана из PDF


@pytest.mark.integration
@pytest.mark.django_db
def test_distribution_empty_and_no_sums_render_in_html_and_pdf(client, refs, make):
    url = reverse("reports:quarterly_presentation")
    _pay(make, 10 * M, date(2026, 7, 5), broker=True)
    pages = _pdf_pages(client)  # помощник сам авторизует клиента
    html = client.get(url, {"year": 2026, "quarter": 3}).content.decode()
    assert "Нет подходящих фактических оплат без участия брокера за квартал" in html
    assert "Нет подходящих фактических оплат без участия брокера за квартал" in pages[3]
    # Оплаты без брокера появились, но все СС неизвестны — другое состояние.
    _pay(make, None, date(2026, 8, 6), broker=False)
    response = client.get(url, {"year": 2026, "quarter": 3, "format": "pdf"})
    fourth = read_pdf(response.content).pages[3].extract_text()
    html = client.get(url, {"year": 2026, "quarter": 3}).content.decode()
    assert "Оплаты без брокера в квартале есть" in html
    assert "не определена ни у одной из 1 пар полис–год" in _flat(fourth)
    assert "Итого" not in fourth and "0,00%" not in fourth


@pytest.mark.integration
@pytest.mark.django_db
def test_distribution_pdf_fourth_page_fits_with_long_names(client, refs, make):
    branches = [refs["branch"]] + [
        Branch.objects.create(
            branch_name=f"Филиал длинное название {i:02d} "
            + "обслуживания лизинга " * 4
        )
        for i in range(8)
    ]
    clients = [
        Client.objects.create(
            client_name=f"ООО «Длинное наименование {i:02d}» "
            + "лизингополучатель техники " * 3,
            client_inn=f"7803{i:04d}00",
        )
        for i in range(12)
    ]
    for i in range(30):
        _pay(
            make,
            Decimal("1234567890") - i * M,
            date(2026, 7 + i % 3, 5),
            year=1 + i % 2,
            broker=False,
            branch=branches[i % len(branches)],
            client=clients[i % len(clients)],
        )
    fourth = _pdf_pages(client)[3]
    slide = build_distribution_slide(2026, 3)
    assert slide["tables"][0]["other_count"] == 2  # 9 филиалов → 7 + «Иные» из 2
    assert slide["tables"][1]["other_count"] == 5  # 12 лизингополучателей
    assert "Иные филиалы" in fourth and "Иные лизингополучатели" in fourth
    for table in slide["tables"]:
        assert table["name"] in fourth
        for row in table["rows"] + [table["total"]]:
            assert row["sum_display"] in fourth
            assert row["share_display"] in fourth
    data = build_distribution_slide(2026, 3, pairs=broker_payment_pairs(2026, 3))
    flowables = qp_pdf._distribution_slide(data)
    height = sum(f.wrap(qp_pdf.SLIDE_WIDTH, 10000)[1] for f in flowables)
    assert height <= qp_pdf.SLIDE_HEIGHT
