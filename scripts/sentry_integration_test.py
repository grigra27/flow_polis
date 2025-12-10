#!/usr/bin/env python
"""
Скрипт для тестирования интеграции с Sentry.
Создает тестовые ошибки для проверки работы мониторинга.

Использование:
    python scripts/sentry_integration_test.py

Примечание: Используйте только для проверки настройки Sentry.
"""

import os
import sys
import django

# Настройка Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def test_sentry_integration():
    """Тестирует интеграцию с Sentry"""

    print("🔍 Проверка настроек Sentry...")

    # Проверяем, настроен ли Sentry
    sentry_dsn = getattr(settings, "SENTRY_DSN", None) or os.environ.get("SENTRY_DSN")

    if not sentry_dsn:
        print("❌ SENTRY_DSN не настроен")
        print("   Добавьте SENTRY_DSN в .env файл")
        return False

    print(f"✅ SENTRY_DSN настроен: {sentry_dsn[:50]}...")

    # Проверяем, инициализирован ли Sentry
    try:
        import sentry_sdk

        client = sentry_sdk.Hub.current.client

        if not client:
            print("❌ Sentry SDK не инициализирован")
            return False

        print("✅ Sentry SDK инициализирован")
        print(f"   Environment: {client.options.get('environment', 'unknown')}")
        print(f"   Release: {client.options.get('release', 'unknown')}")

    except ImportError:
        print("❌ Sentry SDK не установлен")
        print("   Выполните: pip install sentry-sdk[django]")
        return False

    return True


def send_test_errors():
    """Отправляет тестовые ошибки в Sentry"""

    print("\n🧪 Отправка тестовых ошибок...")

    # 1. Простая ошибка
    try:
        print("1️⃣ Тестируем простую ошибку...")
        result = 1 / 0
    except ZeroDivisionError as e:
        logger.error("Тестовая ошибка деления на ноль", exc_info=True)
        print("   ✅ ZeroDivisionError отправлена")

    # 2. Ошибка с контекстом
    try:
        print("2️⃣ Тестируем ошибку с контекстом...")
        import sentry_sdk

        with sentry_sdk.configure_scope() as scope:
            scope.set_tag("test_type", "integration_test")
            scope.set_context(
                "test_data",
                {
                    "policy_id": 12345,
                    "user_action": "create_policy",
                    "error_source": "test_script",
                },
            )

            raise ValueError("Тестовая ошибка с контекстом для проверки Sentry")

    except ValueError as e:
        logger.error("Тестовая ошибка с контекстом", exc_info=True)
        print("   ✅ ValueError с контекстом отправлена")

    # 3. Предупреждение
    print("3️⃣ Тестируем предупреждение...")
    logger.warning(
        "Тестовое предупреждение для проверки Sentry",
        extra={"test_type": "warning_test", "component": "sentry_integration"},
    )
    print("   ✅ Warning отправлено")

    # 4. Информационное сообщение
    print("4️⃣ Тестируем информационное сообщение...")
    logger.info(
        "Тестовое информационное сообщение",
        extra={"test_type": "info_test", "status": "success"},
    )
    print("   ✅ Info сообщение отправлено")


def test_database_error():
    """Тестирует ошибку базы данных"""

    print("\n💾 Тестируем ошибку базы данных...")

    try:
        from django.db import connection

        with connection.cursor() as cursor:
            # Выполняем заведомо неправильный SQL
            cursor.execute("SELECT * FROM non_existent_table")

    except Exception as e:
        logger.error("Тестовая ошибка базы данных", exc_info=True)
        print("   ✅ Database error отправлена")


def test_policy_related_error():
    """Тестирует ошибку, связанную с полисами"""

    print("\n📋 Тестируем ошибку полисов...")

    try:
        from apps.policies.models import Policy

        # Пытаемся получить несуществующий полис
        policy = Policy.objects.get(id=999999)

    except Policy.DoesNotExist as e:
        logger.error(
            "Тестовая ошибка: полис не найден",
            extra={"policy_id": 999999, "error_type": "policy_not_found", "test": True},
            exc_info=True,
        )
        print("   ✅ Policy DoesNotExist отправлена")

    # Тестируем ошибку валидации
    try:
        from apps.policies.models import PaymentSchedule
        from decimal import Decimal

        # Создаем платеж с некорректными данными
        payment = PaymentSchedule(
            year_number=0,  # Некорректное значение
            installment_number=0,  # Некорректное значение
            amount=Decimal("-100"),  # Отрицательная сумма
        )
        payment.full_clean()

    except Exception as e:
        logger.error(
            "Тестовая ошибка валидации платежа",
            extra={
                "error_type": "validation_error",
                "model": "PaymentSchedule",
                "test": True,
            },
            exc_info=True,
        )
        print("   ✅ Validation error отправлена")


def main():
    """Основная функция"""

    print("🚀 Тестирование интеграции с Sentry")
    print("=" * 50)

    # Проверяем настройки
    if not test_sentry_integration():
        print("\n❌ Тестирование прервано из-за проблем с настройками")
        return

    # Отправляем тестовые ошибки
    send_test_errors()
    test_database_error()
    test_policy_related_error()

    print("\n" + "=" * 50)
    print("✅ Тестирование завершено!")
    print("\n📱 Проверьте уведомления:")
    print("   • Sentry Dashboard: https://sentry.io/")
    print("   • Email (если настроен)")
    print("   • Telegram (если настроен)")
    print("   • Slack (если настроен)")

    print("\n💡 Что делать дальше:")
    print("   1. Проверьте, что ошибки появились в Sentry")
    print("   2. Настройте правила уведомлений")
    print("   3. Добавьте интеграции (Telegram, Slack)")
    print("   4. Удалите тестовые ошибки из Sentry (если нужно)")


if __name__ == "__main__":
    main()
