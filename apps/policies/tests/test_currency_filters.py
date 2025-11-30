from django.test import TestCase
from apps.policies.templatetags.currency_filters import format_rub, format_percent


class CurrencyFiltersTestCase(TestCase):
    """Тесты для фильтра форматирования валюты."""

    def test_format_rub_integer(self):
        """Тест форматирования целого числа."""
        self.assertEqual(format_rub(100000), "100 000")
        self.assertEqual(format_rub(1500000), "1 500 000")
        self.assertEqual(format_rub(500), "500")

    def test_format_rub_decimal(self):
        """Тест форматирования числа с копейками."""
        self.assertEqual(format_rub(100000.50), "100 000.50")
        self.assertEqual(format_rub(1500000.99), "1 500 000.99")

    def test_format_rub_string_number(self):
        """Тест форматирования строки с числом."""
        self.assertEqual(format_rub("100000"), "100 000")
        self.assertEqual(format_rub("100000.50"), "100 000.50")

    def test_format_rub_invalid_input(self):
        """Тест обработки некорректного ввода."""
        self.assertEqual(format_rub("invalid"), "invalid")
        self.assertEqual(format_rub(None), None)


class PercentFiltersTestCase(TestCase):
    """Тесты для фильтра форматирования процентов."""

    def test_format_percent_integer(self):
        """Тест форматирования целого процента."""
        self.assertEqual(format_percent(10), "10")
        self.assertEqual(format_percent(15), "15")
        self.assertEqual(format_percent(100), "100")

    def test_format_percent_decimal(self):
        """Тест форматирования процента с дробной частью."""
        self.assertEqual(format_percent(12.50), "12")  # банковское округление
        self.assertEqual(format_percent(15.00), "15")
        self.assertEqual(format_percent(10.49), "10")
        self.assertEqual(format_percent(10.51), "11")
        self.assertEqual(format_percent(13.50), "14")  # банковское округление

    def test_format_percent_string_number(self):
        """Тест форматирования строки с числом."""
        self.assertEqual(format_percent("12.50"), "12")  # банковское округление
        self.assertEqual(format_percent("15"), "15")

    def test_format_percent_invalid_input(self):
        """Тест обработки некорректного ввода."""
        self.assertEqual(format_percent("invalid"), "invalid")
        self.assertEqual(format_percent(None), None)
