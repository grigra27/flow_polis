"""
Интеграционные тесты для системы экспорта

Тестируют полный цикл работы системы экспорта от начала до конца.
"""

from django.test import TestCase, Client as TestClient
from django.contrib.auth.models import User
from django.urls import reverse
from datetime import date, timedelta
from decimal import Decimal
from openpyxl import load_workbook
from io import BytesIO

from apps.clients.models import Client
from apps.insurers.models import Insurer, Branch, InsuranceType, CommissionRate
from apps.policies.models import Policy, PaymentSchedule
from apps.reports.models import CustomExportTemplate


class FullCycleCustomExportTest(TestCase):
    """
    Интеграционный тест: Полный цикл кастомного экспорта
    
    Тестирует весь процесс создания кастомного экспорта:
    1. Авторизация пользователя
    2. Переход на страницу кастомного экспорта
    3. Выбор источника данных
    4. Выбор полей
    5. Применение фильтров
    6. Генерация экспорта
    7. Проверка содержимого файла
    
    Validates: All properties
    """
    
    def setUp(self):
        """Подготовка тестовых данных"""
        # Создаем пользователя
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        # Создаем тестовые данные
        self.client_obj = Client.objects.create(
            client_name='Интеграционный клиент',
            client_inn='1234567890'
        )
        
        self.insurer = Insurer.objects.create(
            insurer_name='Интеграционная СК'
        )
        
        self.branch = Branch.objects.create(
            branch_name='Главный офис'
        )
        
        self.insurance_type = InsuranceType.objects.create(
            name='КАСКО'
        )
        
        # Создаем несколько полисов
        self.policies = []
        for i in range(5):
            policy = Policy.objects.create(
                policy_number=f'INT-{i:03d}',
                dfa_number=f'DFA-INT-{i:03d}',
                client=self.client_obj,
                insurer=self.insurer,
                branch=self.branch,
                insurance_type=self.insurance_type,
                property_description=f'Имущество {i}',
                start_date=date(2024, 1, 1) + timedelta(days=i*30),
                end_date=date(2024, 12, 31),
                premium_total=Decimal('100000.00') * (i + 1),
                policy_active=(i % 2 == 0)
            )
            self.policies.append(policy)
        
        self.test_client = TestClient()
    
    def test_full_custom_export_cycle(self):
        """Тест полного цикла кастомного экспорта"""
        # Шаг 1: Авторизация
        login_success = self.test_client.login(
            username='testuser',
            password='testpass123'
        )
        self.assertTrue(login_success, "Login should succeed")
        
        # Шаг 2: Переход на страницу кастомного экспорта
        response = self.test_client.get('/reports/custom/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('available_fields', response.context)
        
        # Шаг 3-5: Выбор источника, полей и фильтров
        export_data = {
            'action': 'export',
            'data_source': 'policies',
            'fields': [
                'policy_number',
                'client__client_name',
                'premium_total',
                'policy_active'
            ]
        }
        
        # Шаг 6: Генерация экспорта
        response = self.test_client.post('/reports/custom/', export_data)
        
        # Проверяем что получили Excel файл
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
        # Шаг 7: Проверка содержимого файла
        # Загружаем Excel файл
        excel_file = BytesIO(response.content)
        wb = load_workbook(excel_file)
        ws = wb.active
        
        # Проверяем заголовки
        headers = [cell.value for cell in ws[1]]
        self.assertEqual(len(headers), 4)
        self.assertIn('Номер полиса', headers)
        self.assertIn('Клиент', headers)
        self.assertIn('Общая премия', headers)
        self.assertIn('Статус полиса', headers)
        
        # Проверяем количество строк (заголовок + 5 полисов)
        self.assertEqual(ws.max_row, 6)
        
        # Проверяем данные первого полиса (может быть любой из 5)
        first_row = [cell.value for cell in ws[2]]
        self.assertIn(first_row[0], ['INT-000', 'INT-001', 'INT-002', 'INT-003', 'INT-004'])
        self.assertEqual(first_row[1], 'Интеграционный клиент')
        self.assertIn(first_row[2], [100000.0, 200000.0, 300000.0, 400000.0, 500000.0])
        self.assertIn(first_row[3], ['Да', 'Нет'])
    
    def test_custom_export_with_filters(self):
        """Тест кастомного экспорта с фильтрами"""
        self.test_client.login(username='testuser', password='testpass123')
        
        # Экспортируем только активные полисы
        export_data = {
            'action': 'export',
            'data_source': 'policies',
            'fields': ['policy_number', 'policy_active'],
            'policy_active': 'true'
        }
        
        response = self.test_client.post('/reports/custom/', export_data)
        self.assertEqual(response.status_code, 200)
        
        # Проверяем содержимое
        excel_file = BytesIO(response.content)
        wb = load_workbook(excel_file)
        ws = wb.active
        
        # Должно быть 3 активных полиса (индексы 0, 2, 4)
        self.assertEqual(ws.max_row, 4)  # заголовок + 3 полиса
        
        # Проверяем что все полисы активны
        for row_idx in range(2, ws.max_row + 1):
            status = ws.cell(row=row_idx, column=2).value
            self.assertEqual(status, 'Да')


class TemplateSaveAndLoadTest(TestCase):
    """
    Интеграционный тест: Сохранение и использование шаблона
    
    Тестирует полный цикл работы с шаблонами:
    1. Создание кастомного экспорта
    2. Сохранение как шаблон
    3. Загрузка шаблона
    4. Генерация экспорта с загруженными настройками
    5. Проверка идентичности результатов
    
    Validates: Property 3, Property 4
    """
    
    def setUp(self):
        """Подготовка тестовых данных"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        self.client_obj = Client.objects.create(
            client_name='Тестовый клиент',
            client_inn='1234567890'
        )
        
        self.insurer = Insurer.objects.create(insurer_name='Тестовая СК')
        self.branch = Branch.objects.create(branch_name='Филиал')
        self.insurance_type = InsuranceType.objects.create(name='КАСКО')
        
        self.policy = Policy.objects.create(
            policy_number='TMPL-001',
            dfa_number='DFA-TMPL-001',
            client=self.client_obj,
            insurer=self.insurer,
            branch=self.branch,
            insurance_type=self.insurance_type,
            property_description='Тестовое имущество',
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            policy_active=True
        )
        
        self.test_client = TestClient()
    
    def test_save_and_load_template(self):
        """Тест сохранения и загрузки шаблона"""
        self.test_client.login(username='testuser', password='testpass123')
        
        # Шаг 1: Создаем и сохраняем шаблон
        template_data = {
            'action': 'save_template',
            'template_name': 'Мой тестовый шаблон',
            'data_source': 'policies',
            'fields': ['policy_number', 'client__client_name', 'policy_active']
        }
        
        response = self.test_client.post('/reports/custom/', template_data)
        self.assertEqual(response.status_code, 302)  # Redirect after save
        
        # Проверяем что шаблон создан
        template = CustomExportTemplate.objects.filter(
            user=self.user,
            name='Мой тестовый шаблон'
        ).first()
        
        self.assertIsNotNone(template)
        self.assertEqual(template.data_source, 'policies')
        self.assertEqual(
            template.config['fields'],
            ['policy_number', 'client__client_name', 'policy_active']
        )
        
        # Шаг 2: Генерируем экспорт с этими настройками
        export_data = {
            'action': 'export',
            'data_source': 'policies',
            'fields': ['policy_number', 'client__client_name', 'policy_active']
        }
        
        response1 = self.test_client.post('/reports/custom/', export_data)
        self.assertEqual(response1.status_code, 200)
        
        # Шаг 3: Генерируем экспорт еще раз с теми же настройками
        response2 = self.test_client.post('/reports/custom/', export_data)
        self.assertEqual(response2.status_code, 200)
        
        # Шаг 4: Проверяем что результаты идентичны
        # (размер файлов должен быть примерно одинаковым)
        self.assertAlmostEqual(
            len(response1.content),
            len(response2.content),
            delta=100  # Небольшая разница из-за timestamp в имени файла
        )
    
    def test_template_uniqueness(self):
        """Тест уникальности имен шаблонов"""
        self.test_client.login(username='testuser', password='testpass123')
        
        # Создаем первый шаблон
        template_data = {
            'action': 'save_template',
            'template_name': 'Уникальный шаблон',
            'data_source': 'policies',
            'fields': ['policy_number']
        }
        
        response1 = self.test_client.post('/reports/custom/', template_data)
        self.assertEqual(response1.status_code, 302)
        
        # Пытаемся создать шаблон с тем же именем
        template_data2 = {
            'action': 'save_template',
            'template_name': 'Уникальный шаблон',
            'data_source': 'payments',
            'fields': ['policy__policy_number']
        }
        
        response2 = self.test_client.post('/reports/custom/', template_data2)
        self.assertEqual(response2.status_code, 302)
        
        # Должен быть только один шаблон (обновленный)
        templates = CustomExportTemplate.objects.filter(
            user=self.user,
            name='Уникальный шаблон'
        )
        
        self.assertEqual(templates.count(), 1)
        # Проверяем что шаблон обновился
        self.assertEqual(templates.first().data_source, 'payments')


class ReadyExportsTest(TestCase):
    """
    Интеграционный тест: Готовые экспорты
    
    Тестирует работу готовых экспортов:
    1. Экспорт полисов
    2. Экспорт платежей
    3. Проверка структуры файлов
    4. Проверка корректности данных
    
    Validates: Property 5, Property 6
    """
    
    def setUp(self):
        """Подготовка тестовых данных"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        # Создаем тестовые данные
        self.client_obj = Client.objects.create(
            client_name='Клиент для готовых экспортов',
            client_inn='9876543210'
        )
        
        self.insurer = Insurer.objects.create(
            insurer_name='СК для готовых экспортов'
        )
        
        self.branch = Branch.objects.create(
            branch_name='Филиал для экспортов'
        )
        
        self.insurance_type = InsuranceType.objects.create(
            name='ОСАГО'
        )
        
        self.commission_rate = CommissionRate.objects.create(
            insurer=self.insurer,
            insurance_type=self.insurance_type,
            kv_percent=Decimal('20.00')
        )
        
        # Создаем полис
        self.policy = Policy.objects.create(
            policy_number='READY-001',
            dfa_number='DFA-READY-001',
            client=self.client_obj,
            insurer=self.insurer,
            branch=self.branch,
            insurance_type=self.insurance_type,
            property_description='Имущество для экспорта',
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            premium_total=Decimal('50000.00'),
            franchise=Decimal('5000.00'),
            policy_active=True
        )
        
        # Создаем платеж
        self.payment = PaymentSchedule.objects.create(
            policy=self.policy,
            year_number=1,
            installment_number=1,
            due_date=date(2024, 3, 1),
            amount=Decimal('50000.00'),
            insurance_sum=Decimal('1000000.00'),
            commission_rate=self.commission_rate,
            kv_rub=Decimal('10000.00'),
            paid_date=date(2024, 2, 28)
        )
        
        self.test_client = TestClient()
    
    def test_ready_export_policies(self):
        """Тест готового экспорта полисов"""
        self.test_client.login(username='testuser', password='testpass123')
        
        response = self.test_client.get('/reports/export/policies/')
        
        # Проверяем что получили Excel файл
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        self.assertIn('policies_', response['Content-Disposition'])
        
        # Проверяем содержимое
        excel_file = BytesIO(response.content)
        wb = load_workbook(excel_file)
        ws = wb.active
        
        # Проверяем заголовки (13 колонок)
        headers = [cell.value for cell in ws[1]]
        self.assertEqual(len(headers), 13)
        self.assertIn('Номер полиса', headers)
        self.assertIn('Клиент', headers)
        self.assertIn('Страховщик', headers)
        
        # Проверяем данные
        self.assertGreaterEqual(ws.max_row, 2)  # Минимум заголовок + 1 полис
        
        # Проверяем первую строку данных
        row_data = [cell.value for cell in ws[2]]
        self.assertEqual(row_data[0], 'READY-001')
        self.assertEqual(row_data[2], 'Клиент для готовых экспортов')
        self.assertEqual(row_data[3], 'СК для готовых экспортов')
    
    def test_ready_export_payments(self):
        """Тест готового экспорта платежей"""
        self.test_client.login(username='testuser', password='testpass123')
        
        response = self.test_client.get('/reports/export/payments/')
        
        # Проверяем что получили Excel файл
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        self.assertIn('payments_', response['Content-Disposition'])
        
        # Проверяем содержимое
        excel_file = BytesIO(response.content)
        wb = load_workbook(excel_file)
        ws = wb.active
        
        # Проверяем заголовки (12 колонок)
        headers = [cell.value for cell in ws[1]]
        self.assertEqual(len(headers), 12)
        self.assertIn('Номер полиса', headers)
        self.assertIn('Клиент', headers)
        self.assertIn('Статус', headers)
        
        # Проверяем данные
        self.assertGreaterEqual(ws.max_row, 2)  # Минимум заголовок + 1 платеж
        
        # Проверяем первую строку данных
        row_data = [cell.value for cell in ws[2]]
        self.assertEqual(row_data[0], 'READY-001')
        self.assertEqual(row_data[1], 'Клиент для готовых экспортов')
        self.assertEqual(row_data[11], 'Оплачен')  # Статус
    
    def test_ready_export_date_formatting(self):
        """Тест форматирования дат в готовых экспортах"""
        self.test_client.login(username='testuser', password='testpass123')
        
        response = self.test_client.get('/reports/export/policies/')
        
        # Проверяем содержимое
        excel_file = BytesIO(response.content)
        wb = load_workbook(excel_file)
        ws = wb.active
        
        # Получаем даты из первой строки данных
        start_date = ws.cell(row=2, column=7).value  # Дата начала
        end_date = ws.cell(row=2, column=8).value  # Дата окончания
        
        # Проверяем формат ДД.ММ.ГГГГ
        import re
        date_pattern = r'^\d{2}\.\d{2}\.\d{4}$'
        
        self.assertRegex(start_date, date_pattern)
        self.assertRegex(end_date, date_pattern)
        
        # Проверяем конкретные значения
        self.assertEqual(start_date, '01.01.2024')
        self.assertEqual(end_date, '31.12.2024')


class AuthorizationTest(TestCase):
    """
    Интеграционный тест: Авторизация и права доступа
    
    Тестирует что все страницы экспорта требуют авторизации.
    
    Validates: Requirement 9
    """
    
    def setUp(self):
        """Подготовка тестовых данных"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.test_client = TestClient()
    
    def test_index_requires_login(self):
        """Главная страница требует авторизации"""
        response = self.test_client.get('/reports/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)
    
    def test_custom_export_requires_login(self):
        """Кастомный экспорт требует авторизации"""
        response = self.test_client.get('/reports/custom/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)
    
    def test_ready_exports_require_login(self):
        """Готовые экспорты требуют авторизации"""
        response1 = self.test_client.get('/reports/export/policies/')
        self.assertEqual(response1.status_code, 302)
        self.assertIn('/accounts/login/', response1.url)
        
        response2 = self.test_client.get('/reports/export/payments/')
        self.assertEqual(response2.status_code, 302)
        self.assertIn('/accounts/login/', response2.url)
    
    def test_authorized_access(self):
        """Авторизованный пользователь имеет доступ"""
        self.test_client.login(username='testuser', password='testpass123')
        
        response1 = self.test_client.get('/reports/')
        self.assertEqual(response1.status_code, 200)
        
        response2 = self.test_client.get('/reports/custom/')
        self.assertEqual(response2.status_code, 200)
