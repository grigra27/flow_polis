# Backup-контур production: backlog улучшений

Дата: 2026-09-19, ред. 4 (2026-09-23: решение владельца по offsite-хранению после закрытия P0). Источник проблем: [`prod-backup-audit-2026-09-19.md`](./prod-backup-audit-2026-09-19.md).

Режим составления: только read-only изучение. Ни код, ни сервер, ни cron, ни firewall не менялись.
Сервер: `ssh polis`, приложение в `/root/insurance_broker` (Docker Compose `docker-compose.prod.yml`), cron от root.

Обозначения: риск = Low / Medium / High; «downtime» = нужен ли остановочный перерыв. Downtime согласуется отдельно, непосредственно перед задачей, если он реально потребуется.

### Что изменилось в рев. 4 (решение владельца, 2026-09-23)

Ветка P0 закрыта (P0-09 PASS, 2026-09-22 — см. раздел 6). Владелец принял решение: **отдельное независимое offsite-хранилище на этом этапе не строится**; VK-зеркало (и Telegram, если/когда сеть починится) — осознанно принятая единственная внешняя копия резервных данных. Это закрывает **Q1** и **Q2** из раздела 3. Следствия для задач, которые предполагали `rclone`/S3-хранилище:

- **CANCELLED:** P1-01 (спека offsite), P1-02 (выгрузка DB), P1-03 (выгрузка media), P1-04 (проверяемость offsite-копий) — вся цепочка держалась на P1-01.
- **CANCELLED as specified:** P1-09 (периодический drill **из offsite**) — держалась на P1-02/P1-04; разовый эквивалент уже выполнен в P0-09.
- **Пересмотрены (offsite-часть убрана, остальное в силе):** P1-05 (retention — только локально), P1-06 (теперь документирует принятый риск, а не мотивирует будущий offsite), P1-08 (dead man's switch без зависимости от артефакта P1-09), P1-10 (VK — единственный практический канал; варианты Telegram-прокси и email убраны из scope).
- **Закрыта диагностикой + решением:** P1-07 (Q2 отвечен).

Раздел 2 (порядок выполнения), раздел 3 (Q1/Q2), раздел 4 (D6) и раздел 5 (реестр) обновлены соответственно. Приоритет P2 внутри раздела 1 не менялся построчно, но рекомендованный порядок в разделе 2 пересобран: P2-02 (деньги — недостающая КВ) и P2-05 (возможные реальные 403 у пользователей) подняты выше эксплуатационной гигиены.

### Что изменилось в рев. 3

P0-08 (несоответствие `REQUIRED_STAGES` и `result` устранено: `notify`/`mirror` вне обязательных стадий не влияют на `result` и код возврата; `exit=4` только при обязательном `notify`; стадии развязаны по типам — `DB_REQUIRED_STAGES` / `MEDIA_REQUIRED_STAGES`), P0-09 (core acceptance без `mirror=1 notify=1`, доставка сообщений — отдельный неблокирующий smoke test), P2-01 (`pk=None` больше не guard; добавлен тест на сохранение валидации для несохранённого объекта), P1-02/P1-03 (переключение обязательных стадий по типам, media не ломается при появлении DB-offsite), новая P1-10 (реализация выбранной схемы уведомлений), P1-08 (контроль давности drill включён в scope/acceptance, зависимости от P1-09 и P1-10), порядок фазы C, реестр ID и перекрёстные ссылки.

### Что изменилось в рев. 2

P0-02 (restorability вместо 100 % checksum старого архива), P0-05 (динамический `file_count` вместо хардкода), P0-06 (минимальная содержательная верификация), P0-08 (полноценный status contract: `created` / `verified` / `offsite` / `mirror` / `notify` / `result` / `exit`; VK и Telegram больше не считаются offsite), P0-09 (немедленный E2E gate + неблокирующее наблюдение за cron), P1-04 (исправлена ссылка), новая P1-09 (периодический restore drill из offsite), P2-01 (смысл правки и тест), P2-02 (rollback без восстановления БД из backup), P2-03 (выбран `create`, rationale), P2-05 (policy 526 вынесена), блок вопросов владельцу сокращён до 5, инженерные решения приняты самостоятельно (раздел 4).

---

## 0. Read-only факты, повлиявшие на декомпозицию

| Факт | Где | Влияние на план |
|---|---|---|
| `/root/insurance_broker` не является git-чекоутом (`.git` отсутствует), **но канал доставки существует**: `.github/workflows/deploy.yml:181-191` на каждый push в `main` выполняет `rsync -avz ./ …:~/insurance_broker/`, и `scripts/` из sync **не исключён**. `scripts/backup-db-telegram.sh`, `backup-media-telegram.sh`, `telegram-notify.sh` байт-в-байт совпадают с репозиторием (md5 `6972fbe…`, `1a24c0e…`, `d57946c…`) | сервер + repo + workflow | Канонический deployment path уже есть; P0-03 сведён к его подтверждению, отдельный механизм доставки не вводится |
| `scripts/import-database.sh:157-158` выполняет `DROP DATABASE insurance_broker_prod` | repo | **Запрещено** использовать для restore-drill; нужен scratch-DB путь (решение D2) |
| `notify_backup_success` глотает ошибки доставки: `send_telegram_message … \|\| true` (:507), `send_telegram_file … \|\| true` (:512) | telegram-notify.sh | Статус доставки существует (`send_telegram_file` возвращает 1), но выбрасывается → P0-08 |
| `send_telegram_message`/`send_telegram_file` возвращают **0**, если включённых каналов нет вообще (:398, :449) | telegram-notify.sh | «Нет каналов = успех» — дефект в рамках P0-08 |
| Media-скрипт **молча пропускает** верификацию: guard `[ -f "$backup_file" ] && [[ == *.tar.gz ]]` (:349) не срабатывает на мусорной переменной | backup-media-telegram.sh | В `backup-media.log` нет ни строки «Verifying», ни WARN — хуже, чем в DB-логе |
| Не-Telegram вариант `backup-db.sh:255` верифицирует через symlink `$latest_backup` и корректен, но **cron'ом не используется** | scripts/ | Готовый образец правильного паттерна; кандидат на удаление/объединение (P2-06) |
| Штатный признак завершения дампа подтверждён фактически: поток содержит заголовок `-- PostgreSQL database dump` и терминатор `-- PostgreSQL database dump complete` (после него идёт `\unrestrict …`) | `db_backup_20260919_020050.sql.gz` | P0-06 использует именно эти два маркера, без эвристик |
| В media-архиве 227 regular files + 11 каталогов; `backup_20260914_030050.meta` содержит `file_count=227` | сервер | P0-06 сверяет число regular files с `file_count` из metadata **этого** архива, а не с константой |
| Django пишет `django.log`/`security.log` через `RotatingFileHandler` (10 MB × 10) | config/settings.py:417-428 | logrotate для них **не нужен** и вреден; ротировать только cron-аппенды |
| `lsof` по `/root/insurance_broker/logs/*.log`: постоянно открыты только `django.log` и `security.log` (gunicorn ×3, celery ×4, uid 10001). Ни один cron-лог ни кем не удерживается | сервер | Основание выбрать `create`, а не `copytruncate` (P2-03) |
| Cron-строки пишут через shell-редирект `>> file 2>&1`, то есть файл открывается заново на каждый запуск | crontab | То же основание для P2-03 |
| Cron-строка health-check передаёт только `--notify-telegram`, флага `--notify-vk` нет | crontab + `apps/core/management/commands/system_health_check.py:32` | Аварийные алерты (диск/память/БД) уходят в мёртвый Telegram → алертинга де-факто нет |
| `api.telegram.org` недостижим; на сервере **нет** `rclone`, `aws`, `s3cmd` | сервер | Offsite = только VK docs (это mirror, не хранилище); для P1 нужен установочный инструмент |
| `.env.deployment` содержит `BACKUP_DIR=/opt/insurance_broker_backups`, которого не существует; реальный путь — `$HOME/insurance_broker_backups` (/root/…) | сервер | Мёртвая, вводящая в заблуждение переменная → P2-06 |
| Ресурсы: 1.9 GB RAM (0.8 GB free), 21 GB свободно на /, `/var/lib/docker` = 1.9 GB; дамп 1.5 MB, media-архив 50 MB | сервер | Restore-drill и тестовые распаковки безопасны по ресурсам |
| Пустой volume `insurance_broker_media` (0 файлов) рядом с живым `insurance_broker_media_volume` (227 файлов) | сервер | Ловушка для будущих правок → P2-06 |
| `CSRF_TRUSTED_ORIGINS` в `config/settings.py` не задан; nginx слушает `polis.insflow.ru` | repo + сервер | Основа для P2-05 |

---

# 1. Полный backlog

## P0 — критично для надёжности backup-контура

### P0-01 — Baseline: тестовый restore актуального DB-дампа в scratch-БД
- **Проблема:** за 9 месяцев нет ни одного подтверждения, что дамп восстанавливается; автоматическая проверка не работает (P0-06).
- **Почему P0:** без этого невозможно отличить «бэкапы плохие» от «бэкапы хорошие, но проверка сломана». Делается **до** правок кода, чтобы зафиксировать текущее состояние.
- **Тронутые объекты:** сервер, контейнер `insurance_broker_db`, `/root/insurance_broker_backups/database/db_backup_20260919_020050.sql.gz`. Код репозитория не трогается.
- **Scope:** создать scratch-БД `polis_restore_test` в существующем контейнере (решение D2), восстановить туда последний дамп через `psql`, зафиксировать число ошибок SQL, сравнить списки и количества таблиц/строк с прод-БД (помня, что дамп — снимок 02:00, расхождения в таблицax журнала допустимы), удалить scratch-БД.
- **Не входит:** правки скриптов, `import-database.sh` (он роняет прод-БД), восстановление поверх прод-БД, media.
- **Зависимости:** нет.
- **Риск:** Medium (работа на прод-инстансе PostgreSQL; данные прод-БД не изменяются). **Downtime:** нет.
- **Acceptance:** 0 ошибок `psql`; создано 38 таблиц; sanity-сверка по справочным таблицам (`policies_policy`, `policies_paymentschedule`, `auth_user`) согласуется со снимком; scratch-БД удалена; результат зафиксирован в задаче.
- **Как проверить:** `createdb` → `psql < dump` → `SELECT count(*) FROM pg_tables WHERE schemaname='public'` → выборочные `count(*)` → `dropdb`.
- **Rollback:** `DROP DATABASE polis_restore_test` (больше ничего не создаётся).
- **Статус:** **PASS (2026-09-19)** — baseline-restore выполнен: дамп `db_backup_20260919_020050.sql.gz` восстановлен в scratch-БД `polis_restore_test` (контейнер `insurance_broker_db`, решение D2); restore — 0 ошибок `psql`; создано 38 таблиц; sanity-сверка schema/таблиц/справочных row counts (`policies_policy`, `policies_paymentschedule`, `auth_user`) совпала с production-снимком; прод-БД не изменялась; scratch-БД удалена. Вывод: текущий `pg_dump` восстановим.

### P0-02 — Baseline: проверка restorability media-архива
- **Проблема:** media-архивы проходят лишь `tar -tzf`; факт распаковки и разумности содержимого не проверялся.
- **Почему P0:** media (логотипы страховщиков, иконки типов, коммуникации) при порче невосстановимы из других мест.
- **Тронутые объекты:** `/root/insurance_broker_backups/media/media_backup_20260914_030050.tar.gz`, временные каталоги в `/tmp`.
- **Scope — два разных теста, не смешивать:**
  1. **Restorability существующего боевого архива 14.09:** успешная распаковка во временный каталог без ошибок tar; корректная структура (ожидаемые верхние каталоги `branch_logos`, `communications`, `insurance_type_icons`, `insurer_logos`); разумное содержимое — количество regular files > 0 и согласовано с `file_count=` из `backup_20260914_030050.meta`, ненулевые размеры у типичных файлов. **Сверка 1:1 с текущим live volume на этом шаге не выполняется** — с 14.09 media могли легитимно измениться, и расхождение не будет дефектом.
  2. **Строгая проверка `live volume ↔ archive`:** выполняется на **отдельном свежем тестовом архиве**, созданном в `/tmp` из текущего состояния `insurance_broker_media_volume` тем же методом, что и боевой скрипт (`docker run … tar czf`); тогда и только тогда оправданы 100 % сверка имён и checksum. Все тестовые данные (архив и распакованный каталог) удаляются по завершении.
- **Не входит:** раскатка архива поверх live volume, изменение скриптов, ротация.
- **Зависимости:** нет.
- **Риск:** Low (чтение volume + ~55 MB × 2 во временном каталоге). **Downtime:** нет.
- **Acceptance:** (1) архив 14.09 распаковывается без ошибок, структура и количество regular files согласованы с его metadata; (2) на свежем тестовом архиве — 100 % совпадение имён и checksum с live volume на момент создания; (3) временные артефакты удалены, `/tmp` чист.
- **Как проверить:** `tar -tzvf` с разбором типов записей; `find … -type f | md5sum` с обеих сторон; `diff` списков; `ls /tmp/<workdir>` после cleanup.
- **Rollback:** `rm -rf /tmp/<workdir>` (каталоги создаются задачей).
- **Статус:** **PASS (2026-09-19)** — боевой архив `media_backup_20260914_030050.tar.gz` читается и распаковывается без ошибок tar; ожидаемые верхние каталоги на месте; regular files = 227, что совпадает с `file_count=227` в его `.meta`; строгая проверка на свежем read-only снапшоте: список имён и SHA256 live volume ↔ тестовый архив — 100 % совпадение; live volume не изменялся; временные артефакты удалены. Найденный при проверке дефект `count_media_files` (mount volume без `:/media:ro`) устранён в P0-05.

### P0-03 — Подтвердить, что существующий CI/CD доставляет backup-скрипты на production — **PASS (2026-09-19)**
- **Проблема:** исходная формулировка задачи была неверной. Из отсутствия `.git` в `/root/insurance_broker` был сделан вывод, что канала доставки правок нет и его надо создать. Канал есть — это GitHub Actions.
- **Почему P0:** перед правками P0-04…P0-08 нужно подтверждение, что «исправлено в репозитории» действительно означает «исправлено в проде».
- **Тронутые объекты:** только `docs/BACKUP_RESTORE.md`. Сервер, бэкап-скрипты и `deploy.yml` не меняются.
- **Scope:** зафиксировать канонический deployment path и задокументировать его как единственный.
- **Не входит:** любой отдельный механизм доставки (`scp`, git-чекоут на проде, ansible), правка `deploy.yml` и `deploy.sh`, cron, бэкап-скрипты.
- **Зависимости:** нет.
- **Риск:** Low. **Downtime:** нет.
- **Acceptance — выполнено, PASS** на основании установленных фактов:
  1. checksum трёх скриптов на проде и в репозитории совпадают: md5 `6972fbebcac3f4570549d7e44273966e` / `1a24c0e638f49e338860411392faddda` / `d57946c5448552cc7379ca9ebba0293f`, подтверждено также по sha256;
  2. `.github/workflows/deploy.yml:181-191` на каждый push в `main` выполняет `rsync -avz ./ …:~/insurance_broker/`;
  3. `scripts/` не входит в `--exclude` этого rsync (исключены только `.git`, `venv`, `black_venv`, `__pycache__`, `*.pyc`, `.env`, `.env.prod`, `db.sqlite3`, `certbot/`).
- **Как проверить:** `sha256sum` трёх файлов с обеих сторон; список `--exclude` в `deploy.yml`.
- **Rollback:** не требуется — изменений на проде задача не вносит.
- **Housekeeping:** от отменённой попытки внедрить отдельный `scp`-доставщик на сервере остался безвредный файл `/root/insurance_broker/scripts/backup-db-telegram.sh.bak-20260919_222023` (идентичная копия боевого скрипта). Никакого отдельного deployment-механизма задача не вводила и не вводит: canonical deployment path — существующий `.github/workflows/deploy.yml`; файл удалается в P2-06 вместе с прочим мусором в `scripts/`.

### P0-04 — Исправить перехват stdout в `backup-db-telegram.sh` — **PASS (2026-09-19, deployed 42f2769)**
- **Проблема:** `backup_file=$(backup_database)` (:279) кладёт в переменную весь stdout функции, включая `log_info`-строки; путь теряется → верификация падает 267/271 раз.
- **Почему P0:** корневая причина «сломанной проверки целостности».
- **Тронутые файлы:** `scripts/backup-db-telegram.sh` (`backup_database` ~:60-120, вызов :279).
- **Scope:** весь служебный вывод функции — в stderr, на stdout только путь; либо (по образцу `backup-db.sh:255`) не возвращать путь строкой, а использовать symlink `latest_backup.sql.gz`. Подход выбирается один раз и применяется также в P0-05.
- **Не входит:** логика верификации (P0-06), exit-коды (P0-07), доставка и статус (P0-08), media.
- **Зависимости:** P0-03.
- **Риск:** Low. **Downtime:** нет.
- **Acceptance:** `backup_file` = ровно один существующий путь; поведение при реальном провале дампа не изменилось (ненулевой exit).
- **Как проверить:** изолированный запуск `BACKUP_DIR=/tmp/bktest ./scripts/backup-db-telegram.sh` → в логе `Verifying backup integrity... → Backup file integrity verified`, а не `Backup file not found`; `bash -n`, `shellcheck`.
- **Rollback:** `git revert` правки + прогон того же workflow (deploy на push в `main`).
- **Статус:** код в `main` (42f2769), доставлен на production штатным workflow (run 35465686132), sha256 проде = sha256 коммита (`fc88d7b3…`), regression-набор `scripts/tests/test-backup-db-stdout-contract.sh` зелёный и локально, и на сервере. **Cron-наблюдение закрыто (2026-09-21):** прогоны 20.09 и 21.09 02:00 MSK — `Verifying backup integrity... → Backup file integrity verified`, без `Backup file not found` / `Backup verification failed` (последний сбой — 19.09 02:03, до деплоя).

### P0-05 — Исправить перехват stdout в `backup-media-telegram.sh` — **PASS (2026-09-19, deployed 42f2769)**
- **Проблема:** тот же дефект — `backup_file=$(backup_media)` (:343) при `echo "$backup_file"` (:138). Хуже: из-за guard'а :349 верификация молча пропускается, и в логе нет даже следа проверки.
- **Почему P0:** media-бэкапы не проверяются вообще и никогда.
- **Тронутые файлы:** `scripts/backup-media-telegram.sh` (:70-146, :343, :349).
- **Scope:** тот же паттерн, что в P0-04; убрать условие, молча пропускающее верификацию; случай пустого архива (`.empty`-маркер) обрабатывать явно и независимо.
- **Не входит:** DB-скрипт, содержательность проверок (P0-06), exit-коды (P0-07), статус (P0-08).
- **Зависимости:** P0-03; концептуально P0-04 (единый паттерн).
- **Риск:** Low. **Downtime:** нет.
- **Acceptance:** лог содержит `Verifying backup integrity...` и строку результата вида `Backup file integrity verified (N files)`, где **N берётся динамически из `file_count=` в `.meta` этого же прогона** (никаких констант вроде 227 в коде или в критериях) и N > 0.
- **Как проверить:** `BACKUP_DIR=/tmp/bktest_media ./scripts/backup-media-telegram.sh`, затем `grep file_count /tmp/bktest_media/*.meta` и сверка с N в логе; `bash -n`.
- **Rollback:** `git revert` правки + прогон того же workflow.
- **Статус:** код в `main` (42f2769), доставлен на production штатным workflow (run 35465686132), sha256 проде = sha256 коммита (`7abeb4b6…`), regression-набор `scripts/tests/test-backup-media-stdout-contract.sh` зелёный и локально, и на сервере; доп. правки P0-02 в `count_media_files` (mount `:/media:ro`, удалён мёртвый `volume_path=$1`) включены. **Cron-наблюдение закрыто (2026-09-21):** плановый прогон пн 03:00 MSK (crontab `0 3 * * 1`; комментарий «Weekly on Sunday» в самом crontab — описка, выражение = понедельник; сам cron не менялся) дал `Verifying backup integrity... → Backup file integrity verified (227 files)` — верификация больше не пропускается молча.

### P0-06 — Минимальная, устойчивая автоматическая integrity verification
- **Проблема:** после P0-04/05 проверка заработает, но означает лишь «архив не битый». Нужен обязательный минимум, который при этом не рассыпется при будущих изменениях версии PostgreSQL, числа таблиц или состава media.
- **Почему P0:** верификация — единственная автоматическая страховка корректности nightly-файла.
- **Принцип:** никаких эвристик и «псевдо-restore» из десяти признаков. Полную восстанавливаемость подтверждает restore drill (P0-01, P0-09, P1-09), а не эта функция.
- **Тронутые файлы:** `scripts/backup-db-telegram.sh:verify_backup` (:123-143), `scripts/backup-media-telegram.sh:verify_backup` (:149-169).
- **Scope — DB, ровно четыре проверки:**
  1. файл существует, размер > `MIN_BACKUP_BYTES` (env, консервативный нижний порог, дефолт 10 KiB);
  2. `gzip -t` — физическая целостность сжатого потока;
  3. декомпрессированное содержимое идентифицируется как PostgreSQL dump — наличие сигнатуры `-- PostgreSQL database dump` в начале;
  4. штатный признак корректного завершения — `-- PostgreSQL database dump complete` в хвосте потока (фактически присутствует в текущих дампах; после него идёт `\unrestrict`).
- **Scope — media, ровно три проверки:**
  1. `tar -tzf` читается без ошибок;
  2. в архиве есть ожидаемые regular files (записи типа `-`, а не только каталоги);
  3. количество regular files согласуется с `file_count=` из `.meta` **этого конкретного** архива.
- **Не входит:** сравнение с «эталонным» числом таблиц, восстановление, проверка содержимого по бизнес-признакам, offsite.
- **Зависимости:** P0-04, P0-05.
- **Риск:** Low. **Downtime:** нет.
- **Acceptance:** негативные тесты падают — усечённый на 50 % gzip; валидный gzip с произвольным текстом вместо дампа; дамп без терминатора завершения; tar без regular files; tar, где число файлов не совпадает с его `.meta`. Реальные вчерашние DB- и media-архивы проходят.
- **Как проверить:** набор негативных fixture-файлов в `/tmp` + вызов `./scripts/backup-db-telegram.sh --verify <fixture>` (этот режим уже есть в скрипте) и проверка кода возврата; затем один реальный cron-прогон.
- **Rollback:** `git revert` правки + прогон того же workflow.
- **Статус:** **PASS (2026-09-20, deployed 504d178)** — код в `main`, доставлен штатным workflow (run 35468996152), sha256 проде = sha256 коммита (DB `1cc48bae…`, media `24850fdc…`). Набор `scripts/tests/test-backup-integrity-verification.sh` — 22/22 локально и на сервере, включая lifecycle-assertion временных файлов `verify_backup()` (изолированный TMPDIR, мутационный контроль). Read-only smoke на реальных артефактах проде: `--verify db_backup_20260919_020050.sql.gz` → exit 0 (все 4 проверки); `--verify media_backup_20260914_030050.tar.gz` → exit 0, 227 regular files == `file_count=227` в его `.meta`. Негативный read-only контроль (мусорный gzip в `/tmp`) → exit 1 «Content is not a PostgreSQL dump». **Cron-наблюдение закрыто (2026-09-21):** содержательная верификация подтверждена плановыми прогонами — DB 20.09 и 21.09 (`Backup file integrity verified`), media 21.09 (`integrity verified (227 files)`).

### P0-07 — Корректный exit code при провале integrity check
- **Проблема:** `verify_backup … || { log_warn "Backup verification failed"; }` (DB :286, media :350) и финальный `exit 0` (:296/:365). Скрипт всегда успешен → cron, деплой и мониторинг слепы.
- **Почему P0:** без кода возврата починенная проверка остаётся невидимой для машины.
- **Тронутые файлы:** main-секции обоих `-telegram.sh`.
- **Scope:** провал верификации → `notify_backup_error` + ненулевой exit **согласно общей таблице кодов (D5)**: `2` = «создан, но не проверен». Бэкап-файл при этом не удаляется — он нужен для разбора; retention (P1-05) сделает своё.
- **Не входит:** статус доставки и поле `mirror`/`notify` (P0-08), формат `last_status.json` (P0-08).
- **Зависимости:** P0-06 (иначе вместе с `set -e` получаем некорректные падения).
- **Риск:** Medium (меняется контракт cron'а: ошибки станут видимы и могут вскрыть смежные проблемы). **Downtime:** нет.
- **Acceptance:** подложенный битый файл → exit 2, ERROR в логе, текст-уведомление доходит в VK; корректный прогон → exit 0.
- **Как проверить:** запуск с подменённым `BACKUP_DIR` и fixture-файлом, `echo $?`; ближайший ночной лог.
- **Rollback:** `git revert` правки + прогон того же workflow.
- **Статус:** **PASS (2026-09-20, deployed 504d178)** — workflow-контракт реализован: verification failure → `log_error "Backup verification failed"` + `notify_backup_error` + **exit 2**, файл сохранён для разбора, normal flow (cleanup/list) не продолжается; creation failure сохраняет прежний exit 1; media `.empty` — по-прежнему success (exit 0). Проверено полным main-flow набором `scripts/tests/test-backup-exit-codes.sh` — 35/35 локально и на production checkout (run 35468996152), control-прогон против HEAD ловит исходный дефект (7 FAIL). **Известное ограничение (закрыто в P0-08):** `notify_backup_success` исторически отправлялся внутри `backup_database`/`backup_media` до верификации — при verification failure порядок был «Started → Completed Successfully → Backup Failed». P0-08 перенёс единственное финальное уведомление в main после верификации и оценки обязательных стадий — ложный success больше невозможен (см. статус P0-08). **Доставка в живой канал (закрыто на baseline P0-09):** cron-прогон 22.09 02:00 под кодом `f7376b6` — финальное уведомление фактически доставлено в VK (`mirror=1 notify=1` в `BACKUP_RESULT`, см. статус P0-09); error-путь и exit 2 подтверждены изолированным harness S7 на production checkout. Наблюдение за натуральным негативным cron-прогоном (verification failure в бою) остаётся operational-наблюдением P1-08/P1-10. Плановые cron-прогоны 20–21.09 завершились успешно (exit 0); негативного cron-прогона с exit 2 после деплоя пока не наблюдалось (провалов верификации не было) — контрольный негативный сценарий подтверждён regression-набором.

### P0-08 — Status contract: машинно-определяемый итог по стадиям (created / verified / offsite / mirror / notify / result / exit)
- **Проблема:** `notify_backup_success` вызывает отправку с `|| true` (:507, :512), поэтому отказ всех каналов (событие `File delivery failed on all enabled channels`, 21 раз в логе) ни на что не влияет; а при отсутствии включённых каналов (:398, :449) возвращается 0, то есть ложный «успех». Кроме того, в текущем понимании «файл ушёл в VK/Telegram» приравнивается к наличию внешней копии, что неверно: мессенджер — это зеркало и канал уведомления, а не хранилище.
- **Почему P0:** из-за этого 2026-09-10 и 2026-09-17 дамп не покинул сервер, и никто не узнал; и потому что на этом контракте построены P1-02…P1-10.
- **Тронутые файлы:** `scripts/telegram-notify.sh` (:375-514), `scripts/backup-db-telegram.sh`, `scripts/backup-media-telegram.sh`; общий слой статуса вынесен в новый общий library-файл `scripts/backup-status.sh` (по образцу sourcing-паттерна `telegram-notify.sh`).
- **Scope — контракт, спроектированный так, чтобы после P1-02 значения полей не пришлось переопределять.**

  Поля и их неизменный смысл:

  | Поле | Значения | Смысл |
  |---|---|---|
  | `created` | `1\|0` | файл дампа/архива создан и не пуст |
  | `verified` | `1\|0` | пройдена integrity verification по P0-06 |
  | `offsite` | `1\|0\|-` | копия в **настоящем** внешнем хранилище (P1-02/P1-03). `-` = стадия ещё не реализована. **Отправка в VK/Telegram сюда не входит и никогда не установит `offsite=1`** |
  | `mirror` | `1\|0\|-` | файл передан в мессенджер как зеркало (`send_vk_file`, `send_telegram_file`) — convenience, копией не считается |
  | `notify` | `1\|0\|-` | текстовое уведомление доставлено хотя бы в один включённый канал; `-` = ни один канал не включён (тогда WARNING, а не успех) |
  | `result` | `ok\|fail` | вычисляется **только** по стадиям из обязательного набора данного типа бэкапа; `mirror` и `notify`, в него не входящие, на `result` не влияют |
  | `exit` | `0\|1\|2\|3\|4` | таблица D5; `4` возможен только когда `notify` входит в обязательные стадии и не выполнен |

  **Обязательные стадии задаются конфигурационно и независимо для каждого типа бэкапа:** `DB_REQUIRED_STAGES` и `MEDIA_REQUIRED_STAGES` (общий `REQUIRED_STAGES` — значение по умолчанию для обоих). На всём этапе P0 оба набора = `created,verified`. После P1-02 переключается **только** `DB_REQUIRED_STAGES` → `created,verified,offsite`, а `MEDIA_REQUIRED_STAGES` остаётся `created,verified` до завершения P1-03 — так исключается период, когда внедрение offsite для DB искусственно валит media-бэкап. Смена набора стадий не меняет семантику ни одного поля.

  **Принцип разделения ответственности:** отказ или недоступность внешнего communication-канала (`mirror`, `notify`) вне обязательного набора фиксируется в статусе и логируется как WARNING `degraded communication`, но **не делает `result=fail` и не меняет код возврата успешно завершённого backup**.

  Формат фиксации:
  - одна финальная строка в лог: `BACKUP_RESULT type=db file=db_backup_20260919_020050.sql.gz created=1 verified=1 offsite=- mirror=1 notify=1 result=ok exit=0`;
  - машиночитаемый `last_status.json` в `BACKUP_DIR` (решение D3): `{ts,type,file,bytes,created,verified,offsite,mirror,notify,required,result,exit}`, где не реализованная стадия — `null`, а не `false`.

  Также устраняется дефект «нет включённых каналов = успех»: при полностью выключенных каналах `notify=-` и пишется WARNING. Итог становится `fail` (и `exit=4`) **только если `notify` явно включён в обязательные стадии этого типа бэкапа**.
- **Не входит:** реализация offsite-хранилища (P1-02/P1-03), диагностика Telegram (P1-07), алертинг (P1-08), документация ролей каналов (P1-06).
- **Зависимости:** P0-03; согласуется с P0-07 (общая таблица кодов возврата D5).
- **Риск:** Medium (правится общий слой уведомлений; проверить регрессию у `monitor-logs-telegram.sh`, `setup-error-monitoring.sh`, `daily_digest`). **Downtime:** нет.
- **Acceptance — пять прогонов с разными env:**
  1. `DB_REQUIRED_STAGES=created,verified`, при этом VK-зеркало принудительно падает → `mirror=0 notify=0`, WARNING `degraded communication`, но **`result=ok` и `exit=0`**: backup успешен.
  2. `TELEGRAM_ENABLED=false` + `VK_ENABLED=false` → `mirror=- notify=-`, `result=ok`, `exit=0` (ни одна из этих стадий не обязательна).
  3. `DB_REQUIRED_STAGES=created,verified,notify` при выключенных каналах → `result=fail`, `exit=4`.
  4. `DB_REQUIRED_STAGES=created,verified,offsite` без реализованного хранилища → `offsite=-`, `result=fail`, `exit=3`.
  5. Развязка по типам в одном окружении: `DB_REQUIRED_STAGES=created,verified,offsite` + `MEDIA_REQUIRED_STAGES=created,verified` → DB-прогон даёт `exit=3`, media-прогон — `result=ok`, `exit=0`.
  Отсутствие настоящего offsite на этапе P0 (`offsite=-`) не трактуется ни как успех хранения, ни как ложный провал.
- **Как проверить:** прогоны с подменёнными env-флагами в `/tmp` (пункты 1-5 acceptance, причём пункт 5 — обоими скриптами в одном окружении); `cat last_status.json`; `python3 -m json.tool` на файле статуса; реальный ночной прогон.
- **Rollback:** `git revert` правок четырёх файлов (три из scope + новый `backup-status.sh`; доставляются одним набором) + прогон того же workflow.
- **Статус:** **PASS — deployed (2026-09-21, commit `f7376b6`, workflow run 35643934361)**. Реализовано и доставлено штатным GitHub Actions (`scripts/backup-status.sh` — новый общий слой; `telegram-notify.sh`, `backup-db-telegram.sh`, `backup-media-telegram.sh`):
  - status contract по всем семи полям (`created/verified/offsite/mirror/notify/result/exit`) — контракт реализован;
  - машиночитаемый `last_status.json` (атомарная запись tmp+mv, валидный JSON) и ровно одна финальная строка `BACKUP_RESULT`;
  - tri-state доставка (`1` — доставлено хотя бы в один канал, `0` — все включённые каналы отказали, `-` — каналов нет) вместо «нет каналов = успех»; WARNING `degraded communication` без порчи `result` при необязательных communication-стадиях;
  - `DB_REQUIRED_STAGES` / `MEDIA_REQUIRED_STAGES` независимы (fallback `REQUIRED_STAGES`, дефолт `created,verified`); `mirror` обязательным не бывает; неизвестная стадия = конфигурационный отказ (exit 1, до начала работы);
  - `notify_backup_success` перенесён после верификации и оценки обязательных стадий (дефект порядка из P0-07 закрыт);
  - при required-offsite failure ложный success невозможен: до финального уведомления считается core outcome без `notify`, при провале — только error-путь, `mirror=-`, `exit=3` (D5);
  - media `.empty` = `created=1 verified=1` без tar-верификации; semantics P0-07 (suspect-файл сохраняется, normal flow не продолжается) сохранены;
  - regression-матрица S1–S12 зелёная: `scripts/tests/test-backup-status-contract.sh` 179/179, суммарно с P0-04/05/06/07 — 265/265 assertions.
  Deployment: коммит `f7376b6` (`fix: add backup status contract`), workflow run **35643934361** — все стадии success (Validate Configuration / Run Tests / Build Docker Image / Copy files (rsync) / Deploy on server / Run migrations / Health check / Notify Deployment Status).
  Production verification (2026-09-21, read-only + sandboxed): sha256 четырёх скриптов проде = sha256 коммита; `bash -n` OK; owner/mode штатные; контейнеры Up; cron не менялся; все 5 изолированных наборов на production checkout зелёные (13/16/22/35/179 = 265); smoke статуса-контракта A–E (S1/S3/S4/S5/S7 на прод-коде) — PASS; notification-compat без реальной сети (tri-state 0/1/2, `set -e`-совместимость обёрток, сохранение `NOTIFY_TEXT_RC`/`NOTIFY_FILE_RC`, best-effort старых callers) — PASS; read-only `--verify` свежих боевых артефактов `db_backup_20260921_020050.sql.gz` и `media_backup_20260921_030051.tar.gz` — exit 0. E2E-подтверждение на живом прогоне с настоящим каналом (VK) — закрыто в P0-09: изолированный E2E-гейт 22.09 (notification-слой — stub, без реальной сети) плюс фактический cron-прогон 22.09 02:00 с живым VK-каналом (`mirror=1 notify=1` в `BACKUP_RESULT`).

### P0-09 — End-to-end gate: немедленная проверка исправленного контура
- **Проблема:** нужно подтвердить, что контур (create → verify → status → exit code) работает на настоящих скриптах до того, как ветка P0 считается закрытой.
- **Почему P0:** финальный gate ветки P0.
- **Тронутые объекты:** сервер, изолированные тестовые каталоги, дамп, созданный исправленным кодом.
- **Scope (всё выполняется сразу, в рамках одной сессии):**
  1. ручной полный прогон DB backup в изолированный `BACKUP_DIR`;
  2. ручной полный прогон media backup в изолированный `BACKUP_DIR`;
  3. сверка цепочки: факт создания → строки верификации → `BACKUP_RESULT` / `last_status.json` → `echo $?`;
  4. отдельная проверка негативного сценария (битый fixture → ожидаемые exit-коды из D5);
  5. **restore drill DB-дампа, созданного уже исправленным кодом**, по методике P0-01 (scratch-БД `polis_restore_test`, затем удаление).

  Отдельно, как **неблокирующий communication smoke test**: фактическая отправка `mirror` и `notify` в VK. Фактический результат (включая отказ) записывается в отчёт задачи.
- **Post-deploy observation (не блокирует закрытие задачи):** следующие плановые cron-прогоны — DB 02:00 ежедневно и media понедельник 03:00 — проверяются на отсутствие строк `Backup verification failed`, `Backup file not found`, `delivery failed on all enabled channels` и на presence `result=ok`. Фиксируется отдельным пунктом наблюдения после P0-09, к закрытию P1-08.
- **Не входит:** требования `offsite=1`, а также `mirror=1` / `notify=1` в качестве условий приёмки (см. P0-08: на этапе P0 эти стадии не обязательны); новые каналы хранения, мониторинг, алерты, ожидание календарных суток как условие закрытия.
- **Зависимости:** P0-04, P0-05, P0-06, P0-07, P0-08; методика — P0-01.
- **Риск:** Low. **Downtime:** нет.
- **Core acceptance (блокирует закрытие ветки P0):** `created=1`; `verified=1`; корректный status contract (`BACKUP_RESULT` + `last_status.json` со всеми семью полями, включая `offsite=-`); корректный `exit` — как на успешном, так и на негативных fixtures (таблица D5); успешный restore drill нового DB-дампа.
- **Не блокирует закрытие:** фактические значения `mirror` и `notify`. Временный отказ внешнего communication-канала (упавший VK, недоступный Telegram) не мешает закрыть core P0 gate, поскольку эти стадии не входят в `DB_REQUIRED_STAGES` / `MEDIA_REQUIRED_STAGES` — ровно по контракту P0-08. Результат smoke test фиксируется в отчёте и используется в P1-10.
- **Как проверить:** вывод прогонов + `last_status.json` + отчёт drill; чек-лист по пяти пунктам core scope плюс отдельно — smoke test каналов.
- **Rollback:** не требуется (задача проверочная; тестовые каталоги и scratch-БД удаляются).
- **Статус:** **PASS (2026-09-22, E2E-гейт на production-инфраструктуре, код `f7376b6`)**. Все прогоны — побайтовыми копиями production-скриптов (sha256 совпали с прод checkout и коммитом) из изолированного runner `/tmp/p0-09-e2e-20260922_160732` со stub-слоем `telegram-notify.sh` (без `telegram-config.sh`, без network-вызовов — гарантированная невозможность реальной Telegram/VK-отправки):
  - **real DB isolated backup — PASS:** живой `pg_dump` из `insurance_broker_db`, `db_backup_20260922_161216.sql.gz` (1 547 298 байт, sha256 `d12393ed…`), exit 0, ровно один `BACKUP_RESULT`, `created=1 verified=1 offsite=- mirror=- notify=- required=created,verified result=ok exit=0`, parser-valid `last_status.json` (file/bytes соответствуют факту), standalone `--verify` по реальному имени — exit 0; degraded-communication WARNING допустим по контракту;
  - **status contract нового run — PASS** (см. выше, все семь полей + D5-код 0);
  - **fresh dump restore drill — PASS:** scratch `polis_p009_restore_20260922_161216` (создана с проверкой отсутствия), restore через `gunzip | psql -v ON_ERROR_STOP=1 --no-psqlrc`, PIPESTATUS=`0 0`, stderr пуст; 38 таблиц / 38 PK / 41 FK / 160 индексов / md5 списка таблиц = боевым; per-table counts идентичны снапшоту прода; все FK `convalidated=true`; orphan-проверки (payments→policy, policyinfo→policy, emailrecipients→email, permissions→content_type, adminlog→user) — нули; scratch удалена, состав `pg_database` восстановлен;
  - **real media isolated backup — PASS:** live volume только `:ro`, `media_backup_20260922_162042.tar.gz` (51 889 021 байт, sha256 `51919170…`), exit 0, `.meta` (`file_count=227`), `created=1 verified=1 result=ok exit=0`, один `BACKUP_RESULT`, `tar -tzf` OK, regular files 227 = meta, standalone `--verify` по реальному имени — exit 0;
  - **extraction/manifest sanity — PASS:** распаковка 227 файлов, sample-файлы читаются (JPEG), SHA256-манифест live volume (`:ro`, дважды — стабильность подтверждена) побайтово совпал с манифестом архива по path+checksum;
  - **negative fixture — PASS:** корректный gzip 120 КБ (не дамп) → `--verify` exit 1 (DB-3 header marker отсутствует); полный verification-failure flow — существующим изолированным harness S7 на production checkout (`DOCKER_DB_MODE=garbage`): created=1, verified=0, result=fail, exit=2, suspect-файл сохранён, success-уведомление/mirror отсутствуют, error-путь использован, один `BACKUP_RESULT`, валидный failure `last_status.json` — 24/24 assertions; все 5 наборов на прод checkout зелёные (13/16/22/35/179 = 265), трипваир «curl never called» — PASS;
  - **production unchanged — PASS:** `dirs_before/after` и `hashes_before/after` боевых каталогов идентичны (diff пуст), artifacts P0-09 создавались только в изолированном каталоге; cron/env/скрипты боевого checkout не менялись;
  - **cleanup — PASS:** scratch-БД, extracted tree, stub-runner, изолированные artifacts, harness-логи удалены; `polis_p009%` БД — 0, `/tmp` без P0-09-файлов, протёкших `verify_*` temp нет.
  - **Communication smoke (неблокирующий):** в этом гейте notification-слой намеренно изолирован stub'ом («нет каналов», rc=2 → `notify=-`/`mirror=-`); фактическая доставка проверена отдельно cron-прогоном 22.09 02:00 под кодом `f7376b6`: `mirror=1 notify=1` (текст в VK доставлен; VK file-upload первой попытки отвалился с `no_free_space/var/www/pi`, файл всё же ушёл). Telegram по-прежнему мёртв (curl 28). Результат учитывается в P1-10.
  - **Post-deploy cron observation (собрано, не блокирует):** плановый DB-прогон 22.09 02:00 — `BACKUP_RESULT … result=ok exit=0`, реальный `last_status.json` в боевом каталоге валиден; media под новым кодом ещё не запускалась (следующий понедельник, 28.09 03:00) — observational, к закрытию P1-08.

---

## P1 — устойчивость внешнего хранения и уведомлений

### P1-01 — Выбрать и специфицировать независимое offsite-хранилище (без кода) — **CANCELLED (владелец, 2026-09-23)**
- **Проблема:** настоящей внешней копии нет: VK docs падал 2 из последних 8 ночей (`no_free_space`, `not saved`), и это мессенджер, а не хранилище.
- **Почему P1:** P0 обеспечивает корректность и проверяемость локальных дампов; отсутствие независимой внешней копии — риск потери данных, а не текущая регрессия.
- **Тронутые объекты:** `docs/BACKUP_RESTORE.md`, будущий `.env.prod`.
- **Scope:** одностраничная спека: провайдер (см. Q1), схема имён, нужно ли шифрование на клиенте, стоимость при 1.5 MB/день + 50 MB/неделя, бюджет и хранение credentials, RPO/RTO. Инструмент принимается заранее — `rclone` одним бинарником (решение D6), чтобы спека не раздувалась.
- **Не входит:** установка, скрипты, cron, тесты.
- **Зависимости:** решение владельца (Q1).
- **Риск:** Low. **Downtime:** нет.
- **Acceptance:** согласованный документ: bucket/хост, инструмент, способ хранения ключей, retention (перекрёсток с P1-05).
- **Как проверить:** ревью владельца.
- **Rollback:** не применимо.
- **Статус:** **CANCELLED (2026-09-23)** — владелец решил не строить отдельное durable offsite-хранилище на этом этапе; VK-зеркало (и Telegram, если сеть восстановится) сознательно принимается как единственная внешняя копия. Отвечает Q1. Задача не удалена и не переиспользован номер — при пересмотре решения в будущем можно вернуться к ней как есть.

### P1-02 — Реализовать выгрузку DB-дампа в настоящее offsite-хранилище — **CANCELLED (владелец, 2026-09-23)**
- **Проблема:** независимой внешней копии дампа нет.
- **Почему P1:** прямое продолжение P1-01.
- **Тронутые файлы:** новый `scripts/backup-upload-offsite.sh` (предпочтительно, чтобы не раздувать P0-контур), `.env.prod`, установка rclone на сервер.
- **Scope:** upload `.sql.gz` + `.meta` после успешной верификации; идемпотентность; таймауты/ретраи; **запись результата в поле `offsite` контракта P0-08**; после успешного внедрения — перевод **только** `DB_REQUIRED_STAGES` в `created,verified,offsite`; `MEDIA_REQUIRED_STAGES` не трогается (см. P0-08).
- **Не входит:** media (P1-03), prune (P1-05), проверяемость загрузки (P1-04), алерты (P1-08), drill (P1-09), Telegram/VK-логика.
- **Зависимости:** P0-08, P1-01.
- **Риск:** Medium (новый внешний сетевой путь на проде + секреты). **Downtime:** нет.
- **Acceptance:** объект появляется в хранилище с корректным размером; `offsite=1` и `result=ok` в статусе; при недоступности хранилища — `offsite=0`, `result=fail`, exit `3`.
- **Как проверить:** листинг хранилища, сверка размера, негативный тест (заведомо неверный endpoint), наблюдение за плановым прогоном.
- **Rollback:** вернуть `DB_REQUIRED_STAGES="created,verified"` и убрать вызов; объекты в хранилище безвредны. Media-прогон на rollback не влияет вовсе.
- **Статус:** **CANCELLED (2026-09-23)** — зависела от P1-01 (CANCELLED). Реализация не начиналась, код `backup-status.sh` (P0-08) уже поддерживает `offsite` как `-`/`null` бессрочно — переключения `DB_REQUIRED_STAGES` не будет, пока решение не пересмотрено.

### P1-03 — Реализовать выгрузку media-архива в настоящее offsite-хранилище — **CANCELLED (владелец, 2026-09-23)**
- **Проблема:** то же для weekly media (50 MB).
- **Почему P1:** отдельный объект и отдельный цикл (понедельник).
- **Тронутые файлы:** `scripts/backup-media-telegram.sh`, upload-скрипт из P1-02.
- **Scope:** переиспользование P1-02 через параметризацию; контроль размера архива (защита от случайного разрастания media и удара по бюджету); `offsite=` в статусе media-прогона; перевод `MEDIA_REQUIRED_STAGES` в `created,verified,offsite` — только здесь, после успешного прогона.
- **Не входит:** retention, DB.
- **Зависимости:** P1-02.
- **Риск:** Low-Medium. **Downtime:** нет.
- **Acceptance:** архив в хранилище, `offsite=1` в статусе media-прогона.
- **Как проверить:** ближайший понедельник 03:00 + листинг хранилища.
- **Rollback:** отключение вызова, как в P1-02.
- **Статус:** **CANCELLED (2026-09-23)** — зависела от P1-02 (CANCELLED).

### P1-04 — Обеспечить проверяемость offsite-копий — **CANCELLED (владелец, 2026-09-23)**
- **Проблема:** загрузка ≠ восстанавливаемость; кейс VK `no_free_space` показал, что подтверждения API недостаточно.
- **Почему P1:** защищает новую ветку хранения.
- **Тронутые файлы:** `scripts/backup-upload-offsite.sh`, статус P0-08.
- **Scope:** после upload — HEAD/stat объекта, сверка размера (etag/md5 где доступно), запись результата в `offsite`.
- **Не входит:** периодический drill из offsite — это отдельная **P1-09**.
- **Зависимости:** P1-02.
- **Риск:** Low. **Downtime:** нет.
- **Acceptance:** рассогласование размера → `offsite=0` и ненулевой exit.
- **Как проверить:** негативный тест с обрезанным объектом.
- **Rollback:** отключение проверки.
- **Статус:** **CANCELLED (2026-09-23)** — зависела от P1-02 (CANCELLED); нечего проверять без загрузки.

### P1-05 — Retention policy для локальных копий (offsite-часть отменена вместе с P1-01…04)
- **Проблема:** локально 7 дней; в VK — формально бессрочно, но без гарантий и без версионирования. Ни суточных «на всякий случай», ни месячных точек. **После решения владельца (2026-09-23) не строить offsite (см. рев. 4) локальная глубина хранения — единственная гарантированная страховка**: VK падал 2 из 8 наблюдавшихся ночей (`no_free_space`, `not saved`, аудит 2026-09-19), и если это совпадёт с любой другой проблемой на сервере, только локальные копии останутся проверяемым источником восстановления.
- **Почему P1:** вопрос корректности хранения, а не работоспособности кода; после отмены offsite это стало *более* значимым, а не менее.
- **Тронутые файлы:** `RETENTION_DAYS` в обоих скриптах и cron-строках, `cleanup_old_backups` (:172 в обоих).
- **Scope:** пересмотреть только локальную сетку (значение — Q3, пересмотренный): предложение — daily DB на 14–30 дней вместо текущих 7, media — несколько последних weekly вместо текущих 7 дней. Offsite-часть (daily/weekly/monthly в хранилище) из scope убрана — хранилища нет. Prune — с защитой от «удалить всё» (минимум N файлов) и обязательным dry-run (`PRINT_ONLY=true`).
- **Не входит:** изменение графика создания бэкапов; offsite prune (P1-01…04, CANCELLED).
- **Зависимости:** подтверждение владельца (Q3, пересмотренный).
- **Риск:** Medium (ошибка prune способна уничтожить копии). **Downtime:** нет.
- **Acceptance:** dry-run даёт корректный список; боевой прогон не трогает свежие файлы; минимум N файлов гарантированно остаётся.
- **Как проверить:** синтетический каталог с файлами разного возраста; `ls` после реального cleanup.
- **Rollback:** env-конфиг; поэтому dry-run обязателен перед первым боевым запуском.
- **Статус:** pending, объём сокращён 2026-09-23 (offsite-часть снята).

### P1-06 — Задокументировать принятую архитектуру: VK-зеркало = единственная внешняя копия (осознанный риск)
- **Проблема:** файл бэкапа уходит в мессенджер, а текстовые уведомления по Telegram не доходят (Telegram мёртв). Владелец решил не строить независимое offsite-хранилище (Q1, 2026-09-23, см. рев. 4) — значит VK-зеркало фактически исполняет роль внешней копии, хотя контракт P0-08 по определению никогда не поставит ему `offsite=1`. Если это не задокументировать явно, через полгода кто-то (инженер или другой агент) примет `mirror=1` за «есть offsite» и не заметит реальный риск.
- **Почему P1:** устраняет разрыв между тем, что фактически защищает данные, и тем, что документация может подразумевать.
- **Тронутые файлы:** `docs/BACKUP_RESTORE.md` (раздел «Backup Storage»), `scripts/README.md`, комментарии в `scripts/telegram-notify.sh`.
- **Scope:** без изменения контракта P0-08 — явно зафиксировать: (1) независимого offsite нет и на этом этапе не планируется (решение владельца, дата); (2) VK-зеркало — единственная внешняя копия де-факто; (3) известная статистика надёжности VK (2 отказа `no_free_space`/`not saved` из 8 наблюдавшихся ночей, аудит 2026-09-19); (4) что реально митигирует риск — integrity verification (P0-06), подтверждённый restore drill (P0-09), локальный retention (P1-05); (5) что не митигирует — потеря сервера оставляет зависимость только от VK, версионирование на стороне VK не гарантировано.
- **Не входит:** удаление VK-зеркалирования (оно полезно и остаётся основным механизмом), миграция данных, правки семантики полей контракта.
- **Зависимости:** P0-08; для точных цифр — P1-05.
- **Риск:** Low. **Downtime:** нет.
- **Acceptance:** документация не называет VK/Telegram «backup storage» без оговорок; явно указано, что отсутствие offsite — осознанный принятый риск, а не забытая задача, с датой и тем, кто решение принял.
- **Как проверить:** ревью diff документации и строк лога.
- **Rollback:** revert коммита.
- **Статус:** pending, переформулирована 2026-09-23 (была ориентирована на будущий offsite, теперь документирует принятое решение его не строить).

### P1-07 — Диагностика недоступности `api.telegram.org` и выбор канала уведомлений — **PASS: диагностика + решение владельца (2026-09-23)**
- **Проблема:** минимум с 2026-04-25 Telegram недоступен с прод-сервера: с хоста — connect timeout (curl exit 28), из контейнера — `[Errno 101] Network is unreachable`. Затронуты все скрипты и Django (`notifications`), включая `daily_digest` 06:00.
- **Почему P1:** сам бэкап не ломает, но убивает наблюдаемость.
- **Тронутые объекты:** сеть сервера (только диагностика), `.env.prod`, код уведомлений.
- **Scope:** определить уровень отказа — DNS / TCP / TLS (`getent`, `nc -zv`, `curl -v` на `api.telegram.org:443` в сравнении с другим внешним хостом:443, проверка исходящих правил). Затем варианты с ценой и риском: (а) признать VK основным и везде добавить `--notify-vk`; (б) SOCKS/MTProto-прокси; (в) локальный Bot API proxy; (г) email как независимый fallback.
- **Не входит:** любые изменения firewall/сети и установка прокси — запрещены в этой фазе; само внедрение выбранной схемы — отдельная задача **P1-10**.
- **Зависимости:** нет (параллельно с P0).
- **Риск:** Low (read-only). **Downtime:** нет.
- **Acceptance:** зафиксирован уровень отказа и 2-3 варианта с ценой/риском; владелец выбрал один (Q2).
- **Как проверить:** после внедрения выбранного решения в P1-10 — `test_telegram_connection` из скрипта.
- **Rollback:** не применимо (диагностика).
- **Статус:** **PASS (2026-09-23).** Диагностика выполнена аудитом 2026-09-19 (connect timeout на TCP-уровне до `api.telegram.org:443`, подтверждено повторно 22–23.09 на реальных cron-прогонах: `curl: (28) Failed to connect`). Решение владельца по Q2: вариант **(а) — VK признаётся основным и единственным практическим каналом**; инвестиции в сетевой обход для Telegram (SOCKS/MTProto-прокси, локальный Bot API proxy) и email-fallback на этом этапе не делаются. Внедрение — **P1-10**.

### P1-08 — Мониторинг свежести бэкапа (dead man's switch)
- **Проблема:** о проблемах никто не узнаёт: скрипты до P0-07/08 всегда завершались успехом, а health-check до 2026-09-23 шлёт только в мёртвый Telegram (флаг `--notify-vk` в cron-строке отсутствовал — **исправлено в P1-10 в тот же день**). Сама по себе эта починка не создаёт мониторинга свежести — она только чинит канал доставки; наблюдателя за `last_status.json` (dead man's switch) по-прежнему нет, это и есть scope данной задачи.
- **Почему P1:** без детектора замирание контура снова станет тихим.
- **Тронутые объекты:** `apps/core/management/commands/system_health_check.py` (324 строки, есть реестр проверок и `--notify-vk`), cron-строка health-check (каждые 30 мин), `last_status.json` из P0-08 (решение D4).
- **Scope:** проверка `backup_freshness`: читает `last_status.json` для db/media, требует свежесть (DB < 26 ч, media < 8 сут) и `result=ok` с учётом текущего обязательного набора стадий **соответствующего типа** (`DB_REQUIRED_STAGES` / `MEDIA_REQUIRED_STAGES`, см. P0-08); warning/critical → уведомление в оба канала (в cron-строку добавляется `--notify-vk`, см. P1-10). Работает как dead man's switch. Сюда же закрывается post-deploy observation из P0-09 (первый плановый media-прогон под новым кодом — понедельник 28.09 03:00 MSK).
- **Убрано из scope (2026-09-23):** контроль давности артефакта restore-drill **из offsite** — держался на P1-09, которая отменена вместе с offsite-веткой (см. рев. 4). Разовая подтверждённая восстанавливаемость есть в P0-09; периодического автоматического контроля её давности на этом этапе не будет.
- **Не входит:** новый демон/сервис, внешние uptime-сервисы, Grafana; реализация канала доставки алерта (это P1-10, от которого P1-08 зависит).
- **Зависимости:** P0-08, **P1-10 (работающий канал уведомлений)**.
- **Риск:** Medium (правка кода Django + cron; может понадобиться деплой web-контейнера — downtime согласуется перед задачей). **Downtime:** возможен короткий рестарт — согласовать отдельно.
- **Acceptance:** протухший или отсутствующий `last_status.json` → warning и сообщение доходит в VK; актуальный `result=ok` → HEALTHY и молчание; P1-08 запускается после P1-10 и видит живой канал доставки.
- **Как проверить:** порча `last_status.json` в песочном каталоге + ручной `python manage.py system_health_check --check-all --notify-vk` с проверкой, что сигнал дошёл.
- **Rollback:** отключить проверку (константа/флаг) и вернуть cron-строку.
- **Статус:** pending, объём сокращён 2026-09-23 (контроль drill-артефакта снят вместе с P1-09).

### P1-09 — Периодический restore drill из offsite — **CANCELLED as specified (владелец, 2026-09-23)**
- **Проблема:** P1-04 доказывает лишь наличие объекта и совпадение размера. Ни один тест пока не подтверждает, что дамп, лежащий вне сервера, можно скачать и поднять — то есть вся ветка offsite остаётся непроверенной по главному критерию.
- **Почему P1:** повышает доверие к резервной копии, но не блокирует корректность текущих nightly-дампов (это P0).
- **Тронутые файлы:** новый `scripts/restore-drill-offsite.sh` (или, на первом этапе, только документ), `docs/BACKUP_RESTORE.md` (новый раздел «Периодический restore drill»), scratch-БД `polis_restore_test` на сервере.
- **Scope — полный цикл, а не проверка наличия:**
  1. выбрать в offsite-хранилище свежий (или согласованный по возрасту) DB-дамп и скачать во временный каталог;
  2. integrity check скачанного файла функцией из P0-06 (тот же код, что и в nightly);
  3. restore в scratch-БД `polis_restore_test` по методике P0-01;
  4. sanity checks: 0 ошибок SQL, 38 таблиц, выборочные `count(*)` по справочным таблицам, `django_migrations` присутствует и непуст;
  5. удалить scratch-БД и скачанный файл;
  6. зафиксировать итог одной строкой/файлом, чтобы P1-08 мог видеть давность последнего успешного drill.
- **Автоматизация — по минимуму:** первый этап — **документированный runbook с ручным запуском** (команды готовы к копипасте, никакого планировщика). Автоматизация по cron — только после 2-3 успешных ручных прогонов и отдельного согласования, если в ней появится нужда.
- **Предлагаемая периодичность:** **ежемесячно** для DB-дампа (стоимость — минутная операция над 1.5 MB; риск-профиль: без drill мы можем год не знать, что offsite-копии не поднимаются), **ежеквартально** для media (распаковка 50 MB + сверка, по методике P0-02). Дополнительный обязательный drill — сразу после изменений в ветке offsite (P1-02…P1-05) и после любого инцидента с `offsite=0`.
- **Не входит:** восстановление поверх прод-БД, `import-database.sh`, автоматизация на первом этапе, ротация и prune (P1-05), мониторинг (P1-08).
- **Зависимости:** P1-02, P1-04.
- **Риск:** Medium (работает с прод-инстансом PostgreSQL, но только в отдельной scratch-БД). **Downtime:** нет.
- **Acceptance:** runbook в `docs/BACKUP_RESTORE.md`; выполненный вручную прогон «из коробки» на актуальном offsite-объекте с успешным финалом и полным cleanup; временных артефактов после запуска не осталось; дата последнего успешного drill доступна машине.
- **Как проверить:** повторный прогон другим человеком по одному только документу (тест на самодостаточность runbook'а); `ls` временных каталогов и `\l` списания баз после.
- **Rollback:** `DROP DATABASE polis_restore_test` и удаление скачанного файла; сам drill боевые данные не затрагивает.
- **Статус:** **CANCELLED as specified (2026-09-23)** — зависела от реального offsite (P1-02/P1-04, CANCELLED), скачивать и проверять нечего. Разовый эквивалент («дамп, созданный исправленным кодом, восстановим») уже подтверждён в **P0-09** (2026-09-22): scratch-БД `polis_restore_test`, 38 таблиц/PK/FK/индексов, orphan-проверки — чисто. Периодическое повторение такого drill'а на **локальном/VK-зеркалированном** дампе (без offsite) — дешёвая опция на будущее, но отдельно не заказана; при желании завести отдельной небольшой задачей после P1-08.

### P1-10 — Сделать VK единственным практическим каналом уведомлений везде (решение Q2 реализуется) — **PASS: основной scope (2026-09-23)**
- **Проблема:** Q2 закрыт решением владельца 2026-09-23 (см. P1-07): VK — основной и единственный практический канал на этом этапе, обход сети для Telegram и email-fallback не делаем. Но по факту VK включён не везде: **cron-строка health-check передаёт только `--notify-telegram`** (подтверждено на проде 2026-09-23 — `*/30 * * * * ... system_health_check --check-all --notify-telegram ...`, без `--notify-vk`). Значит прямо сейчас критические алерты (диск, память, БД) уходят исключительно в мёртвый Telegram — это самый дешёвый и самый срочный пункт этой задачи, можно сделать в первую очередь отдельно от остального.
- **Почему P1:** без этого мониторинг (P1-08) бессмысленен даже после реализации — сигнал будет генерироваться и никуда не доходить, то есть ровно тот дефект, ради которого всё затевалось.
- **Тронутые объекты:** cron-строка `system_health_check` на сервере, `scripts/telegram-notify.sh` (флаг `notify` контракта P0-08), другие места, где отправка сейчас предполагает только Telegram.
- **Scope — только вариант (а), выбор Q2 закрыт:**
  1. (сделать первым, дёшево) добавить `--notify-vk` в cron-строку `system_health_check` на сервере — сейчас там только `--notify-telegram`;
  2. пройтись по остальным вызовам уведомлений (`daily_digest`, `cleanup_login_attempts`, прямые вызовы `send_telegram_*`) и добавить VK-эквивалент там, где сейчас есть только Telegram;
  3. подтвердить, что `notify` в контракте P0-08 отражает фактическую доставку через VK (реализация уже есть в P0-08/P0-09 и наблюдается в проде с 22.09 — здесь только закрывается пробел с флагом, контракт не переписывается).
  Варианты (б) Telegram через SOCKS/MTProto-прокси и (в) email-fallback — **не делаем** (решение Q2, 2026-09-23).
- **Не входит:** сетевые изменения ради Telegram, email-инфраструктура, monitoring-логика (P1-08), offsite-хранение (P1-01…04, CANCELLED).
- **Зависимости:** P1-07 (решение Q2 принято), P0-08 (поле `notify`).
- **Риск:** Low-Medium (правка cron-строки и, возможно, ещё пары мест; изменения доставки затронут не только бэкап, но и `daily_digest`, `cleanup_login_attempts`). **Downtime:** нет.
- **Acceptance:** cron health-check шлёт и в VK; ручной `python manage.py system_health_check --check-all --notify-vk` доставляет сообщение; во всех местах, где раньше был только Telegram, теперь есть VK; `notify=1` в контракте P0-08 подтверждён фактической доставкой (уже наблюдается в проде с 22.09 — см. P0-09).
- **Как проверить:** ручной запуск `python manage.py system_health_check --check-all --notify-vk` с принудительной порчей `last_status.json`; `crontab -l | grep notify` на предмет строк с `--notify-telegram` без соседнего `--notify-vk`; факт получения подтверждает владелец.
- **Rollback:** вернуть прежние строки скриптов/cron (реверт коммита).
- **Статус:** **PASS — основной scope закрыт (2026-09-23).**
  1. **Cron health-check на проде поправлен напрямую (`ssh polis`, не через GitHub Actions — crontab не входит в rsync-деплой):** снят бэкап текущего crontab в `/tmp/crontab_backup_20260923_142810.txt` на сервере, единственная строка `system_health_check` изменена точечным `sed` (проверено `diff` перед применением — тронута ровно одна строка), новая строка установлена `crontab`. Живой прогон `system_health_check --check-all --notify-vk` на проде — HEALTHY, флаг принят без ошибок, уведомление корректно не отправлено (status=healthy, без `--notify-always` VK-отправка пропускается по документированному дефолту) — правка не вызывает побочных сообщений в канал.
  2. **Источник в репозитории приведён в соответствие** (`scripts/setup-error-monitoring.sh`), чтобы баг не вернулся при следующей установке: сама cron-строка (:164), self-test шага 4 (:95) и памятка с полезными командами (:220) — везде добавлен `--notify-vk` рядом с `--notify-telegram`. Деплоится штатным GitHub Actions при пуше в `main` (rsync, `scripts/` не исключён — см. D1/P0-03); сам cron этим не переустанавливается, правки на сервере и в репозитории сделаны отдельно и независимо.
  3. **Аудит остальных мест (пункт 2 scope) выполнен:** `daily_digest` уже шлёт в оба канала по умолчанию (флаги `--no-telegram`/`--no-vk` — opt-out, не opt-in, отдельной правки не требовалось); `cleanup_login_attempts` уведомлений не отправляет вообще ни в один канал — это не регрессия этой задачи, а отдельный (и незначительный) пробел, в scope P1-10 не включён.
  4. **`notify=1` в контракте P0-08** уже подтверждён фактической доставкой через VK на реальных cron-прогонах бэкапа 22–23.09 (см. P0-09) — отдельного подтверждения не требовалось.
- **Не закрыто, вынесено отдельно:** side finding из P0-09 про приоритет `Environment variables > .env.prod > .env` в `telegram-config.sh` (см. ниже) — код чтения конфига не менялся, это отдельная правка, не блокирующая работу VK-канала как такового.
- **Side finding из P0-09 (осталось открытым, не входит в закрытый выше scope):** комментарий в `telegram-config.sh` заявляет приоритет `Environment variables > .env.prod > .env`, но код сначала `source`'ит `.env.prod` / `.env`, поэтому переменные из файлов перезаписывают внешние env. Наружно выставленный `TELEGRAM_ENABLED=false` / `VK_ENABLED=false` нельзя считать безопасным способом отключить отправку — для тестов на прод-машине нужна изоляция notification-слоя (как в P0-09: отдельный runner со stub вместо `telegram-notify.sh`). Требует отдельной небольшой задачи: привести фактический приоритет в соответствие документированному (внешний env побеждает) или явно переформулировать контракт.

---

## P2 — эксплуатационные и прикладные ошибки

### P2-01 — `PaymentSchedule.clean()`: не подменять стандартную валидацию обязательных полей
- **Проблема:** `apps/policies/models.py:384-391` строит `Q(year_number__lt=self.year_number)` при `year_number=None` → Django бросает `ValueError: Cannot use None as a query value`; исключение перехватывается широким `except`, валидация дат пропускается и остаётся WARNING `Skipping date validation … Manual review recommended for policy 526` (2026-09-14, 1 раз).
- **Смысл исправления (важно):** цель **не** в том, чтобы разрешить сохранять платёж с пустыми `year_number` / `installment_number`. Эти поля обязательны, и их отсутствием должна заниматься стандартная Django field validation. Задача — чтобы кастомный `clean()` не выбрасывал **вторичную** техническую ошибку в ситуации, когда данные уже некорректны и должны быть отверганы штатным механизмом.
- **Почему P2:** единично, не влияет на данные и бэкап, но сейчас некорректные записи либо проходят с пропущенной проверкой, либо дают технический traceback вместо понятной ошибки валидации.
- **Тронутые файлы:** `apps/policies/models.py` (`clean`), `apps/policies/tests/…`.
- **Scope:** ранний выход из `clean()`, если не заполнены данные, реально нужные для запроса-сравнения: `policy_id`, `year_number`, `installment_number` — без попытки запроса; при этом `full_clean()` обязан выдать нормальный `ValidationError` от field validation. **`pk` в guard не участвует**: у нового несохранённого объекта `pk` законно равен `None`, и кастомная проверка последовательности дат обязана работать при создании. Никаких изменений в определениях полей и миграций.
- **Не входит:** правка данных policy 526 (оформляется follow-up'ом этой же задачи, см. ниже), изменения модели, массовая чистка.
- **Зависимости:** нет.
- **Риск:** Low-Medium (задевает путь сохранения платежей; прогнать существующие тесты). **Downtime:** нет.
- **Acceptance:** два регрессионных теста:
  (a) `year_number=None` (и/или `installment_number=None`) → `full_clean()` падает с `ValidationError`, **не** с `ValueError`, и запись с такими полями не сохраняется;
  (b) новый валидный `PaymentSchedule` с `pk=None` проходит кастомную проверку последовательности дат (не выходит молча), а при некорректной последовательности дат получает `ValidationError` — то есть отказ от `pk` в guard не ослабил валидацию при создании.
  Существующие тесты сохранений платежа зелёные; traceback в проде не воспроизводится.
- **Как проверить:** `pytest apps/policies`; отдельно — ручной `PaymentSchedule(...).full_clean()` в shell с проверкой типа исключения для обоих сценариев.
- **Follow-up (в рамках задачи):** read-only разбор фактических данных policy 526 — почему у платежа пусто `year_number` / `installment_number`, есть ли другие такие записи (`SELECT … WHERE year_number IS NULL OR installment_number IS NULL`), и нужен ли точечный ремонт данных по Q… не требуя решения владельца на этапе планирования.
- **Rollback:** revert коммита.

### P2-02 — Отсутствие `CommissionRate` для insurer=17 / insurance_type=1
- **Проблема:** `apps/policies/signals.py:29-45` — 12 warning'ов; для других пар ставка находится (`Auto-set commission rate …`), следствие — `kv_rub` не рассчитывается автоматически.
- **Почему P2:** вопрос полноты справочника, не надёжности backup-контура.
- **Тронутые объекты:** данные (ставки КВ), при необходимости admin/migration; уровень логирования в `signals.py`.
- **Scope:** read-only выяснить, какие пары `insurer`/`insurance_type` не покрыты и по каким уже проведённым платежам нет КВ; далее либо добавить ставку (значение — от бизнеса, Q4), либо признать отсутствие легитимным и понизить лог до INFO с метрикой.
- **Не входит:** автозаполнение денежных значений без подтверждения владельца.
- **Зависимости:** нет.
- **Риск:** Low (исследование) / Medium (правка данных). **Downtime:** нет.
- **Acceptance:** список непокрытых пар + решение по каждой; warning'и не повторяются либо осмысленно исчезли.
- **Как проверить:** SQL-выборка `PaymentSchedule` без `commission_rate`; неделя наблюдения за warning'ами.
- **Rollback (по требованию владельца):** **не** предполагает восстановления БД из backup. Перед любым изменением фиксируется исходное состояние затронутых строк (SELECT-вывод с `id` и текущими значениями, сохраняется в задачу/коммит), после чего rollback — точечная обратная правка (`UPDATE`/`DELETE` по зафиксированным `id`). Полный restore не используется ни как план откатa, ни как рабочий инструмент.

### P2-03 — logrotate для cron-логов в `/root/insurance_broker/logs/`
- **Проблема:** `health-check.log` 6.0 MB (пишется каждые 30 мин), `daily-digest.log` 2.4 MB, `backup-*.log` копятся с декабря 2025; правила ротации для приложения отсутствуют.
- **Почему P2:** при 21 GB свободных это не угроза, но логи становятся нечитаемыми.
- **Тронутые файлы:** новый `/etc/logrotate.d/insurance-broker`. **Не трогаем** `django.log` и `security.log` — они уже ротируются `RotatingFileHandler` (settings.py:417-428), внешняя ротация будет с ним конфликтовать.
- **Выбор стратегии: `create` (rename + создание нового), а НЕ `copytruncate`.** Rationale: `lsof` показал, что ни один cron-лог не удерживается открытым процессом — все они пишутся cron-строкой через shell-редирект `>> … 2>&1`, то есть файл открывается заново на каждый запуск (максимум между перезаписью — следующий прогон: 30 мин для health-check, 24 ч для backup). Значит `create` не теряет записей, а `copytruncate` лишь добавляет окно гонки между копированием и усечением, в которое строки теряются. `copytruncate` оправдан только для long-lived fd — как раз тех, что у gunicorn/celery в `django.log`/`security.log`, и они не подлежат внешней ротации. Новый файл создаётся с владельцем `10001:10001` (как сейчас, logrotate работает от root и это допускает), чтобы не менять сложившуюся картину прав.
- **Scope:** правило для `backup-db.log`, `backup-media.log`, `backup-cleanup.log`, `health-check.log`, `daily-digest.log`, `cleanup-login-attempts.log`: weekly, `rotate 8`, `compress`, `missingok`, `notifempty`, `create 0644 10001 10001`.
- **Не входит:** уровни логирования (P2-04), перенос каталога, смена прав существующих файлов, ротация docker json-логов.
- **Зависимости:** нет.
- **Риск:** Low. **Downtime:** нет.
- **Acceptance:** `logrotate -d` без ошибок; `logrotate -f` создаёт `.1.gz`, следующий cron-прогон дописывает в новый файл по тому же пути; в `django.log`/`security.log` ротация не вмешивается.
- **Как проверить:** принудительный прогон + `ls -l` (пути, владельцы) + плановый health-check после.
- **Rollback:** удалить единственный конфиг-файл `/etc/logrotate.d/insurance-broker`.

### P2-04 — DEBUG-шум в `daily_digest`
- **Проблема:** `daily-digest.log` на 2.4 MB состоит из `DEBUG: Processing updated policy …`; полезная часть тонется.
- **Почему P2:** эксплуатационная чистота.
- **Тронутые файлы:** management-команда `daily_digest`, при необходимости LOGGING.
- **Scope:** итоги — INFO, детальный перебор — DEBUG под опцию `--verbose`.
- **Не входит:** изменение содержания дайджеста и получателей.
- **Зависимости:** нет.
- **Риск:** Low. **Downtime:** нет.
- **Acceptance:** типичный прогон ≤ ~30 строк; `--verbose` возвращает прежнюю подробность.
- **Как проверить:** ручной запуск команды в контейнере; размер следующего дневного лога.
- **Rollback:** revert.

### P2-05 — Классификация HTTP/CSRF/security warning'ов и настройка trusted origins
- **Проблема:** необработанные повторы в `django.log`: `Forbidden (Referer checking failed — no Referer)` 314, `CSRF cookie not set` 153, `Referer … https://www.polis.insflow.ru/ does not match any trusted origins` 99, `Referer is insecure while host is secure` 42, `Origin checking failed — https://109.68.215.223` 36, `Blocked login attempt …`. При этом `CSRF_TRUSTED_ORIGINS` в `config/settings.py` **не задан**.
- **Почему P2:** часть — мусор сканеров, но часть указывает на реальные 403 у легитимных запросов с `www`-варианта и IP-хоста.
- **Тронутые файлы:** `config/settings.py`; nginx-config в этой задаче только читается.
- **Scope:** разложить warning'и по реальному трафику (IP/UA из nginx-логов), отделить ботов от живых пользователей; **если влияние на легитимных пользователей подтверждено** — завести `CSRF_TRUSTED_ORIGINS` с каноническими host'ами (решение D8) и задокументировать «ожидаемый шум», чтобы он не маскировал регрессии.
- **Не входит:** разбор данных policy 526 и любые вопросы платежей/справочников (P2-01, P2-02); отключение CSRF-защиты; `SESSION_COOKIE_*`; rate limiting/анти-бот.
- **Зависимости:** нет.
- **Риск:** Medium (CSRF-настройки могут сломать вход и формы; проверять в low-traffic, рестарт при необходимости — согласовать отдельно). **Downtime:** нет (при правке настроек — рестарт web, обсуждается перед задачей).
- **Acceptance:** 403 CSRF для реальных пользователей = 0; шум от ботов не выше согласованного порога; по каждой группе есть письменное решение «чинить/игнорировать».
- **Как проверить:** вручную логин + сохранение платежа; grep `django.log` за 3 дня.
- **Rollback:** вернуть настройку, рестарт web.

### P2-06 — Housekeeping: лишний мусор и мёртвые конфиги (опись, без удаления)
- **Проблема:** в `scripts/` файл с именем `ystemctl start cron` (1735 байт, Dec 2025 — следствие опечатки с перенаправлением) и каталог `scripts/~/insurance_broker_backups/` с дампом 2025-12-09; `.env.deployment` содержит несуществующий `BACKUP_DIR=/opt/insurance_broker_backups`; в Docker есть пустой volume-двойник `insurance_broker_media`; `scripts/backup-db.sh` и `scripts/backup-media.sh` — расходящиеся копии логики, cron'ом не используемые (при этом `backup-db.sh:255` содержит корректный паттерн верификации, взятый за образец в P0-04).
- **Почему P2 (низкий приоритет):** на надёжность не влияет, но это ловушки — пустой volume и двойники сбивали с толку во время аудита.
- **Scope:** инвентаризация и предложение списка на удаление/объединение. Удаление — только отдельной согласованной задачей после Q5.
- **Не входит:** любые `rm`, `docker volume rm`, правки скриптов.
- **Зависимости:** нет.
- **Риск:** Low. **Downtime:** нет.
- **Acceptance:** по каждому пункту: что это, кто создал, безопасно ли удалить.
- **Как проверить:** ревью владельцем (Q5).
- **Rollback:** не применимо.

---

# 2. Рекомендуемый порядок выполнения

**Обновлено 2026-09-23** после закрытия P0 и решения владельца не строить offsite (см. рев. 4 наверху документа).

```
Фаза A (baseline, ничего не меняем) — DONE:
  P0-01 → P0-02 → P1-07 (диагностика, параллельно)

Фаза B (починка контура) — DONE (2026-09-22):
  P0-03 → P0-04 → P0-05 → P0-06 → P0-07 → P0-08 → P0-09

Фаза C (наблюдаемость на принятой архитектуре, без offsite):
  P1-10 (PASS, 2026-09-23) → P1-08 → P1-05 → P1-06
  [P1-01, P1-02, P1-03, P1-04, P1-09 — CANCELLED решением владельца 2026-09-23]

Фаза D (прикладные и эксплуатационные, по значимости):
  P2-02 → P2-05 → P2-04 → P2-01 → P2-03 → P2-06
```

Обоснование порядка (Фазы A/B — исторические, для фазы C и D — актуальные на 2026-09-23):
- **Сначала baseline (P0-01/02), потом код.** Restore-drill на текущих артефактах даёт точку сравнения. Если он упадёт — приоритеты меняются радикально (срочная ветка «спасаем данные»), и правка верификации перестаёт выглядеть косметикой.
- **P0-03 строго перед всеми правками скриптов**: прежде чем чинить скрипты, нужно убедиться, что правка репозитория действительно доезжает до cron. Проверка подтвердила, что доезжает — через GitHub Actions.
- **P0-04 и P0-05** технически независимы; такая очерёдность держится только ради единого паттерна.
- **P0-06 до P0-07:** менять exit code у проверки, которая ещё ничего не проверяет, значит получить «уверенные падения» или «уверенные успехи» без содержания.
- **P0-08 до P0-09:** контракт по стадиям фиксируется до E2E-проверки, иначе P0-09 проверяет не тот статус.
- **P0-09 — немедленный gate**, без ожидания календарных ночей; наблюдение за плановым cron-прогоном закрывается в P1-08.
- **P1-10 первой в фазе C — сделано.** Был самым дешёвым и самым срочным пунктом (на проде не хватало флага `--notify-vk` в cron health-check) и прямой зависимостью P1-08: мониторинг без рабочего канала алертов фиксировал бы проблемы молча — ровно тот дефект, ради которого он заводится. Закрыт 2026-09-23 (см. статус P1-10).
- **P1-08 сразу за P1-10.** Как только канал уведомлений жив, dead man's switch по свежести `last_status.json` можно включать без дальнейших зависимостей (контроль давности offsite-drill из неё убран вместе с P1-09).
- **P1-05 и P1-06 — низкий риск, без внешних зависимостей**, можно делать в любой момент после P1-08 или параллельно с ним.
- **P2-02 первой в фазе D**, потому что это единственная задача с прямым денежным эффектом (недостающая КВ) — инвентаризация масштаба не требует решения владельца и может начаться немедленно.
- **P2-05 следующая**: возможен реальный эффект на живых пользователей (403 у `www`-варианта/IP-хоста); сначала классификация трафика, код не трогается без подтверждения.
- **P2-04, P2-01, P2-03, P2-06 — эксплуатационная гигиена**, порядок между ними не принципиален.

---

# 3. Вопрос владельцу (сокращённый блок — только то, что действительно ваше)

1. **Q1 — Offsite-провайдер и бюджет (P1-01). ОТВЕЧЕН (2026-09-23).** Решение: отдельное независимое offsite-хранилище на этом этапе не строится; VK-зеркало (и Telegram, если сеть восстановится) — осознанно принятая единственная внешняя копия. P1-01…P1-04, P1-09 — CANCELLED (см. рев. 4).
2. **Q2 — Судьба Telegram (P1-07). ОТВЕЧЕН (2026-09-23).** Решение: **VK признаётся основным и единственным практическим каналом уведомлений**; обход сети для Telegram (SOCKS/Bot API proxy) и email-fallback не делаем на этом этапе. Реализация — P1-10 (в первую очередь: добавить `--notify-vk` туда, где сейчас его нет, начиная с cron-строки health-check).
3. **Q3 — Retention, пересмотренный (P1-05).** Offsite-часть вопроса снята вместе с Q1. Остаётся: локально сейчас 7 дней для DB и media — предлагаю поднять DB-хранение до 14–30 дней и оставить для media несколько последних weekly-копий, поскольку это единственная гарантированная страховка при отказе VK (см. P1-05). Подтверждаете глубину или нужна другая?
4. **Q4 — Бизнес-значение CommissionRate (P2-02).** Какая ставка задаётся для `insurer=17 / insurance_type=1`, либо для этой комбинации КВ не начисляется вовсе?
5. **Q5 — Разрешение на удаление housekeeping-мусора (P2-06).** `scripts/ystemctl start cron`, `scripts/~/`, пустой volume `insurance_broker_media`, неиспользуемые `backup-db.sh`/`backup-media.sh`, мёртвая переменная `BACKUP_DIR=/opt/...`.

Downtime ни здесь, ни в задачах не согласуется заранее: он обсуждается непосредственно перед задачей, где реально потребуется (потенциально — P1-08, P2-05).

---

# 4. Инженерные решения, принятые без запроса владельца

Прежние вопросы «как доставлять», «где поднимать scratch-БД», «как хранить статус» переведены в решения по принципу минимальной сложности и безопасного откатa:

- **D1 — Доставка скриптов на сервер (P0-03): отменено.** Решение опиралось на неверную предпосылку «нет git-чекоута на проде = нет канала доставки». Канонический и единственный path — существующий GitHub Actions workflow: `rsync` всего репозитория в `~/insurance_broker/` на push в `main`, `scripts/` из sync не исключён. Отдельный `scp`-механизм не вводится — второй deployment path порождал бы расхождение репозитория и прода вместо того, чтобы его устранять. Откат правки скрипта = `git revert` + прогон того же workflow.
- **D2 — Scratch-БД для drill (P0-01, P0-09, P1-09):** отдельная база `polis_restore_test` внутри существующего контейнера `insurance_broker_db`, а не новый контейнер и не локальная машина. Дамп 1.5 MB, свободных 0.8 GB RAM и 21 GB диска — запас двукратный; изоляция по базе достаточна, прод-БД не читается на запись. `import-database.sh` не используется (он выполняет `DROP DATABASE insurance_broker_prod`).
- **D3 — Хранение статуса (P0-08):** `BACKUP_RESULT`-строка в логе + `last_status.json` в `BACKUP_DIR` (уже примонтирован в web-контейнер как `/app/server_backups`, поэтому Django видит его без новых mount'ов).
- **D4 — Место мониторинга (P1-08):** расширение существующего `system_health_check.py`, а не новый сервис или cron-скрипт: там уже есть реестр проверок, статусы и `--notify-vk`, и он запускается каждые 30 минут.
- **D5 — Таблица кодов возврата (P0-07, P0-08):** `0` = `result=ok`; `1` = не создан (`created=0`); `2` = создан, но не прошёл верификацию (`verified=0`); `3` = не выполнено обязательное внешнее копирование (`offsite=0`); `4` = не выполнено **обязательное** уведомление: `notify=0` или `notify=-` при том, что `notify` входит в обязательные стадии этого типа бэкапа; если `notify` вне набора — код остаётся `0`. Разделение нужно, чтобы P1-08 различал «бэкапа нет» и «бэкап есть, но его не видно».
- **D6 — Инструмент выгрузки (P1-02/P1-03): superseded (владелец, 2026-09-23).** Было: `rclone` одним бинарником (на сервере нет ни `rclone`, ни `aws`, ни `s3cmd`), без самописных S3-клиентов. Теперь не актуально — offsite не строится (P1-01…04 CANCELLED); решение сохранено как справка на случай пересмотра.
- **D7 — Ротация логов (P2-03):** `create`, обоснование — в тексте P2-03 (cron-логи не удерживаются открытыми, подтверждено `lsof`).
- **D8 — Канонические host'ы для CSRF/ALLOWED_HOSTS (P2-05):** `https://polis.insflow.ru` (совпадает с `server_name` в nginx) как единственный доверенный origin; `www`-вариант добавляется только если по nginx-логам подтверждается живой трафик с него; доступ по IP `109.68.215.223` доверенным не делается. Правка вступает в силу только если P2-05 подтвердит 403 у реальных пользователей, иначе вопрос закрывается как ожидаемый шум сканеров.

---

# 5. Реестр задач и проверка перекрёстных ссылок

## Все task IDs

| Приоритет | ID | Название | Статус (на 2026-09-23) |
|---|---|---|---|
| P0 | P0-01 | Baseline: restore DB-дампа в scratch-БД | PASS |
| P0 | P0-02 | Baseline: restorability media-архива + строгая проверка на свежем тестовом архиве | PASS |
| P0 | P0-03 | Подтверждение доставки скриптов существующим CI/CD | PASS |
| P0 | P0-04 | Исправление перехвата stdout в `backup-db-telegram.sh` | PASS |
| P0 | P0-05 | Исправление перехвата stdout в `backup-media-telegram.sh` | PASS |
| P0 | P0-06 | Минимальная содержательная integrity verification | PASS |
| P0 | P0-07 | Exit code при провале integrity check | PASS |
| P0 | P0-08 | Status contract по стадиям | PASS |
| P0 | P0-09 | Немедленный E2E gate | PASS |
| P1 | P1-01 | Спека offsite-хранилища | **CANCELLED** |
| P1 | P1-02 | Выгрузка DB-дампа в offsite | **CANCELLED** |
| P1 | P1-03 | Выгрузка media-архива в offsite | **CANCELLED** |
| P1 | P1-04 | Проверяемость offsite-копий | **CANCELLED** |
| P1 | P1-05 | Retention локально (offsite-часть снята) | pending |
| P1 | P1-06 | Документировать принятую архитектуру (VK = внешняя копия) | pending |
| P1 | P1-07 | Диагностика недоступности Telegram + выбор канала | PASS |
| P1 | P1-08 | Мониторинг свежести бэкапа (dead man's switch) | pending |
| P1 | P1-09 | Периодический restore drill из offsite | **CANCELLED as specified** |
| P1 | P1-10 | VK — единственный практический канал уведомлений | PASS (основной scope) |
| P2 | P2-01 | `PaymentSchedule.clean()` и валидация обязательных полей | pending |
| P2 | P2-02 | Отсутствие `CommissionRate` insurer=17 / type=1 | pending |
| P2 | P2-03 | logrotate для cron-логов | pending |
| P2 | P2-04 | DEBUG-шум в `daily_digest` | pending |
| P2 | P2-05 | Классификация HTTP/CSRF/security warning'ов | pending |
| P2 | P2-06 | Housekeeping-опись мусора | pending |

Итого 25 задач: 9 × P0 (все PASS), 10 × P1 (4 CANCELLED, 2 PASS, 4 pending), 6 × P2 (все pending). Дубликатов ID нет, нумерация в каждой группе непрерывна (P0-01…P0-09, P1-01…P1-10, P2-01…P2-06). Отменённые задачи сохраняют номер в реестре — не переиспользуется и не удаляется, чтобы решение оставалось прослеживаемым.

## Проверка перекрёстных ссылок

- «Не входит» в P0-01 → P0-02 (media) ✓; P0-02 не ссылается на P0-01 как на зависимость ✓
- P0-04 → P0-03 ✓; P0-05 → P0-03, P0-04 ✓
- P0-06: зависимости P0-04, P0-05; ссылки на P0-01 / P0-09 / P1-09 как на владельца «полной восстанавливаемости» ✓
- P0-07 → P0-06; коды — D5 ✓
- P0-08 → P0-03, P0-07; поля `offsite` реализуются в P1-02/P1-03 (переключение `DB_REQUIRED_STAGES` / `MEDIA_REQUIRED_STAGES` — раздельно, только в этих задачах), проверяются в P1-04, наблюдаются в P1-08, drill — P1-09 ✓
- P0-09 → P0-04…P0-08 + методика P0-01; post-deploy observation закрыта в P1-08 ✓; `mirror`/`notify` в P0-09 — неблокирующий smoke test, его результат используется в P1-10 ✓
- P1-04 «Не входит» → **P1-09** (было ошибочно указано P1-08, исправлено) ✓
- P1-08 → P0-08, P1-02, P1-09, P1-10 ✓ (P1-09 выполняется раньше — она порождает артефакт давности drill, контроль которого входит в scope и acceptance P1-08; P1-10 поставляет рабочий канал алерта, P1-07 для P1-08 теперь только источник решения, а не зависимость доставки)
- P1-09 → P1-02, P1-04, методика P0-01/P0-02 ✓; пункт 6 scope P1-09 ↔ scope/acceptance P1-08 (артефакт drill) ✓
- P1-10 → P1-07 (выбор в Q2), P0-08 (поле `notify`) ✓; P1-07 «Не входит» ссылается на P1-10 ✓; P1-08 зависит от P1-10 ✓
- P1-06 опирается на контракт P0-08 и больше не меняет семантику полей ✓
- policy 526 упомянута только в P2-01 (как follow-up) и в P2-02/P2-05 отсутствует ✓
- Q-номера: в задачах встречаются только Q1, Q2, Q3, Q4, Q5, и все пять определены в разделе 3 ✓. Прежние инженерные вопросы (канал доставки, scratch-БД, формат статуса, место мониторинга, коды возврата, инструмент выгрузки, стратегия ротации, канонические host'ы) переведены в решения D1…D8 и ссылок на Q не имеют ✓

## Обновления после рев. 4 (решение владельца, 2026-09-23)

Приведённая выше сверка описывает исходный план и оставлена как есть — историю решений не переписываем. Актуальные поправки:

- P1-01…P1-04, P1-09 — CANCELLED; все зависимости на них выше (в P0-06, P0-08, P0-09, P1-04, P1-08, P1-09) остаются верными как описание *исходного* плана, но более не действуют.
- P0-06/P0-09 «владелец полной восстанавливаемости» — теперь это только P0-01 (baseline) и P0-09 (разовый E2E-drill, выполнен 2026-09-22); P1-09 из числа таких владельцев выбывает.
- P0-08 поле `offsite` — переключение `DB_REQUIRED_STAGES`/`MEDIA_REQUIRED_STAGES` в `created,verified,offsite`, которое планировалось в P1-02/P1-03, не произойдёт, пока решение владельца не будет пересмотрено; `offsite` остаётся `-`/`null` бессрочно.
- P1-08 зависимости сокращены до **P0-08, P1-10** (было: + P1-02, P1-09); контроль давности drill-артефакта убран из scope P1-08 вместе с P1-09.
- P1-04 «Не входит → P1-09» — обе задачи CANCELLED, ссылка более не действует.
- P1-06 теперь опирается на P0-08 и P1-05, а не на P1-02 — задача документирует принятый риск, а не будущий offsite.
- P1-07 → P1-10: связь не изменилась, но обе стороны Q2 теперь закрыты решением, а не открытым выбором.

---

# 6. Статус выполнения

По состоянию на 2026-09-22 (закрытие ветки P0 после E2E-гейта P0-09):

| ID | Статус |
|---|---|
| P0-01 | PASS (baseline restore, 2026-09-19) |
| P0-02 | PASS (baseline restorability, 2026-09-19) |
| P0-03 | PASS (CI/CD-канал подтверждён, 2026-09-19) |
| P0-04 | PASS / deployed (`42f2769`), cron-наблюдение закрыто 21.09 |
| P0-05 | PASS / deployed (`42f2769`), cron-наблюдение закрыто 21.09 |
| P0-06 | PASS / deployed (`504d178`), cron-наблюдение закрыто 21.09 |
| P0-07 | PASS / deployed (`504d178`) |
| P0-08 | PASS / deployed (`f7376b6`, run 35643934361, production smoke 2026-09-21) |
| P0-09 | PASS / final E2E gate completed 2026-09-22 (на коде `f7376b6`: real DB/media isolated backup, status contract, fresh dump restore drill, extraction/manifest sanity, negative fixture + full-flow exit 2, production unchanged, cleanup) |
| P1-01…P1-04, P1-09 | **CANCELLED (владелец, 2026-09-23)** — решение не строить отдельное offsite-хранилище |
| P1-07 | **PASS (2026-09-23)** — диагностика + решение владельца по Q2 |
| P1-10 | **PASS (2026-09-23)** — основной scope закрыт, см. статус P1-10 |
| P1-05, P1-06, P1-08 | pending, объём пересмотрен под решение владельца (см. рев. 4) |
| P2-01…P2-06 | pending |

## P0 — CLOSED (2026-09-22)

**P0 closure baseline: production commit `f7376b6`** (P0-09 — validation-only, production code не изменял).

Ветка P0 достигла цели: локальный production backup-контур (`insurance_broker`) теперь имеет:

- воспроизводимое создание DB/media backup (stdout-контракты P0-04/P0-05, cron-циклы работают);
- содержательную nightly integrity verification (P0-06: gzip/tar, PostgreSQL header/completion marker, cross-check с `.meta`);
- machine-readable exit semantics (P0-07: `0/1/2/3/4` по таблице D5, suspect-артефакт сохраняется);
- атомарный `last_status.json` и ровно одну финальную строку `BACKUP_RESULT` (P0-08);
- корректный порядок outcome-уведомлений (P0-08: success — только после верификации; ложный success невозможен);
- независимые required-stage контракты для DB и media (`DB_REQUIRED_STAGES` / `MEDIA_REQUIRED_STAGES`);
- подтверждённый restore DB-дампа, созданного исправленным кодом (P0-09 restore drill в scratch-БД: схема/PK/FK/индексы/counts/orphan-sanity — чисто);
- подтверждённую extraction media-архива (P0-09: 227 файлов, exact SHA256 manifest live volume ↔ архив).

E2E-гейт P0-09 проходил на production-инфраструктуре изолированно (stub notification-слой, отдельные `BACKUP_DIR`): реальной notification-сетевой активности не было, боевые каталоги и хеши существующих backups не изменились, scratch/temp ресурсы удалены.

### Что сознательно остаётся за P0 (переход в P1)

- Независимое durable offsite-хранение backup-артефактов отсутствует: `offsite=null` на текущем baseline — **ожидаемое состояние**, а не дефект; мессенджер-зеркало (VK/Telegram file delivery) offsite **не** является и никогда не установит `offsite=1`.
- **Обновление 2026-09-23:** владелец решил не закрывать этот пробел отдельным хранилищем — VK-зеркало осознанно принято как единственная внешняя копия на этом этапе (см. рев. 4 наверху документа). Следствия:
  - **P1-01…P1-04 (провайдер, upload, retention и проверяемость offsite-копии) — CANCELLED.** `offsite` остаётся `-`/`null` бессрочно, `DB_REQUIRED_STAGES`/`MEDIA_REQUIRED_STAGES` не переключаются.
  - **P1-09 (периодический drill из offsite) — CANCELLED as specified.** Разовый эквивалент восстанавливаемости уже подтверждён в P0-09 (2026-09-22).
  - **P1-05** сокращена до пересмотра локального retention (единственная гарантированная страховка без offsite).
  - **P1-06** теперь документирует принятый риск VK-как-единственной-копии, а не мотивирует будущий offsite.
- Мониторинг и hardening доставки уведомлений (Telegram мёртв, VK — единственный живой канал) → **P1-10 (PASS, 2026-09-23)**: конкретный пробел (cron health-check слал только `--notify-telegram`) закрыт на сервере и в репозитории; диагностика/выбор канала — **P1-07 (PASS)**. Отдельно остался открытым side finding про приоритет env-переменных в `telegram-config.sh` (см. статус P1-10) — не блокирует работу VK-канала.
- Контроль свежести `last_status.json` (dead man's switch, без зависимости от drill-артефакта — P1-09 отменена), а также post-deploy cron-наблюдение (первый плановый media-прогон под `f7376b6` — понедельник 28.09 03:00 MSK) → **P1-08**.

### Фактическое cron-расписание (на момент закрытия P0, не менялось)

- DB backup — ежедневно **02:00 MSK**;
- media backup — понедельник **03:00 MSK** (`0 3 * * 1`; комментарий «Weekly on Sunday» в crontab — известная описка, выражение = понедельник);
- cleanup — понедельник 04:00 MSK.

Следующий шаг: старт P1 по согласованию. Этот docs-only коммит (`P0 closure`) не пушится в `origin/main` намеренно: push docs-only коммита в `main` запускает полный production deployment; он уйдёт вместе со следующим согласованным functional push.
