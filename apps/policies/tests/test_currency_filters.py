from django.test import TestCase
from apps.policies.templatetags.currency_filters import format_rub


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
