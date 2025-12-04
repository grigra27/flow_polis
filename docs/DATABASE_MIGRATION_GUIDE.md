# Руководство по миграции базы данных между серверами

Это руководство описывает процесс миграции базы данных PostgreSQL с одного сервера на другой с использованием автоматизированных скриптов.

## Обзор

При миграции хостинга (например, с Digital Ocean на Timeweb Cloud) необходимо перенести все данные из старой базы данных в новую. Проект включает два скрипта для автоматизации этого процесса:

- **migrate-database.sh** - экспорт базы данных со старого сервера
- **import-database.sh** - импорт базы данных на новый сервер

## Требования

### На локальной машине
- SSH доступ к обоим серверам (старому и новому)
- Достаточно места на диске для хранения backup файла
- Утилиты: `ssh`, `scp`, `md5sum` или `md5`

### На старом сервере
- Docker и Docker Compose установлены
- База данных PostgreSQL запущена в контейнере
- SSH доступ настроен

### На новом сервере
- Docker и Docker Compose v1 установлены
- Файлы `.env.prod` и `.env.prod.db` созданы
- Структура директорий подготовлена
- SSH доступ настроен

## Процесс миграции

### Шаг 1: Экспорт базы данных со старого сервера

Скрипт `migrate-database.sh` выполняет следующие действия:

1. Проверяет SSH подключение к старому серверу
2. Проверяет статус контейнера базы данных
3. Собирает статистику о базе данных (количество таблиц, записей)
4. Создает SQL дамп базы данных
5. Проверяет целостность backup файла
6. Создает контрольную сумму (MD5) для проверки целостности

#### Использование

```bash
# Базовое использование (с параметрами по умолчанию)
./scripts/migrate-database.sh

# С пользовательскими параметрами
OLD_SERVER_IP=64.227.75.233 \
OLD_SERVER_USER=root \
BACKUP_DIR=./backups \
./scripts/migrate-database.sh
```

#### Параметры (переменные окружения)

| Переменная | Значение по умолчанию | Описание |
|------------|----------------------|----------|
| OLD_SERVER_IP | 64.227.75.233 | IP адрес старого сервера |
| OLD_SERVER_USER | root | Пользователь SSH на старом сервере |
| BACKUP_DIR | ./backups | Директория для сохранения backup файлов |

#### Что проверяет скрипт

- ✓ SSH подключение к старому серверу
- ✓ Статус контейнера базы данных (должен быть запущен)
- ✓ Количество таблиц в базе данных (должно быть > 0)
- ✓ Размер backup файла (должен быть > 1KB)
- ✓ Наличие SQL команд в backup файле (CREATE TABLE, COPY)
- ✓ Контрольная сумма для проверки целостности

#### Вывод скрипта

```
=== Database Migration Script - Export ===
Old Server: root@64.227.75.233
Backup Directory: ./backups
Backup File: insurance_broker_backup_20231204_120000.sql

[1/6] Checking SSH connection to old server...
✓ SSH connection successful

[2/6] Checking Docker Compose status on old server...
✓ Database container is running

[3/6] Gathering database statistics...
✓ Database contains 45 tables
  Checking key tables...
  - Django migrations: 87
  - Policies: 1234

[4/6] Creating database backup on old server...
This may take several minutes depending on database size...
✓ Database backup created successfully

[5/6] Verifying backup file integrity...
✓ Backup file size: 15 MB
✓ Backup file contains valid SQL commands
  - Tables in backup: 45

[6/6] Creating checksum for integrity verification...
✓ Checksum created: a1b2c3d4e5f6g7h8i9j0

=== Export Complete ===
Backup file: ./backups/insurance_broker_backup_20231204_120000.sql
Backup size: 15 MB
Tables exported: 45

Next steps:
1. Transfer the backup file to the new server:
   scp ./backups/insurance_broker_backup_20231204_120000.sql root@109.68.215.223:~/insurance_broker/

2. Run the import script on the new server:
   ./scripts/import-database.sh insurance_broker_backup_20231204_120000.sql

Important: Keep this backup file safe until migration is verified!
```

