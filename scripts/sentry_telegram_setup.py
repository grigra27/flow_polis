#!/usr/bin/env python
"""
Скрипт для настройки Telegram уведомлений в Sentry через webhook.

Использование:
    python scripts/sentry_telegram_setup.py

Этот скрипт поможет настроить Telegram бота для получения уведомлений
о ошибках из Sentry.
"""

import requests
import json


def create_telegram_bot():
    """Инструкции по созданию Telegram бота"""
    print("📱 Настройка Telegram бота для Sentry уведомлений")
    print("=" * 60)

    print("\n1️⃣ Создайте Telegram бота:")
    print("   • Напишите @BotFather в Telegram")
    print("   • Отправьте команду: /newbot")
    print("   • Следуйте инструкциям и выберите имя бота")
    print("   • Сохраните полученный TOKEN")

    print("\n2️⃣ Получите Chat ID:")
    print("   • Напишите вашему боту любое сообщение")
    print("   • Откройте в браузере:")
    print("     https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates")
    print("   • Найдите 'chat':{'id':123456789} - это ваш Chat ID")

    return input("\n📝 Введите TOKEN бота: ").strip()


def get_chat_id(bot_token):
    """Получает Chat ID из Telegram API"""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        response = requests.get(url)
        data = response.json()

        if data.get("ok") and data.get("result"):
            for update in data["result"]:
                if "message" in update and "chat" in update["message"]:
                    chat_id = update["message"]["chat"]["id"]
                    print(f"✅ Найден Chat ID: {chat_id}")
                    return str(chat_id)

        print("❌ Chat ID не найден. Убедитесь, что вы отправили сообщение боту.")
        return input("📝 Введите Chat ID вручную: ").strip()

    except Exception as e:
        print(f"❌ Ошибка при получении Chat ID: {e}")
        return input("📝 Введите Chat ID вручную: ").strip()


def test_telegram_message(bot_token, chat_id):
    """Тестирует отправку сообщения в Telegram"""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        payload = {
            "chat_id": chat_id,
            "text": "🧪 Тест интеграции Sentry с Telegram\n\nЕсли вы видите это сообщение, интеграция работает!",
            "parse_mode": "Markdown",
        }

        response = requests.post(url, json=payload)

        if response.status_code == 200:
            print("✅ Тестовое сообщение отправлено успешно!")
            return True
        else:
            print(f"❌ Ошибка отправки: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        print(f"❌ Ошибка при тестировании: {e}")
        return False


def generate_sentry_webhook_config(bot_token, chat_id):
    """Генерирует конфигурацию для Sentry webhook"""

    webhook_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload_template = {
        "chat_id": chat_id,
        "text": """🚨 *Ошибка в системе полисов!*

*Проект:* {{project}}
*Ошибка:* {{title}}
*Уровень:* {{level}}
*Окружение:* {{environment}}
*Время:* {{timestamp}}

*Детали:*
{{culprit}}

[🔍 Подробнее в Sentry]({{web_url}})""",
        "parse_mode": "Markdown",
    }

    print("\n" + "=" * 60)
    print("📋 Конфигурация для Sentry Webhook")
    print("=" * 60)

    print(f"\n🔗 Webhook URL:")
    print(f"   {webhook_url}")

    print(f"\n📄 Payload Template (JSON):")
    print(json.dumps(payload_template, indent=2, ensure_ascii=False))

    print(f"\n📝 Инструкция по настройке в Sentry:")
    print("   1. Перейдите в ваш проект в Sentry")
    print("   2. Settings → Integrations → Webhooks")
    print("   3. Нажмите 'Add Webhook'")
    print("   4. Вставьте URL выше")
    print("   5. Вставьте Payload Template выше")
    print("   6. Сохраните")

    # Сохраняем в файл
    config = {
        "webhook_url": webhook_url,
        "payload_template": payload_template,
        "setup_instructions": [
            "1. Откройте Sentry Dashboard",
            "2. Перейдите в Settings → Integrations → Webhooks",
            "3. Нажмите 'Add Webhook'",
            "4. URL: " + webhook_url,
            "5. Payload: скопируйте JSON выше",
            "6. Сохраните и протестируйте",
        ],
    }

    with open("sentry_telegram_config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Конфигурация сохранена в файл: sentry_telegram_config.json")


def main():
    """Основная функция"""
    print("🤖 Настройка Telegram уведомлений для Sentry")
    print("=" * 60)

    # Получаем токен бота
    bot_token = create_telegram_bot()

    if not bot_token:
        print("❌ Токен бота не указан. Выход.")
        return

    # Получаем Chat ID
    print(f"\n🔍 Получение Chat ID...")
    chat_id = get_chat_id(bot_token)

    if not chat_id:
        print("❌ Chat ID не получен. Выход.")
        return

    # Тестируем отправку
    print(f"\n🧪 Тестирование отправки сообщения...")
    if test_telegram_message(bot_token, chat_id):
        # Генерируем конфигурацию
        generate_sentry_webhook_config(bot_token, chat_id)

        print(f"\n🎉 Настройка завершена!")
        print(f"   Bot Token: {bot_token}")
        print(f"   Chat ID: {chat_id}")
        print(f"\n📱 Теперь настройте webhook в Sentry используя данные выше")

    else:
        print(f"\n❌ Тестирование не прошло. Проверьте токен и Chat ID.")


if __name__ == "__main__":
    main()
