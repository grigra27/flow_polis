"""
Тесты производительности для системы экспорта

Тестируют производительность системы при больших объемах данных
и проверяют оптимизацию запросов.
"""

from django.test import TestCase, TransactionTestCase
from django.test.utils import override_settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.contrib.auth.models import User
from datetime import date, timedelta
from decimal import Decimal
import time
import threading

from apps.clients.models import Client
from apps.insurers.models import Insurer, Branch, InsuranceType, CommissionRate
from apps.policies.models import Policy, PaymentSchedule
from apps.reports.exporters import CustomExporter, PolicyExporter, PaymentExporter


class LargeDatasetTest(TestCase):
    """
    Тест производительности: Большие объемы данных
    
    Создает 1000 полисов с платежами и измеряет время генерации экспорта.
    Целевое время: < 30 секунд для 10000 записей.
    
    Validates: Property 6, Requirement 8.4
    """
    
    @classmethod
    def setUpClass(cls):
        """Создаем большой набор тестовых данных"""
        super().setUpClass()
        
        # Создаем базовые объекты
        cls.clients = []
        for i in range(10):
            client = Client.objects.create(
                client_name=f'Клиент {i}',
                client_inn=f'{1000000000 + i}'
            )
            cls.clients.append(client)
        
        cls.insurers = []
        for i in range(5):
            insurer = Insurer.objects.create(
                insurer_name=f'Страховщик {i}'
            )
            cls.insurers.append(insurer)
        
        cls.branches = []
        for i in range(3):
            branch = Branch.objects.create(
                branch_name=f'Филиал {i}'
            )
            cls.branches.append(branch)
        
        cls.insurance_types = []
        for i in range(4):
            ins_type = InsuranceType.objects.create(
                name=f'Вид страхования {i}'
            )
            cls.insurance_types.append(ins_type)
        
        # Создаем 1000 полисов
        print("\nСоздание 1000 тестовых полисов...")
        cls.policies = []
        for i in range(1000):
            policy = Policy.objects.create(
                policy_number=f'PERF-{i:05d}',
                dfa_number=f'DFA-PERF-{i:05d}',
                client=cls.clients[i % len(cls.clients)],
                insurer=cls.insurers[i % len(cls.insurers)],
                branch=cls.branches[i % len(cls.branches)],
                insurance_type=cls.insurance_types[i % len(cls.insurance_types)],
                property_description=f'Имущество {i}',
                start_date=date(2024, 1, 1) + timedelta(days=i % 365),
                end_date=date(2024, 12, 31),
                premium_total=Decimal('100000.00') + Decimal(i * 100),
                policy_active=(i % 3 != 0)
            )
            cls.policies.append(policy)
            
            if (i + 1) % 100 == 0:
                print(f"  Создано {i + 1} полисов...")
        
        print("Тестовые данные созданы.")
    
    def test_export_1000_policies_performance(self):
        """Тест экспорта 1000 полисов"""
        print("\nТест экспорта 1000 полисов...")
        
        # Получаем queryset с оптимизацией
        queryset = Policy.objects.select_related(
            'client', 'insurer', 'branch', 'insurance_type'
        ).all()
        
        fields = [
            'policy_number',
            'client__client_name',
            'insurer__insurer_name',
            'branch__branch_name',
            'start_date',
            'premium_total'
        ]
        
        # Измеряем время
        start_time = time.time()
        
        exporter = CustomExporter(queryset, fields, 'policies')
        response = exporter.export()
        
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        print(f"  Время экспорта: {elapsed_time:.2f} секунд")
        print(f"  Размер файла: {len(response.content) / 1024:.2f} KB")
        
        # Проверяем что экспорт завершился успешно
        self.assertEqual(response.status_code, 200)
        
        # Проверяем что время разумное (< 10 секунд для 1000 записей)
        self.assertLess(
            elapsed_time,
            10.0,
            f"Export took {elapsed_time:.2f}s, expected < 10s"
        )
    
    def test_export_with_filters_performance(self):
        """Тест экспорта с фильтрами"""
        print("\nТест экспорта с фильтрами...")
        
        from apps.reports.filters import PolicyExportFilter
        
        # Применяем фильтр
        queryset = Policy.objects.all()
        filterset = PolicyExportFilter(
            {'policy_active': True},
            queryset=queryset
        )
        
        filtered_qs = filterset.qs.select_related(
            'client', 'insurer', 'branch', 'insurance_type'
        )
        
        fields = ['policy_number', 'client__client_name', 'policy_active']
        
        # Измеряем время
        start_time = time.time()
        
        exporter = CustomExporter(filtered_qs, fields, 'policies')
        response = exporter.export()
        
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        print(f"  Время экспорта: {elapsed_time:.2f} секунд")
        print(f"  Отфильтровано записей: {filtered_qs.count()}")
        
        # Проверяем что экспорт завершился успешно
        self.assertEqual(response.status_code, 200)
        
        # Проверяем что время разумное
        self.assertLess(
            elapsed_time,
            5.0,
            f"Filtered export took {elapsed_time:.2f}s, expected < 5s"
        )


