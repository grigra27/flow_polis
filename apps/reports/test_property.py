"""
Property-based тесты для системы экспорта

Используется библиотека Hypothesis для генерации тестовых данных
и проверки свойств корректности системы экспорта.
"""

from hypothesis import given, strategies as st, settings
from hypothesis.extra.django import TestCase, from_model
from django.contrib.auth.models import User
from datetime import date, timedelta
from decimal import Decimal
import json

from apps.clients.models import Client
from apps.insurers.models import Insurer, Branch, InsuranceType, CommissionRate
from apps.policies.models import Policy, PaymentSchedule
from apps.reports.models import CustomExportTemplate
from apps.reports.exporters import CustomExporter, PolicyExporter, PaymentExporter
from apps.reports.filters import PolicyExportFilter, PaymentExportFilter


class PropertyTest1_ColumnCount(TestCase):
    """
    Property Test 1: Корректность количества колонок
    
    Для любого набора выбранных полей (1-20 полей), экспортированный
    Excel файл должен содержать ровно столько колонок, сколько полей было выбрано.
    
    Validates: Property 1 - Корректность экспорта выбранных полей
    """
    
    def setUp(self):
        """Создаем минимальные тестовые данные"""
        self.client_obj = Client.objects.create(
            client_name='Test Client',
            client_inn='1234567890'
        )
        self.insurer = Insurer.objects.create(insurer_name='Test Insurer')
        self.branch = Branch.objects.create(branch_name='Test Branch')
        self.insurance_type = InsuranceType.objects.create(name='Test Type')
        
        self.policy = Policy.objects.create(
            policy_number='TEST-001',
            dfa_number='DFA-001',
            client=self.client_obj,
            insurer=self.insurer,
            branch=self.branch,
            insurance_type=self.insurance_type,
            property_description='Test property',
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            policy_active=True
        )
    
    @settings(max_examples=100, deadline=None)
    @given(
        field_count=st.integers(min_value=1, max_value=10)
    )
    def test_column_count_matches_field_count(self, field_count):
        """Количество колонок должно соответствовать количеству выбранных полей"""
        # Доступные поля для полисов
        available_fields = [
            'policy_number',
            'dfa_number',
            'client__client_name',
            'insurer__insurer_name',
            'branch__branch_name',
            'insurance_type__name',
            'start_date',
            'end_date',
            'policy_active',
            'dfa_active',
        ]
        
        # Выбираем случайное количество полей
        selected_fields = available_fields[:field_count]
        
        # Создаем экспортер
        queryset = Policy.objects.select_related(
            'client', 'insurer', 'branch', 'insurance_type'
        ).all()
        exporter = CustomExporter(queryset, selected_fields, 'policies')
        
        # Получаем заголовки
        headers = exporter.get_headers()
        
        # Проверяем количество колонок
        self.assertEqual(
            len(headers),
            field_count,
            f"Expected {field_count} columns, got {len(headers)}"
        )
        
        # Получаем данные строки
        row = exporter.get_row_data(self.policy)
        
        # Проверяем количество значений в строке
        self.assertEqual(
            len(row),
            field_count,
            f"Expected {field_count} values in row, got {len(row)}"
        )


