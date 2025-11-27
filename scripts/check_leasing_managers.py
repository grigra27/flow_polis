#!/usr/bin/env python
"""
Скрипт для проверки и вывода статистики по менеджерам лизинговой компании.

Использование:
    python manage.py shell < scripts/check_leasing_managers.py
    или
    python scripts/check_leasing_managers.py (если настроен Django)
"""

import os
import sys
import django

# Настройка Django (если запускается напрямую)
if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

from apps.insurers.models import LeasingManager
from apps.policies.models import Policy
from django.db.models import Count


def print_separator(char='=', length=60):
    """Печать разделителя"""
    print(char * length)


def main():
    """Основная функция"""
    print_separator()
    print("СТАТИСТИКА ПО МЕНЕДЖЕРАМ ЛИЗИНГОВОЙ КОМПАНИИ")
    print_separator()
    print()
    
    # Общая статистика
    total_managers = LeasingManager.objects.count()
    total_policies = Policy.objects.count()
    policies_with_manager = Policy.objects.filter(leasing_manager__isnull=False).count()
    
    print(f"📊 Общая статистика:")
    print(f"   Всего менеджеров: {total_managers}")
    print(f"   Всего полисов: {total_policies}")
    print(f"   Полисов с менеджером: {policies_with_manager}")
    print(f"   Полисов без менеджера: {total_policies - policies_with_manager}")
    print()
    
    # Статистика по каждому менеджеру
    print_separator('-')
    print("📋 Распределение полисов по менеджерам:")
    print_separator('-')
    print()
    
    managers_stats = LeasingManager.objects.annotate(
        policies_count=Count('policies')
    ).order_by('-policies_count')
    
    if managers_stats.exists():
        for i, manager in enumerate(managers_stats, 1):
            print(f"{i}. {manager.name}")
            print(f"   Полисов: {manager.policies_count}")
            
            if manager.phone:
                print(f"   Телефон: {manager.phone}")
            if manager.email:
                print(f"   Email: {manager.email}")
            
            # Показываем первые 3 полиса
            if manager.policies_count > 0:
                print(f"   Примеры полисов:")
                for policy in manager.policies.all()[:3]:
                    print(f"      • {policy.policy_number} ({policy.client})")
                
                if manager.policies_count > 3:
                    print(f"      ... и ещё {manager.policies_count - 3}")
            
            print()
    else:
        print("   Менеджеры не найдены")
        print()
    
    # Проверка целостности данных
    print_separator('-')
    print("✅ Проверка целостности данных:")
    print_separator('-')
    print()
    
    # Проверяем, есть ли полисы без менеджера
    policies_without_manager = Policy.objects.filter(leasing_manager__isnull=True)
    if policies_without_manager.exists():
        print(f"⚠️  Найдено {policies_without_manager.count()} полисов без менеджера:")
        for policy in policies_without_manager[:5]:
            print(f"   • {policy.policy_number}")
        if policies_without_manager.count() > 5:
            print(f"   ... и ещё {policies_without_manager.count() - 5}")
    else:
        print("✓ Все полисы имеют назначенного менеджера")
    
    print()
    
    # Проверяем менеджеров без полисов
    managers_without_policies = LeasingManager.objects.annotate(
        policies_count=Count('policies')
    ).filter(policies_count=0)
    
    if managers_without_policies.exists():
        print(f"ℹ️  Найдено {managers_without_policies.count()} менеджеров без полисов:")
        for manager in managers_without_policies:
            print(f"   • {manager.name}")
    else:
        print("✓ У всех менеджеров есть полисы")
    
    print()
    print_separator()
    print("Проверка завершена!")
    print_separator()


if __name__ == '__main__':
    main()