### Шаг 2: Передача backup файла на новый сервер

После успешного экспорта передайте backup файл на новый сервер:

```bash
# Используйте команду из вывода скрипта
scp ./backups/insurance_broker_backup_20231204_120000.sql root@109.68.215.223:~/insurance_broker/

# Также передайте файл контрольной суммы
scp ./backups/insurance_broker_backup_20231204_120000.sql.md5 root@109.68.215.223:~/insurance_broker/
```

### Шаг 3: Импорт базы данных на новый сервер

Скрипт `import-database.sh` выполняет следующие действия:

1. Проверяет контрольную сумму backup файла (если доступна)
2. Проверяет установку Docker Compose
3. Проверяет наличие конфигурационных файлов
4. Проверяет наличие файлов окружения
5. Запускает контейнер базы данных (если не запущен)
6. Создает backup текущей базы данных (если существует)
7. Импортирует данные из backup файла
8. Проверяет целостность импортированных данных
9. Запускает Django миграции

#### Использование

```bash
# На новом сервере
cd ~/insurance_broker
./scripts/import-database.sh insurance_broker_backup_20231204_120000.sql
```

#### Что проверяет скрипт

- ✓ Контрольная сумма backup файла (если доступна)
- ✓ Установка Docker Compose
- ✓ Наличие docker-compose.prod.yml
- ✓ Наличие .env.prod и .env.prod.db
- ✓ Статус контейнера базы данных
- ✓ Количество импортированных таблиц
- ✓ Наличие ключевых таблиц (auth_user, policies_policy, и т.д.)
- ✓ Успешное выполнение Django миграций

#### Вывод скрипта

```
=== Database Migration Script - Import ===

Backup file: insurance_broker_backup_20231204_120000.sql
Backup size: 15 MB

[1/9] Verifying backup file checksum...
✓ Checksum verification passed

[2/9] Checking Docker Compose installation...
✓ Docker Compose installed: docker-compose version 1.29.2

[3/9] Checking Docker Compose configuration...
✓ docker-compose.prod.yml found

[4/9] Checking environment files...
✓ Environment files found

[5/9] Checking database container status...
✓ Database container is running

[6/9] Creating backup of current database (if exists)...
⚠ Database does not exist yet, skipping backup

[7/9] Importing database backup...
This may take several minutes depending on database size...
Preparing database...
✓ Database import completed successfully

[8/9] Verifying imported data...
✓ Database contains 45 tables
  - Django migrations: 87
  Checking key tables...
  - auth_user: 5 rows
  - policies_policy: 1234 rows
  - clients_client: 567 rows
  - insurers_insurer: 12 rows

[9/9] Running Django migrations...
Starting web container to run migrations...
✓ Django migrations completed successfully

=== Import Complete ===
Database: insurance_broker_prod
Tables: 45
Migrations: 87

Next steps:
1. Start all containers:
   docker-compose -f docker-compose.prod.yml up -d

2. Verify the application is working:
   docker-compose -f docker-compose.prod.yml ps
   docker-compose -f docker-compose.prod.yml logs web

3. Test login and data access through the web interface

Database migration completed successfully!
```

## Проверка после миграции

После успешного импорта выполните следующие проверки:

### 1. Проверка контейнеров

```bash
docker-compose -f docker-compose.prod.yml ps
```

Все контейнеры должны быть в статусе "Up".

### 2. Проверка логов

```bash
# Логи веб-приложения
docker-compose -f docker-compose.prod.yml logs web

# Логи базы данных
docker-compose -f docker-compose.prod.yml logs db
```

Не должно быть критических ошибок.

### 3. Проверка данных в базе

```bash
# Подключиться к базе данных
docker-compose -f docker-compose.prod.yml exec db psql -U postgres -d insurance_broker_prod

# Проверить количество записей в ключевых таблицах
SELECT COUNT(*) FROM auth_user;
SELECT COUNT(*) FROM policies_policy;
SELECT COUNT(*) FROM clients_client;
SELECT COUNT(*) FROM insurers_insurer;

# Выйти
\q
```