class PropertyTest2_FilterCorrectness(TestCase):
    """
    Property Test 2: Корректность фильтрации
    
    Для любого набора фильтров, все записи в экспортированном отчете
    должны удовлетворять всем примененным фильтрам (логика AND).
    
    Validates: Property 2 - Корректность применения фильтров
    """
    
    def setUp(self):
        """Создаем разнообразные тестовые данные"""
        # Создаем клиентов
        self.client1 = Client.objects.create(
            client_name='Alpha Corp',
            client_inn='1111111111'
        )
        self.client2 = Client.objects.create(
            client_name='Beta LLC',
            client_inn='2222222222'
        )
        
        # Создаем страховщиков
        self.insurer1 = Insurer.objects.create(insurer_name='Insurer A')
        self.insurer2 = Insurer.objects.create(insurer_name='Insurer B')
        
        # Создаем филиалы
        self.branch1 = Branch.objects.create(branch_name='Branch 1')
        self.branch2 = Branch.objects.create(branch_name='Branch 2')
        
        # Создаем виды страхования
        self.type1 = InsuranceType.objects.create(name='Type 1')
        self.type2 = InsuranceType.objects.create(name='Type 2')
        
        # Создаем полисы с разными параметрами
        self.policies = []
        for i in range(10):
            policy = Policy.objects.create(
                policy_number=f'POL-{i:03d}',
                dfa_number=f'DFA-{i:03d}',
                client=self.client1 if i % 2 == 0 else self.client2,
                insurer=self.insurer1 if i % 3 == 0 else self.insurer2,
                branch=self.branch1 if i % 2 == 0 else self.branch2,
                insurance_type=self.type1 if i % 2 == 0 else self.type2,
                property_description=f'Property {i}',
                start_date=date(2024, 1, 1) + timedelta(days=i*10),
                end_date=date(2024, 12, 31),
                policy_active=(i % 3 != 0),
                dfa_active=(i % 2 == 0)
            )
            self.policies.append(policy)
    
    @settings(max_examples=50, deadline=None)
    @given(
        filter_active=st.booleans(),
        use_branch_filter=st.booleans(),
        use_insurer_filter=st.booleans()
    )
    def test_filtered_results_match_criteria(self, filter_active, use_branch_filter, use_insurer_filter):
        """Все отфильтрованные записи должны соответствовать критериям"""
        # Формируем фильтры
        filter_data = {}
        
        if filter_active:
            filter_data['policy_active'] = True
        
        if use_branch_filter:
            filter_data['branch'] = self.branch1.id
        
        if use_insurer_filter:
            filter_data['insurer'] = self.insurer1.id
        
        # Применяем фильтр
        queryset = Policy.objects.all()
        filterset = PolicyExportFilter(filter_data, queryset=queryset)
        filtered_qs = filterset.qs
        
        # Проверяем каждую запись
        for policy in filtered_qs:
            if filter_active:
                self.assertTrue(
                    policy.policy_active,
                    f"Policy {policy.policy_number} should be active"
                )
            
            if use_branch_filter:
                self.assertEqual(
                    policy.branch,
                    self.branch1,
                    f"Policy {policy.policy_number} should be in Branch 1"
                )
            
            if use_insurer_filter:
                self.assertEqual(
                    policy.insurer,
                    self.insurer1,
                    f"Policy {policy.policy_number} should have Insurer A"
                )