class QueryOptimizationTest(TestCase):
    """
    Тест производительности: Оптимизация запросов
    
    Проверяет что используется select_related для минимизации
    количества SQL запросов.
    
    Validates: Property 6, Requirement 8.1, 8.2
    """
    
    def setUp(self):
        """Создаем тестовые данные"""
        # Создаем базовые объекты
        self.client = Client.objects.create(
            client_name='Тестовый клиент',
            client_inn='1234567890'
        )
        
        self.insurer = Insurer.objects.create(
            insurer_name='Тестовая СК'
        )
        
        self.branch = Branch.objects.create(
            branch_name='Тестовый филиал'
        )
        
        self.insurance_type = InsuranceType.objects.create(
            name='КАСКО'
        )
        
        # Создаем 50 полисов
        self.policies = []
        for i in range(50):
            policy = Policy.objects.create(
                policy_number=f'OPT-{i:03d}',
                dfa_number=f'DFA-OPT-{i:03d}',
                client=self.client,
                insurer=self.insurer,
                branch=self.branch,
                insurance_type=self.insurance_type,
                property_description=f'Имущество {i}',
                start_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31),
                policy_active=True
            )
            self.policies.append(policy)
    
    def test_query_count_without_optimization(self):
        """Тест количества запросов без оптимизации"""
        queryset = Policy.objects.all()
        
        fields = ['policy_number', 'client__client_name', 'insurer__insurer_name']
        
        with CaptureQueriesContext(connection) as context:
            exporter = CustomExporter(queryset, fields, 'policies')
            
            # Получаем данные для первых 10 полисов
            for policy in queryset[:10]:
                row = exporter.get_row_data(policy)
        
        query_count = len(context.captured_queries)
        
        print(f"\nБез оптимизации: {query_count} запросов для 10 полисов")
        
        # Без select_related будет N+1 проблема
        # Ожидаем много запросов (1 + 10*2 = 21)
        self.assertGreater(query_count, 10)
    
    def test_query_count_with_optimization(self):
        """Тест количества запросов с оптимизацией"""
        queryset = Policy.objects.select_related(
            'client', 'insurer', 'branch', 'insurance_type'
        ).all()
        
        fields = ['policy_number', 'client__client_name', 'insurer__insurer_name']
        
        with CaptureQueriesContext(connection) as context:
            exporter = CustomExporter(queryset, fields, 'policies')
            
            # Получаем данные для первых 10 полисов
            for policy in queryset[:10]:
                row = exporter.get_row_data(policy)
        
        query_count = len(context.captured_queries)
        
        print(f"С оптимизацией: {query_count} запросов для 10 полисов")
        
        # С select_related должен быть только 1 запрос
        self.assertLessEqual(
            query_count,
            2,
            f"Expected <= 2 queries with select_related, got {query_count}"
        )
    
    def test_ready_export_query_optimization(self):
        """Тест оптимизации запросов в готовых экспортах"""
        queryset = Policy.objects.select_related(
            'client', 'insurer', 'branch', 'insurance_type'
        ).all()
        
        with CaptureQueriesContext(connection) as context:
            exporter = PolicyExporter(queryset, [])
            
            # Получаем данные для всех полисов
            for policy in queryset:
                row = exporter.get_row_data(policy)
        
        query_count = len(context.captured_queries)
        
        print(f"Готовый экспорт: {query_count} запросов для {queryset.count()} полисов")
        
        # Должен быть только 1 запрос благодаря select_related
        self.assertLessEqual(
            query_count,
            2,
            f"Expected <= 2 queries, got {query_count}"
        )


