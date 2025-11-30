#!/bin/bash

# DNS Propagation Checker Script
# Проверяет распространение DNS записей для домена

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Функция для вывода с цветом
print_color() {
    local color=$1
    shift
    echo -e "${color}$@${NC}"
}

# Функция для вывода заголовка
print_header() {
    echo ""
    print_color "$BLUE" "=========================================="
    print_color "$BLUE" "$1"
    print_color "$BLUE" "=========================================="
    echo ""
}

# Функция для проверки наличия команды
check_command() {
    if ! command -v $1 &> /dev/null; then
        print_color "$RED" "Ошибка: команда '$1' не найдена"
        print_color "$YELLOW" "Установите $1 для продолжения"
        exit 1
    fi
}

# Проверка аргументов
if [ $# -lt 1 ]; then
    print_color "$RED" "Использование: $0 <domain> [expected_ip]"
    echo ""
    echo "Примеры:"
    echo "  $0 onbr.site"
    echo "  $0 onbr.site 123.45.67.89"
    exit 1
fi

DOMAIN=$1
EXPECTED_IP=${2:-"64.227.75.233"}

# Проверка необходимых команд
check_command dig
check_command curl

print_header "DNS Propagation Checker для $DOMAIN"

# Функция для проверки DNS записи
check_dns_record() {
    local hostname=$1
    local dns_server=$2
    local dns_name=$3

    if [ -n "$dns_server" ]; then
        result=$(dig @$dns_server $hostname +short 2>/dev/null | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -n1)
    else
        result=$(dig $hostname +short 2>/dev/null | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -n1)
    fi

    if [ -z "$result" ]; then
        print_color "$RED" "  ✗ $dns_name: Не найдено"
        return 1
    elif [ -n "$EXPECTED_IP" ] && [ "$result" != "$EXPECTED_IP" ]; then
        print_color "$YELLOW" "  ⚠ $dns_name: $result (ожидается $EXPECTED_IP)"
        return 2
    else
        print_color "$GREEN" "  ✓ $dns_name: $result"
        return 0
    fi
}

# Проверка корневого домена
print_header "Проверка корневого домена: $DOMAIN"

echo "Локальный DNS:"
check_dns_record "$DOMAIN" "" "Системный DNS"

echo ""
echo "Публичные DNS серверы:"
check_dns_record "$DOMAIN" "8.8.8.8" "Google DNS (8.8.8.8)"
check_dns_record "$DOMAIN" "8.8.4.4" "Google DNS (8.8.4.4)"
check_dns_record "$DOMAIN" "1.1.1.1" "Cloudflare DNS (1.1.1.1)"
check_dns_record "$DOMAIN" "1.0.0.1" "Cloudflare DNS (1.0.0.1)"
check_dns_record "$DOMAIN" "208.67.222.222" "OpenDNS (208.67.222.222)"
check_dns_record "$DOMAIN" "208.67.220.220" "OpenDNS (208.67.220.220)"

# Проверка www поддомена
print_header "Проверка www поддомена: www.$DOMAIN"

echo "Локальный DNS:"
check_dns_record "www.$DOMAIN" "" "Системный DNS"

echo ""
echo "Публичные DNS серверы:"
check_dns_record "www.$DOMAIN" "8.8.8.8" "Google DNS (8.8.8.8)"
check_dns_record "www.$DOMAIN" "1.1.1.1" "Cloudflare DNS (1.1.1.1)"
check_dns_record "www.$DOMAIN" "208.67.222.222" "OpenDNS (208.67.222.222)"

# Проверка NS записей
print_header "Проверка Nameservers"

ns_records=$(dig NS $DOMAIN +short 2>/dev/null)
if [ -z "$ns_records" ]; then
    print_color "$RED" "  ✗ NS записи не найдены"
else
    print_color "$GREEN" "  ✓ NS записи найдены:"
    echo "$ns_records" | while read ns; do
        echo "    - $ns"
    done
fi

# Проверка TTL
print_header "Проверка TTL (Time To Live)"

ttl=$(dig $DOMAIN +noall +answer | awk '{print $2}' | head -n1)
if [ -n "$ttl" ]; then
    print_color "$GREEN" "  ✓ TTL: $ttl секунд ($(($ttl / 60)) минут)"
    if [ $ttl -gt 3600 ]; then
        print_color "$YELLOW" "  ⚠ Высокий TTL - изменения DNS будут распространяться медленнее"
    fi
else
    print_color "$YELLOW" "  ⚠ TTL не определен"
fi

# Проверка HTTP доступности
print_header "Проверка HTTP доступности"

# Получаем IP адрес
current_ip=$(dig $DOMAIN +short 2>/dev/null | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -n1)

if [ -z "$current_ip" ]; then
    print_color "$RED" "  ✗ Невозможно определить IP адрес домена"
else
    echo "Проверка HTTP на $current_ip..."

    # Проверка HTTP
    if curl -s -I -m 5 http://$DOMAIN > /dev/null 2>&1; then
        http_status=$(curl -s -I -m 5 http://$DOMAIN | head -n1)
        print_color "$GREEN" "  ✓ HTTP доступен: $http_status"
    else
        print_color "$RED" "  ✗ HTTP недоступен"
    fi

    # Проверка HTTPS
    if curl -s -I -m 5 https://$DOMAIN > /dev/null 2>&1; then
        https_status=$(curl -s -I -m 5 https://$DOMAIN | head -n1)
        print_color "$GREEN" "  ✓ HTTPS доступен: $https_status"
    else
        print_color "$YELLOW" "  ⚠ HTTPS недоступен (возможно, SSL еще не настроен)"
    fi
fi

# Итоговая информация
print_header "Итоговая информация"

# Подсчет успешных проверок
total_checks=0
successful_checks=0

# Проверяем основные DNS серверы
for dns in "8.8.8.8" "1.1.1.1" "208.67.222.222"; do
    total_checks=$((total_checks + 2))  # Для корневого и www

    if dig @$dns $DOMAIN +short 2>/dev/null | grep -q -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
        successful_checks=$((successful_checks + 1))
    fi

    if dig @$dns www.$DOMAIN +short 2>/dev/null | grep -q -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
        successful_checks=$((successful_checks + 1))
    fi
done

propagation_percent=$((successful_checks * 100 / total_checks))

echo "Статус распространения DNS: $successful_checks/$total_checks проверок успешно ($propagation_percent%)"

if [ $propagation_percent -eq 100 ]; then
    print_color "$GREEN" "✓ DNS полностью распространился!"
    echo ""
    echo "Следующие шаги:"
    echo "  1. Получите SSL сертификат: ./scripts/init-letsencrypt.sh"
    echo "  2. Настройте HTTPS в Nginx"
    echo "  3. Протестируйте приложение: https://$DOMAIN"
elif [ $propagation_percent -ge 50 ]; then
    print_color "$YELLOW" "⚠ DNS частично распространился ($propagation_percent%)"
    echo ""
    echo "DNS записи распространяются. Подождите еще немного."
    echo "Обычно это занимает 15-60 минут."
else
    print_color "$RED" "✗ DNS еще не распространился ($propagation_percent%)"
    echo ""
    echo "Возможные причины:"
    echo "  1. DNS записи были только что созданы - подождите 15-60 минут"
    echo "  2. DNS записи настроены неправильно - проверьте настройки"
    echo "  3. Высокий TTL - изменения распространяются медленнее"
    echo ""
    echo "Проверьте настройки DNS:"
    if command -v doctl &> /dev/null; then
        echo "  doctl compute domain records list $DOMAIN"
    else
        echo "  Войдите в панель управления вашего DNS провайдера"
    fi
fi

# Онлайн инструменты для проверки
echo ""
print_color "$BLUE" "Онлайн инструменты для проверки распространения:"
echo "  • https://dnschecker.org/#A/$DOMAIN"
echo "  • https://www.whatsmydns.net/#A/$DOMAIN"
echo "  • https://dns.google/query?name=$DOMAIN&type=A"

echo ""
print_color "$BLUE" "Для повторной проверки запустите:"
echo "  $0 $DOMAIN${EXPECTED_IP:+ $EXPECTED_IP}"

echo ""