### 4. Проверка через веб-интерфейс

1. Откройте приложение в браузере
2. Войдите с существующими учетными данными
3. Проверьте отображение данных полисов и клиентов
4. Попробуйте создать тестовую запись
5. Удалите тестовую запись

## Устранение проблем

### Ошибка: SSH connection failed

**Причина:** Неверные SSH credentials или сетевые проблемы

**Решение:**
```bash
# Проверьте SSH подключение вручную
ssh root@64.227.75.233

# Проверьте SSH ключи
ssh-add -l

# Добавьте ключ, если необходимо
ssh-add ~/.ssh/id_rsa
```

### Ошибка: Database container is not running

**Причина:** Контейнер базы данных не запущен

**Решение:**
```bash
# На сервере
cd ~/insurance_broker
docker-compose -f docker-compose.prod.yml up -d db

# Проверьте статус
docker-compose -f docker-compose.prod.yml ps db
```

### Ошибка: Checksum verification failed

**Причина:** Файл был поврежден при передаче

**Решение:**
```bash
# Удалите поврежденный файл
rm insurance_broker_backup_*.sql

# Повторите передачу файла
scp ./backups/insurance_broker_backup_*.sql root@109.68.215.223:~/insurance_broker/
```

### Ошибка: Environment files missing

**Причина:** Файлы .env.prod и .env.prod.db не созданы

**Решение:**
```bash
# Создайте файлы окружения на новом сервере
# См. документацию в MIGRATION_GUIDE.md или SERVER_SETUP.md
nano .env.prod
nano .env.prod.db
```

### Ошибка: Database import failed

**Причина:** Несовместимость версий PostgreSQL или поврежденный backup

**Решение:**
```bash
# Проверьте версию PostgreSQL на обоих серверах
docker-compose exec db psql --version

# Проверьте backup файл
head -n 20 insurance_broker_backup_*.sql
tail -n 20 insurance_broker_backup_*.sql

# Попробуйте импорт с подробным выводом
docker-compose -f docker-compose.prod.yml exec -T db psql -U postgres -d insurance_broker_prod < backup.sql
```

### Ошибка: No tables found in database

**Причина:** Импорт не выполнился или backup файл пустой

**Решение:**
```bash
# Проверьте размер backup файла
ls -lh insurance_broker_backup_*.sql

# Проверьте содержимое
grep -c "CREATE TABLE" insurance_broker_backup_*.sql

# Если файл пустой или маленький, повторите экспорт
./scripts/migrate-database.sh
```

### Ошибка: Django migrations failed

**Причина:** Несовместимость схемы или отсутствие миграций

**Решение:**
```bash
# Проверьте статус миграций
docker-compose -f docker-compose.prod.yml exec web python manage.py showmigrations

# Попробуйте применить миграции вручную
docker-compose -f docker-compose.prod.yml exec web python manage.py migrate --noinput

# Если есть конфликты, создайте новые миграции
docker-compose -f docker-compose.prod.yml exec web python manage.py makemigrations
docker-compose -f docker-compose.prod.yml exec web python manage.py migrate
```

## Безопасность

⚠️ **Важные рекомендации по безопасности:**

1. **Защита backup файлов**
   - Backup файлы содержат все данные приложения, включая пароли пользователей
   - Храните backup файлы в безопасном месте
   - Удалите backup файлы после успешной миграции
   - Не коммитьте backup файлы в Git

2. **SSH ключи**
   - Используйте отдельные SSH ключи для каждого сервера
   - Не используйте пароли для SSH доступа
   - Ограничьте доступ к приватным ключам (chmod 600)

3. **Передача данных**
   - Используйте SCP или RSYNC для безопасной передачи файлов
   - Рассмотрите шифрование больших backup файлов перед передачей
   - Проверяйте контрольные суммы после передачи

4. **Пароли базы данных**
   - Используйте разные пароли на старом и новом серверах
   - Генерируйте сильные пароли (минимум 20 символов)
   - Храните пароли в безопасном месте (password manager)

