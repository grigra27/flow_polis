"""Квартальная презентация для лизинговой компании: оба слайда, PDF и доступ.

Цифры слайдов сверяются с подробным имущественным отчётом и полной
матрицей филиал × страховщик на ту же дату (все филиалы, «Все сделки»,
без лимитов ответственности). PDF — ровно две страницы 16:9.
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
    ):
        counter["n"] += 1
        policy = Policy.objects.create(
            policy_number=f"QP-{counter['n']}",
            dfa_number=f"D-QP-{counter['n']}",
            client=refs[client],
            insurer=refs[insurer] if isinstance(insurer, str) else insurer,
            branch=refs[branch] if isinstance(branch, str) else branch,
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
    matrix_slide = build_branch_matrix_slide(AS_OF)
    assert matrix_slide["empty"]
    assert matrix_slide["rows"] == []
    assert matrix_slide["columns"] == []
    assert matrix_slide["total_sum"] == 0
    assert matrix_slide["total_sum_display"] == "—"
    presentation = build_quarterly_presentation(2026, 3)
    data = build_quarterly_pdf(presentation)
    reader = PdfReader(BytesIO(data))
    assert len(reader.pages) == 2
    assert "распределение по страховщикам пусто" in reader.pages[0].extract_text()
    assert (
        "распределение по филиалам и страховщикам пусто"
        in reader.pages[1].extract_text()
    )


@pytest.mark.django_db
def test_presentation_quarter_label_and_as_of():
    presentation = build_quarterly_presentation(2026, 3)
    assert presentation["as_of"] == AS_OF
    assert presentation["quarter_label"] == "III квартал 2026 года"
    assert [s["kind"] for s in presentation["slides"]] == ["insurers", "branch_matrix"]
    assert all(s["as_of"] == AS_OF for s in presentation["slides"])


@pytest.mark.django_db
def test_presentation_order_and_single_portfolio_load(make):
    make([5 * M])
    with mock.patch.object(
        qp_service, "_portfolio", wraps=qp_service._portfolio
    ) as spy:
        presentation = build_quarterly_presentation(2026, 3)
    assert spy.call_count == 1
    slide1, slide2 = presentation["slides"]
    assert slide1["kind"] == "insurers"
    assert slide2["kind"] == "branch_matrix"
    assert slide1["total_sum"] == slide2["total_sum"] == 5 * M


def read_pdf(data):
    assert data.startswith(b"%PDF-")
    return PdfReader(BytesIO(data))


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
def test_pdf_is_two_landscape_16x9_pages(client, make):
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
    assert len(reader.pages) == 2
    for page in reader.pages:
        box = page.mediabox
        assert float(box.width) > float(box.height)
        assert float(box.width) / float(box.height) == pytest.approx(16 / 9)
    first = reader.pages[0].extract_text()
    assert "Распределение имущества по страховщикам" in first
    assert "По состоянию на 30.09.2026" in first
    assert "Итого" in first and "100,00%" in first
    assert "14 000 000" in first
    assert "флоу//полисы" in first
    second = reader.pages[1].extract_text()
    assert "Распределение имущества по филиалам и страховщикам" in second
    assert "Распределение имущества по филиалам" not in first
    assert "По состоянию на 30.09.2026" in second
    assert "Филиал" in second and "Итого" in second
    assert "14,0" in second  # общий итог в млн ₽ совпадает со слайдом 1
    assert "млн ₽" in second
    assert "флоу//полисы" in second


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
def test_pdf_max_rows_with_long_names_stays_two_pages(client, refs, make):
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
    assert len(reader.pages) == 2
    text = reader.pages[0].extract_text()
    for i in range(11):
        assert f"СК «Длинное название {i:02d}»" in text
    assert "Иные" in text
    assert "СК «Длинное название 13»" not in text
    assert "100,00%" in text
    second = reader.pages[1].extract_text()
    assert "Распределение имущества по филиалам и страховщикам" in second
    assert "Иные страховщики" in second
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
    assert len(reader.pages) == 2
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
    assert "без ОСАГО и лимитов ответственности." in text
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
    assert "без ОСАГО и лимитов ответственности." in text
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
    slide1, slide2 = build_quarterly_presentation(2026, 3)["slides"]
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
    html_levels = Counter(
        int(match) for match in re.findall(r'class="num qp-heat-(\d)"', html)
    )
    assert html_levels == levels
    for color in HEAT_COLORS:
        assert html.count(f'style="background: {color};"') == 1  # образец легенды

    response = client.get(url, {"year": 2026, "quarter": 3, "format": "pdf"})
    reader = read_pdf(response.content)
    assert len(reader.pages) == 2
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
    assert "без ОСАГО и лимитов ответственности." in second


@pytest.mark.integration
@pytest.mark.django_db
def test_pdf_max_filled_matrix_stays_two_pages(client, refs, make):
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
    assert "Иные страховщики" in second
    assert "…" in second  # длинные названия обрезаны только для отображения
    slide = build_branch_matrix_slide(AS_OF)
    assert slide["total_sum_display"] in second
    assert slide["rows"][-1]["total_display"] in second
    assert slide["columns"][-1]["total_display"] in second
    assert "7 крупнейших" in second
    assert "млн ₽" in second
    assert "без ОСАГО и лимитов ответственности." in second
    for label in ("до 50", "50–100", "100–200", "200–300", "от 300"):
        assert label in second  # легенда шкалы на второй странице


@pytest.mark.integration
@pytest.mark.django_db
def test_preview_shows_both_slides_with_same_numbers(client, matrix_data):
    client.force_login(User.objects.create_user("qp", "qp@u.ru", "x"))
    html = client.get(
        reverse("reports:quarterly_presentation"), {"year": 2026, "quarter": 3}
    ).content.decode()
    assert "Распределение имущества по страховщикам" in html
    assert "Распределение имущества по филиалам и страховщикам" in html
    assert "две альбомные страницы 16:9" in html
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
