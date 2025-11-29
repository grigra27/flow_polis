from django.test import TestCase
from django.contrib.auth.models import User
from .models import CustomExportTemplate


class CustomExportTemplateModelTest(TestCase):
    """Тесты модели CustomExportTemplate"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
    
    def test_create_template(self):
        """Тест создания шаблона экспорта"""
        template = CustomExportTemplate.objects.create(
            user=self.user,
            name='Тестовый шаблон',
            data_source='policies',
            config={
                'fields': ['policy_number', 'client__client_name'],
                'filters': {'branch': 1}
            }
        )
        
        self.assertEqual(template.name, 'Тестовый шаблон')
        self.assertEqual(template.data_source, 'policies')
        self.assertEqual(template.user, self.user)
        self.assertIsNotNone(template.created_at)
        self.assertIsNotNone(template.updated_at)
    
    def test_template_str(self):
        """Тест строкового представления шаблона"""
        template = CustomExportTemplate.objects.create(
            user=self.user,
            name='Мой шаблон',
            data_source='payments',
            config={}
        )
        
        self.assertEqual(str(template), 'Мой шаблон (Платежи)')
    
    def test_unique_name_per_user(self):
        """Тест уникальности имени шаблона для пользователя"""
        CustomExportTemplate.objects.create(
            user=self.user,
            name='Уникальный шаблон',
            data_source='policies',
            config={}
        )
        
        # Попытка создать шаблон с тем же именем должна вызвать ошибку
        with self.assertRaises(Exception):
            CustomExportTemplate.objects.create(
                user=self.user,
                name='Уникальный шаблон',
                data_source='payments',
                config={}
            )
    
    def test_different_users_same_name(self):
        """Тест: разные пользователи могут иметь шаблоны с одинаковым именем"""
        user2 = User.objects.create_user(
            username='testuser2',
            password='testpass123'
        )
        
        template1 = CustomExportTemplate.objects.create(
            user=self.user,
            name='Общий шаблон',
            data_source='policies',
            config={}
        )
        
        template2 = CustomExportTemplate.objects.create(
            user=user2,
            name='Общий шаблон',
            data_source='payments',
            config={}
        )
        
        self.assertNotEqual(template1.id, template2.id)
        self.assertEqual(template1.name, template2.name)



class BaseExporterTest(TestCase):
    """Тесты базового экспортера"""
    
    def setUp(self):
        from .exporters import BaseExporter
        
        # Создаем простой экспортер для тестирования
        class TestExporter(BaseExporter):
            def get_headers(self):
                return ['Заголовок 1', 'Заголовок 2']
            
            def get_row_data(self, obj):
                return [obj.get('field1'), obj.get('field2')]
            
            def get_filename(self):
                return 'test_report'
        
        self.TestExporter = TestExporter
    
    def test_format_value_date(self):
        """Тест форматирования даты"""
        from datetime import date
        exporter = self.TestExporter([], [])
        
        test_date = date(2024, 1, 15)
        formatted = exporter.format_value(test_date)
        
        self.assertEqual(formatted, '15.01.2024')
    
    def test_format_value_decimal(self):
        """Тест форматирования Decimal"""
        from decimal import Decimal
        exporter = self.TestExporter([], [])
        
        test_decimal = Decimal('123.45')
        formatted = exporter.format_value(test_decimal)
        
        self.assertEqual(formatted, 123.45)
        self.assertIsInstance(formatted, float)
    
    def test_format_value_bool(self):
        """Тест форматирования boolean"""
        exporter = self.TestExporter([], [])
        
        self.assertEqual(exporter.format_value(True), 'Да')
        self.assertEqual(exporter.format_value(False), 'Нет')
    
    def test_format_value_none(self):
        """Тест форматирования None"""
        exporter = self.TestExporter([], [])
        
        self.assertEqual(exporter.format_value(None), '')
    
    def test_export_creates_response(self):
        """Тест создания HTTP ответа с Excel файлом"""
        test_data = [
            {'field1': 'Значение 1', 'field2': 'Значение 2'},
            {'field1': 'Значение 3', 'field2': 'Значение 4'},
        ]
        
        exporter = self.TestExporter(test_data, [])
        response = exporter.export()
        
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        self.assertIn('test_report_', response['Content-Disposition'])
        self.assertIn('.xlsx', response['Content-Disposition'])


class FilterTest(TestCase):
    """Тесты фильтров экспорта"""
    
    def setUp(self):
        from apps.clients.models import Client
        from apps.insurers.models import Insurer, Branch, InsuranceType
        from apps.policies.models import Policy
        from datetime import date
        
        # Создаем тестовые данные
        self.client1 = Client.objects.create(
            client_name='Тестовый клиент 1',
            client_inn='1234567890'
        )
        self.client2 = Client.objects.create(
            client_name='Другой клиент',
            client_inn='0987654321'
        )
        
        self.insurer = Insurer.objects.create(insurer_name='Тестовая СК')
        self.branch = Branch.objects.create(branch_name='Тестовый филиал')
        self.insurance_type = InsuranceType.objects.create(name='КАСКО')
        
        self.policy1 = Policy.objects.create(
            policy_number='POL-001',
            dfa_number='DFA-001',
            client=self.client1,
            insurer=self.insurer,
            branch=self.branch,
            insurance_type=self.insurance_type,
            property_description='Тестовое имущество',
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            policy_active=True
        )
        
        self.policy2 = Policy.objects.create(
            policy_number='POL-002',
            dfa_number='DFA-002',
            client=self.client2,
            insurer=self.insurer,
            branch=self.branch,
            insurance_type=self.insurance_type,
            property_description='Другое имущество',
            start_date=date(2024, 6, 1),
            end_date=date(2025, 5, 31),
            policy_active=False
        )
    
    def test_policy_filter_by_number(self):
        """Тест фильтрации полисов по номеру"""
        from .filters import PolicyExportFilter
        from apps.policies.models import Policy
        
        f = PolicyExportFilter(
            {'policy_number': 'POL-001'},
            queryset=Policy.objects.all()
        )
        
        self.assertEqual(f.qs.count(), 1)
        self.assertEqual(f.qs.first(), self.policy1)
    
    def test_policy_filter_by_client_name(self):
        """Тест фильтрации полисов по имени клиента"""
        from .filters import PolicyExportFilter
        from apps.policies.models import Policy
        
        f = PolicyExportFilter(
            {'client__client_name': 'Тестовый'},
            queryset=Policy.objects.all()
        )
        
        self.assertEqual(f.qs.count(), 1)
        self.assertEqual(f.qs.first().client, self.client1)
    
    def test_policy_filter_by_active(self):
        """Тест фильтрации полисов по статусу активности"""
        from .filters import PolicyExportFilter
        from apps.policies.models import Policy
        
        f = PolicyExportFilter(
            {'policy_active': True},
            queryset=Policy.objects.all()
        )
        
        self.assertEqual(f.qs.count(), 1)
        self.assertEqual(f.qs.first(), self.policy1)
    
    def test_policy_filter_by_date_range(self):
        """Тест фильтрации полисов по диапазону дат"""
        from .filters import PolicyExportFilter
        from apps.policies.models import Policy
        from datetime import date
        
        f = PolicyExportFilter(
            {
                'start_date_from': date(2024, 1, 1),
                'start_date_to': date(2024, 3, 31)
            },
            queryset=Policy.objects.all()
        )
        
        self.assertEqual(f.qs.count(), 1)
        self.assertEqual(f.qs.first(), self.policy1)
    
    def test_client_filter_by_name(self):
        """Тест фильтрации клиентов по имени"""
        from .filters import ClientExportFilter
        from apps.clients.models import Client
        
        f = ClientExportFilter(
            {'client_name': 'Тестовый'},
            queryset=Client.objects.all()
        )
        
        self.assertEqual(f.qs.count(), 1)
        self.assertEqual(f.qs.first(), self.client1)
    
    def test_client_filter_by_inn(self):
        """Тест фильтрации клиентов по ИНН"""
        from .filters import ClientExportFilter
        from apps.clients.models import Client
        
        f = ClientExportFilter(
            {'client_inn': '1234'},
            queryset=Client.objects.all()
        )
        
        self.assertEqual(f.qs.count(), 1)
        self.assertEqual(f.qs.first(), self.client1)
    
    def test_insurer_filter_by_name(self):
        """Тест фильтрации страховщиков по имени"""
        from .filters import InsurerExportFilter
        from apps.insurers.models import Insurer
        
        f = InsurerExportFilter(
            {'insurer_name': 'Тестовая'},
            queryset=Insurer.objects.all()
        )
        
        self.assertEqual(f.qs.count(), 1)
        self.assertEqual(f.qs.first(), self.insurer)



class CustomExporterTest(TestCase):
    """Тесты CustomExporter"""
    
    def setUp(self):
        from apps.clients.models import Client
        from apps.insurers.models import Insurer, Branch, InsuranceType
        from apps.policies.models import Policy
        from datetime import date
        from decimal import Decimal
        
        # Создаем тестовые данные
        self.client = Client.objects.create(
            client_name='Тестовый клиент',
            client_inn='1234567890'
        )
        
        self.insurer = Insurer.objects.create(insurer_name='Тестовая СК')
        self.branch = Branch.objects.create(branch_name='Тестовый филиал')
        self.insurance_type = InsuranceType.objects.create(name='КАСКО')
        
        self.policy = Policy.objects.create(
            policy_number='POL-001',
            dfa_number='DFA-001',
            client=self.client,
            insurer=self.insurer,
            branch=self.branch,
            insurance_type=self.insurance_type,
            property_description='Тестовое имущество',
            start_date=date(2024, 1, 15),
            end_date=date(2024, 12, 31),
            premium_total=Decimal('100000.00'),
            policy_active=True
        )
    
    def test_custom_exporter_get_headers(self):
        """Тест получения заголовков CustomExporter"""
        from .exporters import CustomExporter
        from apps.policies.models import Policy
        
        fields = ['policy_number', 'client__client_name', 'premium_total']
        exporter = CustomExporter(Policy.objects.all(), fields, 'policies')
        
        headers = exporter.get_headers()
        
        self.assertEqual(len(headers), 3)
        self.assertEqual(headers[0], 'Номер полиса')
        self.assertEqual(headers[1], 'Клиент')
        self.assertEqual(headers[2], 'Общая премия')
    
    def test_custom_exporter_get_field_value(self):
        """Тест получения значения поля с вложенными полями"""
        from .exporters import CustomExporter
        from apps.policies.models import Policy
        
        exporter = CustomExporter(Policy.objects.all(), [], 'policies')
        
        # Простое поле
        value = exporter.get_field_value(self.policy, 'policy_number')
        self.assertEqual(value, 'POL-001')
        
        # Вложенное поле
        value = exporter.get_field_value(self.policy, 'client__client_name')
        self.assertEqual(value, 'Тестовый клиент')
        
        # Двойное вложение
        value = exporter.get_field_value(self.policy, 'insurer__insurer_name')
        self.assertEqual(value, 'Тестовая СК')
    
    def test_custom_exporter_format_date(self):
        """Тест форматирования даты в CustomExporter"""
        from .exporters import CustomExporter
        from apps.policies.models import Policy
        
        exporter = CustomExporter(Policy.objects.all(), [], 'policies')
        
        value = exporter.get_field_value(self.policy, 'start_date')
        self.assertEqual(value, '15.01.2024')
    
    def test_custom_exporter_format_decimal(self):
        """Тест форматирования Decimal в CustomExporter"""
        from .exporters import CustomExporter
        from apps.policies.models import Policy
        
        exporter = CustomExporter(Policy.objects.all(), [], 'policies')
        
        value = exporter.get_field_value(self.policy, 'premium_total')
        self.assertEqual(value, 100000.0)
        self.assertIsInstance(value, float)
    
    def test_custom_exporter_format_bool(self):
        """Тест форматирования boolean в CustomExporter"""
        from .exporters import CustomExporter
        from apps.policies.models import Policy
        
        exporter = CustomExporter(Policy.objects.all(), [], 'policies')
        
        value = exporter.get_field_value(self.policy, 'policy_active')
        self.assertEqual(value, 'Да')
    
    def test_custom_exporter_get_row_data(self):
        """Тест получения данных строки"""
        from .exporters import CustomExporter
        from apps.policies.models import Policy
        
        fields = ['policy_number', 'client__client_name', 'policy_active']
        exporter = CustomExporter(Policy.objects.all(), fields, 'policies')
        
        row = exporter.get_row_data(self.policy)
        
        self.assertEqual(len(row), 3)
        self.assertEqual(row[0], 'POL-001')
        self.assertEqual(row[1], 'Тестовый клиент')
        self.assertEqual(row[2], 'Да')
    
    def test_custom_exporter_filename(self):
        """Тест генерации имени файла"""
        from .exporters import CustomExporter
        from apps.policies.models import Policy
        
        exporter = CustomExporter(Policy.objects.all(), [], 'policies')
        filename = exporter.get_filename()
        
        self.assertEqual(filename, 'custom_export_policies')


class CustomExportViewTest(TestCase):
    """Тесты представления CustomExportView"""
    
    def setUp(self):
        from apps.clients.models import Client
        from apps.insurers.models import Insurer, Branch, InsuranceType
        from apps.policies.models import Policy
        from datetime import date
        
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        # Создаем тестовые данные
        self.client = Client.objects.create(
            client_name='Тестовый клиент',
            client_inn='1234567890'
        )
        
        self.insurer = Insurer.objects.create(insurer_name='Тестовая СК')
        self.branch = Branch.objects.create(branch_name='Тестовый филиал')
        self.insurance_type = InsuranceType.objects.create(name='КАСКО')
        
        self.policy = Policy.objects.create(
            policy_number='POL-001',
            dfa_number='DFA-001',
            client=self.client,
            insurer=self.insurer,
            branch=self.branch,
            insurance_type=self.insurance_type,
            property_description='Тестовое имущество',
            start_date=date(2024, 1, 15),
            end_date=date(2024, 12, 31),
            policy_active=True
        )
    
    def test_custom_export_view_requires_login(self):
        """Тест: CustomExportView требует авторизации"""
        from django.test import Client as TestClient
        
        client = TestClient()
        response = client.get('/reports/custom/')
        
        # Должен перенаправить на страницу входа
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)
    
    def test_custom_export_view_get(self):
        """Тест GET запроса к CustomExportView"""
        from django.test import Client as TestClient
        
        client = TestClient()
        client.login(username='testuser', password='testpass123')
        
        response = client.get('/reports/custom/')
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('available_fields', response.context)
        self.assertIn('templates', response.context)
    
    def test_save_template(self):
        """Тест сохранения шаблона"""
        from django.test import Client as TestClient
        
        client = TestClient()
        client.login(username='testuser', password='testpass123')
        
        response = client.post('/reports/custom/', {
            'action': 'save_template',
            'template_name': 'Мой шаблон',
            'data_source': 'policies',
            'fields': ['policy_number', 'client__client_name']
        })
        
        # Проверяем что шаблон создан
        template = CustomExportTemplate.objects.filter(
            user=self.user,
            name='Мой шаблон'
        ).first()
        
        self.assertIsNotNone(template)
        self.assertEqual(template.data_source, 'policies')
        self.assertEqual(template.config['fields'], ['policy_number', 'client__client_name'])
    
    def test_export_without_fields(self):
        """Тест экспорта без выбранных полей"""
        from django.test import Client as TestClient
        
        client = TestClient()
        client.login(username='testuser', password='testpass123')
        
        response = client.post('/reports/custom/', {
            'action': 'export',
            'data_source': 'policies',
            'fields': []
        })
        
        # Должен перенаправить обратно с сообщением об ошибке
        self.assertEqual(response.status_code, 302)
    
    def test_export_with_fields(self):
        """Тест экспорта с выбранными полями"""
        from django.test import Client as TestClient
        
        client = TestClient()
        client.login(username='testuser', password='testpass123')
        
        response = client.post('/reports/custom/', {
            'action': 'export',
            'data_source': 'policies',
            'fields': ['policy_number', 'client__client_name']
        })
        
        # Должен вернуть Excel файл
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    
    def test_delete_template(self):
        """Тест удаления шаблона"""
        from django.test import Client as TestClient
        
        # Делаем пользователя staff для прохождения middleware
        self.user.is_staff = True
        self.user.save()
        
        # Создаем шаблон
        template = CustomExportTemplate.objects.create(
            user=self.user,
            name='Шаблон для удаления',
            data_source='policies',
            config={'fields': ['policy_number']}
        )
        
        client = TestClient()
        client.login(username='testuser', password='testpass123')
        
        response = client.post(f'/reports/custom/template/{template.id}/delete/')
        
        # Проверяем что шаблон удален
        self.assertFalse(
            CustomExportTemplate.objects.filter(id=template.id).exists()
        )


class PolicyExporterTest(TestCase):
    """Тесты PolicyExporter"""
    
    def setUp(self):
        """Подготовка тестовых данных"""
        from apps.clients.models import Client
        from apps.insurers.models import Insurer, Branch, InsuranceType
        from apps.policies.models import Policy
        from datetime import date
        from decimal import Decimal
        
        # Создаем клиента
        self.client = Client.objects.create(
            client_name='Тестовый клиент',
            client_inn='1234567890'
        )
        
        # Создаем страховщика
        self.insurer = Insurer.objects.create(
            insurer_name='Тестовый страховщик'
        )
        
        # Создаем филиал
        self.branch = Branch.objects.create(
            branch_name='Главный офис'
        )
        
        # Создаем вид страхования
        self.insurance_type = InsuranceType.objects.create(
            name='КАСКО'
        )
        
        # Создаем полис
        self.policy = Policy.objects.create(
            policy_number='TEST-001',
            dfa_number='DFA-001',
            client=self.client,
            insurer=self.insurer,
            branch=self.branch,
            insurance_type=self.insurance_type,
            property_description='Тестовое имущество',
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            policy_active=True
        )
    
    def test_policy_exporter_get_headers(self):
        """Тест получения заголовков PolicyExporter"""
        from apps.policies.models import Policy
        from apps.reports.exporters import PolicyExporter
        
        queryset = Policy.objects.all()
        exporter = PolicyExporter(queryset, [])
        headers = exporter.get_headers()
        
        self.assertEqual(len(headers), 14)
        self.assertIn('Номер полиса', headers)
        self.assertIn('Клиент', headers)
        self.assertIn('Страховщик', headers)
    
    def test_policy_exporter_get_row_data(self):
        """Тест получения данных строки для полиса"""
        from apps.reports.exporters import PolicyExporter
        
        exporter = PolicyExporter([], [])
        row = exporter.get_row_data(self.policy)
        
        self.assertEqual(len(row), 14)
        self.assertEqual(row[0], 'TEST-001')  # policy_number
        self.assertEqual(row[1], 'DFA-001')  # dfa_number
        self.assertEqual(row[2], 'Тестовый клиент')  # client
        self.assertEqual(row[3], 'Тестовый страховщик')  # insurer
        self.assertEqual(row[6], '01.01.2024')  # start_date
        self.assertEqual(row[10], 'Активен')  # policy_active
    
    def test_policy_exporter_filename(self):
        """Тест генерации имени файла"""
        from apps.policies.models import Policy
        from apps.reports.exporters import PolicyExporter
        
        queryset = Policy.objects.all()
        exporter = PolicyExporter(queryset, [])
        
        self.assertEqual(exporter.get_filename(), 'policies')
    
    def test_policy_exporter_export(self):
        """Тест полного экспорта полисов"""
        from apps.policies.models import Policy
        from apps.reports.exporters import PolicyExporter
        
        queryset = Policy.objects.select_related(
            'client', 'insurer', 'branch', 'insurance_type'
        ).all()
        exporter = PolicyExporter(queryset, [])
        response = exporter.export()
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        self.assertIn('policies_', response['Content-Disposition'])


class PaymentExporterTest(TestCase):
    """Тесты PaymentExporter"""
    
    def setUp(self):
        """Подготовка тестовых данных"""
        from apps.clients.models import Client
        from apps.insurers.models import Insurer, Branch, InsuranceType, CommissionRate
        from apps.policies.models import Policy, PaymentSchedule
        from datetime import date
        from decimal import Decimal
        
        # Создаем клиента
        self.client = Client.objects.create(
            client_name='Тестовый клиент',
            client_inn='1234567890'
        )
        
        # Создаем страховщика
        self.insurer = Insurer.objects.create(
            insurer_name='Тестовый страховщик'
        )
        
        # Создаем филиал
        self.branch = Branch.objects.create(
            branch_name='Главный офис'
        )
        
        # Создаем вид страхования
        self.insurance_type = InsuranceType.objects.create(
            name='КАСКО'
        )
        
        # Создаем ставку комиссии
        self.commission_rate = CommissionRate.objects.create(
            insurer=self.insurer,
            insurance_type=self.insurance_type,
            kv_percent=Decimal('15.00')
        )
        
        # Создаем полис
        self.policy = Policy.objects.create(
            policy_number='TEST-001',
            dfa_number='DFA-001',
            client=self.client,
            insurer=self.insurer,
            branch=self.branch,
            insurance_type=self.insurance_type,
            property_description='Тестовое имущество',
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            policy_active=True
        )
        
        # Создаем платеж (дата в будущем, чтобы не был просрочен)
        from datetime import timedelta
        from django.utils import timezone
        future_date = timezone.now().date() + timedelta(days=30)
        
        self.payment = PaymentSchedule.objects.create(
            policy=self.policy,
            year_number=1,
            installment_number=1,
            due_date=future_date,
            amount=Decimal('50000.00'),
            insurance_sum=Decimal('1000000.00'),
            commission_rate=self.commission_rate,
            kv_rub=Decimal('7500.00')
        )
    
    def test_payment_exporter_get_headers(self):
        """Тест получения заголовков PaymentExporter"""
        from apps.policies.models import PaymentSchedule
        from apps.reports.exporters import PaymentExporter
        
        queryset = PaymentSchedule.objects.all()
        exporter = PaymentExporter(queryset, [])
        headers = exporter.get_headers()
        
        self.assertEqual(len(headers), 12)
        self.assertIn('Номер полиса', headers)
        self.assertIn('Клиент', headers)
        self.assertIn('Статус', headers)
    
    def test_payment_exporter_get_row_data(self):
        """Тест получения данных строки для платежа"""
        from apps.reports.exporters import PaymentExporter
        
        exporter = PaymentExporter([], [])
        row = exporter.get_row_data(self.payment)
        
        self.assertEqual(len(row), 12)
        self.assertEqual(row[0], 'TEST-001')  # policy_number
        self.assertEqual(row[1], 'Тестовый клиент')  # client
        self.assertEqual(row[2], 1)  # year_number
        self.assertEqual(row[3], 1)  # installment_number
        # Не проверяем точную дату, так как она динамическая
        self.assertEqual(row[11], 'Ожидается')  # status
    
    def test_payment_exporter_status_paid(self):
        """Тест статуса 'Оплачен'"""
        from apps.reports.exporters import PaymentExporter
        from datetime import date
        
        self.payment.paid_date = date(2024, 2, 1)
        self.payment.save()
        
        exporter = PaymentExporter([], [])
        row = exporter.get_row_data(self.payment)
        
        self.assertEqual(row[11], 'Оплачен')
    
    def test_payment_exporter_status_cancelled(self):
        """Тест статуса 'Отменен'"""
        from apps.reports.exporters import PaymentExporter
        from datetime import date
        
        # Делаем полис неактивным и устанавливаем дату расторжения
        self.policy.policy_active = False
        self.policy.termination_date = date(2024, 1, 15)
        self.policy.save()
        
        exporter = PaymentExporter([], [])
        row = exporter.get_row_data(self.payment)
        
        self.assertEqual(row[11], 'Отменен')
    
    def test_payment_exporter_filename(self):
        """Тест генерации имени файла"""
        from apps.policies.models import PaymentSchedule
        from apps.reports.exporters import PaymentExporter
        
        queryset = PaymentSchedule.objects.all()
        exporter = PaymentExporter(queryset, [])
        
        self.assertEqual(exporter.get_filename(), 'payments')
    
    def test_payment_exporter_export(self):
        """Тест полного экспорта платежей"""
        from apps.policies.models import PaymentSchedule
        from apps.reports.exporters import PaymentExporter
        
        queryset = PaymentSchedule.objects.select_related(
            'policy', 'policy__client', 'policy__insurer', 'commission_rate'
        ).all()
        exporter = PaymentExporter(queryset, [])
        response = exporter.export()
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        self.assertIn('payments_', response['Content-Disposition'])