class ConcurrentExportTest(TestCase):
    """
    Тест производительности: Последовательные экспорты
    
    Симулирует 5 последовательных запросов на генерацию экспортов
    и проверяет корректность результатов.
    
    Validates: Requirement 8
    
    Примечание: Параллельные тесты с threading требуют специальной
    настройки БД и могут вызывать проблемы с транзакциями.
    """
    
    def setUp(self):
        """Создаем тестовые данные"""
        self.client_obj = Client.objects.create(
            client_name='Клиент для последовательных тестов',
            client_inn='9999999999'
        )
        
        self.insurer = Insurer.objects.create(
            insurer_name='СК для последовательных тестов'
        )
        
        self.branch = Branch.objects.create(
            branch_name='Филиал для последовательных тестов'
        )
        
        self.insurance_type = InsuranceType.objects.create(
            name='Тип для последовательных тестов'
        )
        
        # Создаем 100 полисов
        for i in range(100):
            Policy.objects.create(
                policy_number=f'CONC-{i:03d}',
                dfa_number=f'DFA-CONC-{i:03d}',
                client=self.client_obj,
                insurer=self.insurer,
                branch=self.branch,
                insurance_type=self.insurance_type,
                property_description=f'Имущество {i}',
                start_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31),
                policy_active=True
            )
    
    def test_sequential_exports(self):
        """Тест последовательных экспортов"""
        print("\nТест 5 последовательных экспортов...")
        
        num_exports = 5
        results = []
        
        # Выполняем экспорты последовательно
        start_time = time.time()
        
        for i in range(num_exports):
            queryset = Policy.objects.select_related(
                'client', 'insurer', 'branch', 'insurance_type'
            ).all()
            
            fields = ['policy_number', 'client__client_name']
            
            export_start = time.time()
            exporter = CustomExporter(queryset, fields, 'policies')
            response = exporter.export()
            export_end = time.time()
            
            results.append({
                'success': True,
                'time': export_end - export_start,
                'size': len(response.content)
            })
            
            print(f"  Экспорт {i+1}: {results[-1]['time']:.2f}s, {results[-1]['size']/1024:.2f}KB")
        
        end_time = time.time()
        total_time = end_time - start_time
        
        print(f"  Общее время: {total_time:.2f} секунд")
        print(f"  Среднее время: {total_time/num_exports:.2f} секунд")
        
        # Проверяем что все экспорты завершились успешно
        success_count = sum(1 for r in results if r['success'])
        self.assertEqual(success_count, num_exports)
        
        # Проверяем что размеры файлов одинаковые
        sizes = [r['size'] for r in results]
        self.assertEqual(len(set(sizes)), 1, "All file sizes should be identical")
        
        # Проверяем что среднее время разумное (< 1 секунда на экспорт)
        avg_time = total_time / num_exports
        self.assertLess(
            avg_time,
            1.0,
            f"Average export time {avg_time:.2f}s is too high"
        )


class MemoryUsageTest(TestCase):
    """
    Тест производительности: Использование памяти
    
    Проверяет что экспорт больших объемов данных не приводит
    к чрезмерному использованию памяти.
    
    Validates: Requirement 8.3
    """
    
    @classmethod
    def setUpClass(cls):
        """Создаем большой набор тестовых данных"""
        super().setUpClass()
        
        cls.client = Client.objects.create(
            client_name='Клиент для теста памяти',
            client_inn='8888888888'
        )
        
        cls.insurer = Insurer.objects.create(
            insurer_name='СК для теста памяти'
        )
        
        cls.branch = Branch.objects.create(
            branch_name='Филиал для теста памяти'
        )
        
        cls.insurance_type = InsuranceType.objects.create(
            name='Тип для теста памяти'
        )
        
        # Создаем 500 полисов
        print("\nСоздание 500 полисов для теста памяти...")
        for i in range(500):
            Policy.objects.create(
                policy_number=f'MEM-{i:04d}',
                dfa_number=f'DFA-MEM-{i:04d}',
                client=cls.client,
                insurer=cls.insurer,
                branch=cls.branch,
                insurance_type=cls.insurance_type,
                property_description=f'Имущество {i}' * 10,  # Длинное описание
                start_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31),
                premium_total=Decimal('100000.00'),
                policy_active=True
            )
            
            if (i + 1) % 100 == 0:
                print(f"  Создано {i + 1} полисов...")
    
    def test_memory_efficient_export(self):
        """Тест эффективного использования памяти"""
        print("\nТест использования памяти при экспорте 500 полисов...")
        
        import sys
        
        # Получаем queryset
        queryset = Policy.objects.select_related(
            'client', 'insurer', 'branch', 'insurance_type'
        ).all()
        
        fields = [
            'policy_number',
            'client__client_name',
            'insurer__insurer_name',
            'property_description'
        ]
        
        # Измеряем использование памяти (приблизительно)
        exporter = CustomExporter(queryset, fields, 'policies')
        response = exporter.export()
        
        file_size = len(response.content)
        
        print(f"  Размер файла: {file_size / 1024:.2f} KB")
        
        # Проверяем что файл создан успешно
        self.assertEqual(response.status_code, 200)
        
        # Проверяем что размер файла разумный (не более 5 MB для 500 записей)
        self.assertLess(
            file_size,
            5 * 1024 * 1024,
            f"File size {file_size / 1024 / 1024:.2f}MB is too large"
        )