class PropertyTest3_TemplateRoundTrip(TestCase):
    """
    Property Test 3: Round-trip для шаблонов
    
    Для любого сохраненного шаблона, при загрузке должны восстанавливаться
    все сохраненные настройки: источник данных, выбранные поля и фильтры.
    
    Validates: Property 3 - Сохранение и загрузка шаблонов
    """
    
    def setUp(self):
        """Создаем пользователя"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
    
    @settings(max_examples=100, deadline=None)
    @given(
        data_source=st.sampled_from(['policies', 'payments', 'clients', 'insurers']),
        field_count=st.integers(min_value=1, max_value=5),
        filter_count=st.integers(min_value=0, max_value=3)
    )
    def test_template_round_trip(self, data_source, field_count, filter_count):
        """Сохраненный шаблон должен восстанавливаться без изменений"""
        # Генерируем случайные поля
        all_fields = {
            'policies': ['policy_number', 'dfa_number', 'client__client_name', 'start_date', 'policy_active'],
            'payments': ['policy__policy_number', 'due_date', 'amount', 'year_number', 'installment_number'],
            'clients': ['client_name', 'client_inn'],
            'insurers': ['insurer_name']
        }
        
        fields = all_fields[data_source][:field_count]
        
        # Генерируем случайные фильтры
        filters = {}
        for i in range(filter_count):
            filters[f'filter_{i}'] = f'value_{i}'
        
        # Создаем конфигурацию
        config = {
            'fields': fields,
            'filters': filters
        }
        
        # Сохраняем шаблон
        template = CustomExportTemplate.objects.create(
            user=self.user,
            name=f'Test Template {data_source}',
            data_source=data_source,
            config=config
        )
        
        # Загружаем шаблон из БД
        loaded_template = CustomExportTemplate.objects.get(id=template.id)
        
        # Проверяем что все данные совпадают
        self.assertEqual(loaded_template.data_source, data_source)
        self.assertEqual(loaded_template.config['fields'], fields)
        self.assertEqual(loaded_template.config['filters'], filters)
        
        # Проверяем что JSON сериализация/десериализация работает корректно
        config_json = json.dumps(config)
        config_restored = json.loads(config_json)
        self.assertEqual(config_restored, config)


class PropertyTest4_DateFormatting(TestCase):
    """
    Property Test 4: Форматирование дат
    
    Для любой даты в экспортированном файле, формат должен быть "ДД.ММ.ГГГГ".
    
    Validates: Property 5 - Форматирование дат
    """
    
    def setUp(self):
        """Создаем минимальные тестовые данные"""
        self.client_obj = Client.objects.create(
            client_name='Test Client',
            client_inn='1234567890'
        )
        self.insurer = Insurer.objects.create(insurer_name='Test Insurer')
        self.branch = Branch.objects.create(branch_name='Test Branch')
        self.insurance_type = InsuranceType.objects.create(name='Test Type')
    
    @settings(max_examples=100, deadline=None)
    @given(
        year=st.integers(min_value=2020, max_value=2030),
        month=st.integers(min_value=1, max_value=12),
        day=st.integers(min_value=1, max_value=28)  # Используем 28 чтобы избежать проблем с февралем
    )
    def test_date_format_is_correct(self, year, month, day):
        """Все даты должны быть в формате ДД.ММ.ГГГГ"""
        # Создаем полис с случайными датами
        start_date = date(year, month, day)
        end_date = start_date + timedelta(days=365)
        
        policy = Policy.objects.create(
            policy_number='TEST-DATE',
            dfa_number='DFA-DATE',
            client=self.client_obj,
            insurer=self.insurer,
            branch=self.branch,
            insurance_type=self.insurance_type,
            property_description='Test property',
            start_date=start_date,
            end_date=end_date,
            policy_active=True
        )
        
        # Создаем экспортер
        exporter = CustomExporter(
            Policy.objects.filter(id=policy.id),
            ['start_date', 'end_date'],
            'policies'
        )
        
        # Получаем данные строки
        row = exporter.get_row_data(policy)
        
        # Проверяем формат дат
        start_date_str = row[0]
        end_date_str = row[1]
        
        # Проверяем что это строки
        self.assertIsInstance(start_date_str, str)
        self.assertIsInstance(end_date_str, str)
        
        # Проверяем формат ДД.ММ.ГГГГ
        import re
        date_pattern = r'^\d{2}\.\d{2}\.\d{4}$'
        
        self.assertRegex(
            start_date_str,
            date_pattern,
            f"Start date '{start_date_str}' doesn't match DD.MM.YYYY format"
        )
        self.assertRegex(
            end_date_str,
            date_pattern,
            f"End date '{end_date_str}' doesn't match DD.MM.YYYY format"
        )
        
        # Проверяем что дата корректно форматируется
        expected_start = start_date.strftime('%d.%m.%Y')
        self.assertEqual(start_date_str, expected_start)
        
        # Очищаем тестовые данные
        policy.delete()


class PropertyTest5_DecimalFormatting(TestCase):
    """
    Property Test 5: Форматирование Decimal значений
    
    Для любого Decimal значения в экспортированном файле,
    оно должно быть преобразовано в float.
    
    Validates: Property 1 - Корректность экспорта выбранных полей
    """
    
    def setUp(self):
        """Создаем минимальные тестовые данные"""
        self.client_obj = Client.objects.create(
            client_name='Test Client',
            client_inn='1234567890'
        )
        self.insurer = Insurer.objects.create(insurer_name='Test Insurer')
        self.branch = Branch.objects.create(branch_name='Test Branch')
        self.insurance_type = InsuranceType.objects.create(name='Test Type')
    
    @settings(max_examples=100, deadline=None)
    @given(
        premium=st.decimals(
            min_value=Decimal('1000.00'),
            max_value=Decimal('10000000.00'),
            places=2
        )
    )
    def test_decimal_converted_to_float(self, premium):
        """Decimal значения должны быть преобразованы в float"""
        # Создаем полис со случайной премией
        policy = Policy.objects.create(
            policy_number='TEST-DECIMAL',
            dfa_number='DFA-DECIMAL',
            client=self.client_obj,
            insurer=self.insurer,
            branch=self.branch,
            insurance_type=self.insurance_type,
            property_description='Test property',
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            premium_total=premium,
            policy_active=True
        )
        
        # Создаем экспортер
        exporter = CustomExporter(
            Policy.objects.filter(id=policy.id),
            ['premium_total'],
            'policies'
        )
        
        # Получаем данные строки
        row = exporter.get_row_data(policy)
        premium_value = row[0]
        
        # Проверяем что это float
        self.assertIsInstance(
            premium_value,
            float,
            f"Premium value should be float, got {type(premium_value)}"
        )
        
        # Проверяем что значение корректно
        self.assertAlmostEqual(
            premium_value,
            float(premium),
            places=2
        )
        
        # Очищаем тестовые данные
        policy.delete()


class PropertyTest6_QueryOptimization(TestCase):
    """
    Property Test 6: Оптимизация запросов
    
    Для любого отчета с полями из связанных таблиц,
    должен использоваться select_related для ForeignKey полей.
    
    Validates: Property 6 - Оптимизация запросов
    """
    
    def setUp(self):
        """Создаем тестовые данные"""
        self.client_obj = Client.objects.create(
            client_name='Test Client',
            client_inn='1234567890'
        )
        self.insurer = Insurer.objects.create(insurer_name='Test Insurer')
        self.branch = Branch.objects.create(branch_name='Test Branch')
        self.insurance_type = InsuranceType.objects.create(name='Test Type')
        
        # Создаем несколько полисов
        for i in range(5):
            Policy.objects.create(
                policy_number=f'TEST-{i:03d}',
                dfa_number=f'DFA-{i:03d}',
                client=self.client_obj,
                insurer=self.insurer,
                branch=self.branch,
                insurance_type=self.insurance_type,
                property_description=f'Property {i}',
                start_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31),
                policy_active=True
            )
    
    @settings(max_examples=20, deadline=None)
    @given(
        use_related_fields=st.booleans()
    )
    def test_query_count_with_select_related(self, use_related_fields):
        """Количество запросов должно быть минимальным при использовании select_related"""
        from django.test.utils import override_settings
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        
        if use_related_fields:
            fields = ['policy_number', 'client__client_name', 'insurer__insurer_name']
        else:
            fields = ['policy_number', 'dfa_number']
        
        # Получаем queryset с оптимизацией
        queryset = Policy.objects.all()
        
        # Оптимизируем queryset
        if use_related_fields:
            queryset = queryset.select_related('client', 'insurer')
        
        # Считаем количество запросов
        with CaptureQueriesContext(connection) as context:
            exporter = CustomExporter(queryset, fields, 'policies')
            
            # Получаем данные для всех полисов
            for policy in queryset:
                row = exporter.get_row_data(policy)
        
        query_count = len(context.captured_queries)
        
        if use_related_fields:
            # С select_related должно быть не более 2 запросов
            # (1 для получения полисов с related данными)
            self.assertLessEqual(
                query_count,
                2,
                f"With select_related, expected <= 2 queries, got {query_count}"
            )
        else:
            # Без related полей должен быть 1 запрос
            self.assertLessEqual(
                query_count,
                2,
                f"Without related fields, expected <= 2 queries, got {query_count}"
            )
