from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.insurers.models import Branch, InsuranceType, Insurer
from apps.policies.models import Policy

from .models import Client

User = get_user_model()


class ClientDetailViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="client_detail_user", password="testpass123"
        )
        self.client.login(username="client_detail_user", password="testpass123")

        self.leasing_client = Client.objects.create(
            client_name="ООО Тест Лизинг", client_inn="7701234567"
        )
        self.insurer = Insurer.objects.create(insurer_name="Тестовая СК")
        self.branch = Branch.objects.create(branch_name="Тестовый филиал")
        self.insurance_type = InsuranceType.objects.create(name="КАСКО")

    def test_client_detail_highlights_no_broker_policy_rows(self):
        Policy.objects.create(
            policy_number="POL-CLIENT-001",
            dfa_number="DFA-POL-CLIENT-001",
            client=self.leasing_client,
            insurer=self.insurer,
            property_description="Тестовое имущество",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            insurance_type=self.insurance_type,
            branch=self.branch,
            policy_active=True,
            broker_participation=False,
        )

        response = self.client.get(
            reverse("clients:detail", args=[self.leasing_client.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "tbl-row-nobroker")
        self.assertContains(response, "Без брокера")
