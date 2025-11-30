#!/usr/bin/env python
"""
Скрипт проверки готовности к продакшену
"""
import os
import sys


def check_production_readiness():
    """Проверяет готовность проекта к деплою на продакшен"""

    issues = []
    warnings = []

    print("=" * 60)
    print("ПРОВЕРКА ГОТОВНОСТИ К ПРОДАКШЕНУ")
    print("=" * 60)
    print()

    # 1. Проверка requirements
    print("1. Проверка зависимостей...")
    try:
        import psycopg2

        print("   ✓ psycopg2 установлен (PostgreSQL)")
    except ImportError:
        issues.append("psycopg2 не установлен - PostgreSQL не будет работать")

    # Шифрование отключено по решению разработчика
    # try:
    #     import django_cryptography
    #     print("   ✓ django-cryptography установлен (шифрование)")
    # except ImportError:
    #     issues.append("django-cryptography не установлен - шифрование не будет работать")

    try:
        import gunicorn

        print("   ✓ gunicorn установлен (production сервер)")
    except ImportError:
        issues.append("gunicorn не установлен")

    # 2. Проверка миграций
    print("\n2. Проверка миграций...")
    os.system("python manage.py makemigrations --check --dry-run > /dev/null 2>&1")
    if (
        os.system("python manage.py makemigrations --check --dry-run > /dev/null 2>&1")
        == 0
    ):
        print("   ✓ Нет неприменённых изменений моделей")
    else:
        warnings.append("Есть неприменённые изменения моделей")

    # 3. Проверка .env.prod.example
    print("\n3. Проверка конфигурации...")
    if os.path.exists(".env.prod.example"):
        with open(".env.prod.example", "r") as f:
            content = f.read()
            required_vars = [
                "SECRET_KEY",
                "DEBUG",
                "ALLOWED_HOSTS",
                "DB_NAME",
                "DB_USER",
                "DB_PASSWORD",
                "DB_HOST",
                "DB_PORT",
            ]

            missing = []
            for var in required_vars:
                if var not in content:
                    missing.append(var)

            # Шифрование отключено по решению разработчика
            # if 'FIELD_ENCRYPTION_KEY' not in content:
            #     issues.append("FIELD_ENCRYPTION_KEY отсутствует в .env.prod.example")
            # else:
            #     print("   ✓ FIELD_ENCRYPTION_KEY есть в примере")

            if missing:
                issues.append(
                    f"Отсутствуют переменные в .env.prod.example: {', '.join(missing)}"
                )
            else:
                print("   ✓ Все обязательные переменные есть в .env.prod.example")
    else:
        issues.append(".env.prod.example не найден")

    # 4. Проверка Docker конфигурации
    print("\n4. Проверка Docker...")
    if os.path.exists("docker-compose.prod.yml"):
        print("   ✓ docker-compose.prod.yml существует")
    else:
        issues.append("docker-compose.prod.yml не найден")

    if os.path.exists("Dockerfile"):
        print("   ✓ Dockerfile существует")
    else:
        issues.append("Dockerfile не найден")

    if os.path.exists("entrypoint.sh"):
        print("   ✓ entrypoint.sh существует")
    else:
        issues.append("entrypoint.sh не найден")

    # 5. Проверка Nginx
    print("\n5. Проверка Nginx...")
    if os.path.exists("nginx/default.conf"):
        print("   ✓ nginx/default.conf существует")
    else:
        issues.append("nginx/default.conf не найден")

    # 6. Проверка скриптов
    print("\n6. Проверка скриптов деплоя...")
    if os.path.exists("scripts/init-letsencrypt.sh"):
        print("   ✓ init-letsencrypt.sh существует")
    else:
        warnings.append("init-letsencrypt.sh не найден")

    # Итоги
    print("\n" + "=" * 60)
    print("РЕЗУЛЬТАТЫ")
    print("=" * 60)

    if not issues and not warnings:
        print("\n✅ ВСЁ ОТЛИЧНО! Проект готов к деплою на продакшен")
        print("\nСледующие шаги:")
        print("1. Создайте .env.prod с реальными значениями")
        print("2. Запустите на сервере:")
        print("   docker-compose -f docker-compose.prod.yml up -d")
        return 0

    if issues:
        print("\n❌ КРИТИЧЕСКИЕ ПРОБЛЕМЫ:")
        for issue in issues:
            print(f"   • {issue}")

    if warnings:
        print("\n⚠️  ПРЕДУПРЕЖДЕНИЯ:")
        for warning in warnings:
            print(f"   • {warning}")

    print("\n" + "=" * 60)

    if issues:
        print("\n⛔ ДЕПЛОЙ НА ПРОДАКШЕН НЕВОЗМОЖЕН БЕЗ ИСПРАВЛЕНИЯ КРИТИЧЕСКИХ ПРОБЛЕМ")
        return 1
    else:
        print("\n⚠️  ДЕПЛОЙ ВОЗМОЖЕН, НО РЕКОМЕНДУЕТСЯ ИСПРАВИТЬ ПРЕДУПРЕЖДЕНИЯ")
        return 0


if __name__ == "__main__":
    sys.exit(check_production_readiness())
