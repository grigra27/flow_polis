from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from pypdf import PdfReader
from openpyxl import load_workbook
from apps.clients.models import Client
from apps.insurers.models import Branch, InsuranceType, Insurer
from apps.policies.models import Policy, PaymentSchedule
from apps.core.services.dashboard_v3_service import DashboardV3Service
from apps.core.services.portfolio_scope import PortfolioScope
from apps.reports.services.property_document import build_property_document
from apps.reports.services.property_pdf import build_property_pdf, logo
from apps.reports.services.property_snapshot import build_property_snapshot

AS_OF = date(2027, 6, 15)
pytestmark = pytest.mark.django_db


@pytest.fixture
def make_pdf_policy():
    client = Client.objects.create(
        client_name="ООО «Тест & <Компания>»", client_inn="7700999988"
    )
    branch = Branch.objects.create(branch_name="Тестовый филиал")
    insurer = Insurer.objects.create(insurer_name="Тестовый страховщик")
    kind = InsuranceType.objects.create(name="Имущество PDF", needs_prolongation=True)
    serial = 0

    def make(*, value=1000, amount=100, **kwargs):
        nonlocal serial
        serial += 1
        values = dict(
            policy_number=f"PDF-{serial}",
            dfa_number=f"DFA-PDF-{serial}",
            client=client,
            branch=branch,
            insurer=insurer,
            insurance_type=kind,
            policy_active=True,
            dfa_active=True,
            broker_participation=True,
            property_description="Станок & <оснастка>",
            start_date=AS_OF - timedelta(days=30),
            end_date=AS_OF + timedelta(days=20),
        )
        values.update(kwargs)
        obj = Policy.objects.create(**values)
        PaymentSchedule.objects.bulk_create(
            [
                PaymentSchedule(
                    policy=obj,
                    year_number=1,
                    installment_number=1,
                    due_date=AS_OF - timedelta(days=30),
                    amount=Decimal(amount),
                    insurance_sum=value,
                    kv_rub=Decimal("98765.43"),
                )
            ]
        )
        return obj

    return make


def read_pdf(report):
    data = build_property_pdf(report)
    assert data.startswith(b"%PDF-")
    return PdfReader(BytesIO(data))


def test_property_and_liability_reconcile_in_report_snapshot_and_dashboard(
    make_pdf_policy,
):
    make_pdf_policy(value=1000)
    kind = InsuranceType.objects.create(name="Ответственность")
    liability_policy = make_pdf_policy(value=200, insurance_type=kind)
    report = build_property_document(AS_OF)
    assert report["totals"]["sum"] == 1000
    assert report["totals"]["count"] == 1
    assert report["liability"]["sum"] == 200
    assert report["scope_total"] == 1200
    assert (
        DashboardV3Service(PortfolioScope(AS_OF, "all", ())).context()["total_sum"]
        == 1000
    )
    assert build_property_snapshot(AS_OF)["total_insurance_sum"] == 1000
    assert [r["name"] for r in report["by_type"]] == ["Имущество PDF"]
    assert {
        row["policy_number"]: row["sum"] for row in report["liability"]["rows"]
    } == {liability_policy.policy_number: 200}


@pytest.mark.parametrize(
    "mode,expected", [("all", 3000), ("broker", 1000), ("direct", 2000)]
)
def test_document_scope_and_branch_are_preserved(make_pdf_policy, mode, expected):
    a = make_pdf_policy(value=1000)
    make_pdf_policy(value=2000, broker_participation=False)
    other = Branch.objects.create(branch_name="Другой филиал")
    make_pdf_policy(value=9000, branch=other)
    report = build_property_document(AS_OF, (a.branch_id,), mode)
    assert report["totals"]["sum"] == expected
    assert report["selected_branches"] == [a.branch.branch_name]
    assert all(r["branch"] == a.branch.branch_name for r in report["top_objects"])


def test_endings_and_renewals_are_different_cohorts(make_pdf_policy):
    make_pdf_policy()
    make_pdf_policy(dfa_deactivation_date=AS_OF + timedelta(days=10))
    make_pdf_policy(termination_date=AS_OF + timedelta(days=10))
    no_renewal = InsuranceType.objects.create(
        name="Непродлеваемый PDF", needs_prolongation=False
    )
    make_pdf_policy(insurance_type=no_renewal)
    report = build_property_document(AS_OF)
    assert report["renewals"][0]["endings"]["count"] == 4
    assert report["renewals"][0]["candidates"]["count"] == 1
    assert report["renewals"][0]["candidates"]["sum"] == 1000