5. **Очистка**
   - Удалите backup файлы со старого сервера после миграции
   - Удалите backup файлы с локальной машины после проверки
   - Удалите временные файлы на новом сервере

## Рекомендации

### Перед миграцией

1. **Создайте несколько backup копий**
   ```bash
   # Запустите скрипт несколько раз
   ./scripts/migrate-database.sh
   ```

2. **Проверьте размер базы данных**
   ```bash
   ssh root@64.227.75.233 "docker-compose -f docker-compose.prod.yml exec -T db psql -U postgres -c \"SELECT pg_size_pretty(pg_database_size('insurance_broker_prod'));\""
   ```

3. **Убедитесь в наличии свободного места**
   ```bash
   # На локальной машине
   df -h

   # На новом сервере
   ssh root@109.68.215.223 "df -h"
   ```

### Во время миграции

1. **Включите режим обслуживания** (если возможно)
   - Предотвратите изменения данных во время экспорта
   - Уведомите пользователей о временной недоступности

2. **Мониторьте процесс**
   - Следите за выводом скриптов
   - Проверяйте логи на наличие ошибок
   - Сохраняйте вывод скриптов для отладки

3. **Не прерывайте процесс**
   - Дождитесь завершения экспорта/импорта
   - Не закрывайте терминал во время выполнения

### После миграции

1. **Сохраните backup файлы**
   - Храните backup файлы минимум 7 дней
   - Создайте дополнительные копии на внешних носителях

2. **Мониторьте новый сервер**
   - Проверяйте логи в течение первых 24 часов
   - Следите за производительностью
   - Проверяйте целостность данных

3. **Документируйте изменения**
   - Запишите дату и время миграции
   - Сохраните версии backup файлов
   - Обновите документацию проекта

## Автоматизация

Для регулярных миграций или backup'ов можно создать cron задачи:

### Автоматический backup каждый день в 2:00

```bash
# На старом сервере
crontab -e

# Добавьте строку:
0 2 * * * cd ~/insurance_broker && ./scripts/migrate-database.sh >> /var/log/db_backup.log 2>&1
```

### Автоматическая очистка старых backup'ов

```bash
# Удалять backup файлы старше 7 дней
find ./backups -name "insurance_broker_backup_*.sql" -mtime +7 -delete
```

## Дополнительные команды

### Проверка размера backup файла

```bash
ls -lh ./backups/insurance_broker_backup_*.sql
```

### Просмотр содержимого backup файла

```bash
# Первые 50 строк
head -n 50 ./backups/insurance_broker_backup_*.sql

# Последние 50 строк
tail -n 50 ./backups/insurance_broker_backup_*.sql

# Поиск конкретной таблицы
grep "CREATE TABLE policies_policy" ./backups/insurance_broker_backup_*.sql
```

### Сжатие backup файла

```bash
# Сжать backup файл
gzip ./backups/insurance_broker_backup_*.sql

# Распаковать
gunzip ./backups/insurance_broker_backup_*.sql.gz
```

### Передача со сжатием

```bash
# Сжать и передать одной командой
gzip -c ./backups/insurance_broker_backup_*.sql | ssh root@109.68.215.223 "gunzip > ~/insurance_broker/backup.sql"
```

## Связанная документация

- [MIGRATION_GUIDE.md](../MIGRATION_GUIDE.md) - Общее руководство по миграции хостинга
- [SERVER_SETUP.md](../SERVER_SETUP.md) - Настройка нового сервера
- [DATABASE_IMPORT_GUIDE.md](./DATABASE_IMPORT_GUIDE.md) - Импорт базы данных в локальное окружение
- [BACKUP_RESTORE.md](./BACKUP_RESTORE.md) - Резервное копирование и восстановление

## Поддержка

При возникновении проблем:

1. Проверьте раздел "Устранение проблем" в этом документе
2. Проверьте логи скриптов и контейнеров
3. Обратитесь к документации PostgreSQL и Docker
4. Создайте issue в репозитории проекта
