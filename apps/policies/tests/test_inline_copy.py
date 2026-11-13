"""Regression checks for the payment editor and Django's dynamically cloned row."""
from html.parser import HTMLParser

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse


class PaymentRows(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.rows = {}
        self.row = self.cell = None
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr" and "payment-row" in attrs.get("class", "").split():
            self.row = self.rows.setdefault(attrs["id"], {})
        elif self.row is not None:
            if tag == "td":
                self.cell = self.row.setdefault(attrs["class"], [])
            elif self.cell is not None:
                self.cell.append((tag, attrs))

    def handle_endtag(self, tag):
        if tag == "td":
            self.cell = None
        elif tag == "tr":
            self.row = None


@pytest.mark.django_db
def test_copy_and_delete_have_separate_cells_in_every_row(admin_client, sample_payment):
    url = reverse("admin:policies_policy_change", args=[sample_payment.policy_id])
    response = admin_client.get(url)
    html = response.content.decode()
    assert "/static/policies/js/copy_payment_inline.js?v=" in html
    assert "/static/policies/css/copy_payment_inline.css?v=" in html
    rows = PaymentRows(response).rows
    assert set(rows) == {f"payment_schedule-{i}" for i in (0, 1, "empty")}
    for row_id, cells in rows.items():
        assert list(cells)[-2:] == ["payment-copy-cell", "delete"]
        buttons = [
            attrs for tag, attrs in cells["payment-copy-cell"] if tag == "button"
        ]
        assert [button["class"] for button in buttons] == ["copy-payment-btn"]
        assert buttons[0]["type"] == "button"
        controls = [
            attrs.get("name") for tag, attrs in cells["delete"] if tag == "input"
        ]
        assert controls == ([f"{row_id}-DELETE"] if row_id.endswith("-0") else [])
        fields = {
            attrs["name"].rsplit("-", 1)[-1]
            for tag, attrs in cells["payment-details"]
            if tag in ("input", "textarea")
        }
        assert fields == {"insurer_date", "alliance_paid", "payment_info"}


@pytest.mark.django_db
def test_view_only_inline_discloses_values_without_edit_actions(
    client, django_user_model, sample_payment
):
    viewer = django_user_model.objects.create_user("viewer", is_staff=True)
    viewer.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="policies",
            codename__in=("view_policy", "view_paymentschedule"),
        )
    )
    client.force_login(viewer)
    url = reverse("admin:policies_policy_change", args=[sample_payment.policy_id])
    response = client.get(url)
    assert response.status_code == 200
    rows = PaymentRows(response).rows
    assert list(rows) == ["payment_schedule-0"]
    cells = rows["payment_schedule-0"]
    assert "payment-copy-cell" not in cells and not cells["delete"]
    assert all(tag not in ("input", "textarea") for tag, _ in cells["payment-details"])
    assert sample_payment.payment_info in response.content.decode()