@pytest.mark.parametrize("empty", [False, True])
def test_eight_main_pages_and_readable_appendices(make_pdf_policy, empty):
    if not empty:
        make_pdf_policy()
    reader = read_pdf(build_property_document(AS_OF))
    assert 12 <= len(reader.pages)
    assert "Методика и полнота данных" in reader.pages[7].extract_text()
    assert "Приложение А" in reader.pages[8].extract_text()
    assert reader.outline
    for i, page in enumerate(reader.pages, 1):
        text = page.extract_text()
        assert f"{i} / {len(reader.pages)}" in text
        assert "\ufffd" not in text
    assert any(float(p.mediabox.width) > float(p.mediabox.height) for p in reader.pages)
    if not empty:
        text = "\n".join(p.extract_text() for p in reader.pages)
        assert "ООО «Тест & <Компания>»" in text
        assert "Станок & <оснастка>" in text


def test_large_table_long_description_and_unknown_sum(make_pdf_policy):
    description = "Оборудование и комплектующие " * 450 + " КОНЕЦ_ПОЛНОГО_ОПИСАНИЯ"
    for i in range(20):
        insurer = Insurer.objects.create(
            insurer_name=f"Компания {i:02d} " + ("страхования имущества " * 3)
        )
        make_pdf_policy(
            value=1000 + i,
            insurer=insurer,
            property_description=description if i == 19 else "Имущество",
        )
    make_pdf_policy(value=None)
    report = build_property_document(AS_OF)
    reader = read_pdf(report)
    assert "Методика и полнота данных" in reader.pages[7].extract_text()
    text = "\n".join(p.extract_text() for p in reader.pages)
    assert "КОНЕЦ_ПОЛНОГО_ОПИСАНИЯ" in text
    assert "Компания 00" in text and "Компания 19" in text
    assert report["totals"]["missing_sum_count"] == 1
    assert all(r["sum"] is not None for r in report["top_objects"])


@pytest.mark.parametrize("superuser", [False, True])
def test_pdf_access_disposition_filters_and_no_commission(
    client, make_pdf_policy, superuser
):
    obj = make_pdf_policy()
    url = reverse("reports:property_report")
    query = {
        "as_of": AS_OF.isoformat(),
        "branch": obj.branch_id,
        "structure_scope": "broker",
        "format": "pdf",
    }
    assert client.get(url, query).status_code == 302
    user = User.objects.create_user(
        username=f"pdf-{superuser}", is_staff=superuser, is_superuser=superuser
    )
    client.force_login(user)
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url, query)
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"].startswith("attachment;")
    assert "no-store" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"
    sql = " ".join(q["sql"].lower() for q in queries)
    assert "kv_rub" not in sql and "commission_rate" not in sql
    text = "\n".join(
        p.extract_text() for p in PdfReader(BytesIO(response.content)).pages
    )
    assert "15.06.2027" in text and "С участием брокера" in text
    assert not any(
        word in text.lower()
        for word in ("98765", "комиссион", "вознагражден", "доход компании")
    )
    response = client.get(url, {**query, "disposition": "inline"})
    assert response["Content-Disposition"].startswith("inline;")
    html = client.get(url, {k: v for k, v in query.items() if k != "format"})
    assert b"format=pdf" in html.content and b"disposition=inline" in html.content
    assert "branch=" + str(obj.branch_id) in html.context["pdf_query"]
    excel = client.get(url, {**query, "format": "xlsx"})
    workbook = load_workbook(BytesIO(excel.content), read_only=True)
    assert (
        "Ответственность" in workbook.sheetnames and "Методика" in workbook.sheetnames
    )
    workbook.close()


def test_pdf_image_loader_does_not_open_arbitrary_files(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MEDIA_ROOT.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"not an image")
    path = settings.MEDIA_ROOT / "branch_logos"
    path.mkdir()
    (path / "link.png").symlink_to(outside)
    for url in (
        "https://example.com/image.png",
        "/media/documents/private.png",
        "/media/../outside.png",
        "/media/branch_logos/link.png",
    ):
        assert logo(url) is None
