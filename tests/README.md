# Тесты

Сверено с `pytest.ini`, `config/test_settings.py`, workflow и тестовыми
фикстурами 2026-11-11. [Общее оглавление](../docs/README.md).

Один способ запуска — **pytest** (его же запускает CI перед деплоем):

```bash
pytest                                   # весь набор
pytest apps/policies/tests/test_in_force.py
pytest -m unit                           # маркеры: unit, integration, property, slow, migration, admin
```

`python manage.py test` не используйте: стандартный раннер Django не запускает
pytest-функции с фикстурами и не собирает весь набор проекта.

## Где лежат тесты

- `apps/<app>/tests.py`, `apps/<app>/tests/test_*.py`, `apps/<app>/test_*.py` — тесты приложения;
- `tests/test_*.py` — сквозные тесты (аналитика, отчёты, регрессия портфеля);
- `config/tests/` — настройки, заголовки безопасности, nginx.

`pytest.ini` собирает файлы `tests.py`, `test_*.py`, `*_test.py`. Файл с другим
именем pytest молча пропустит — и CI тоже.

## Правила, чтобы тесты не ломались сами

1. **Нет «мин» с датами.** Если результат зависит от сегодняшнего дня
   («в силе», «просрочено», «текущий год»), задавайте даты относительно
   `timezone.localdate()` или передавайте `today` в сервис явно. Фиксированная
   дата, которая когда-нибудь пройдёт, рано или поздно уронит тест.
2. **Проверяйте на других датах** после изменений, зависящих от времени:

   ```bash
   pip install time-machine
   for d in 2027-01-01 "2027-01-01 00:20 +0300" 2028-02-29 2030-06-01; do
       TEST_NOW="$d" pytest -q -p tests.plugins.timetravel
   done
   ```

3. **Тестовые данные — через график платежей.** Премия, КВ и страховая сумма
   полиса считаются из `PaymentSchedule`; полис без платежей — это полис с
   нулевой премией.
4. **Hypothesis и база.** Стратегии текста, который сохраняется в БД, — без
   NUL и одиночных суррогатов: `st.characters(blacklist_characters="\x00",
   blacklist_categories=("Cs",))`.
5. **Изменили поведение — поправьте тест в том же коммите.** Не подгоняйте тест
   под ошибку: если тест упал, сначала решите, кто прав.


## Фикстуры полисов

В [apps/policies/tests/conftest.py](../apps/policies/tests/conftest.py) находятся
factory fixtures для клиента, СК, филиала, вида страхования, ставки,
лизингового менеджера, полиса и платежа; также есть sample-объекты и admin user.
Используйте фактические имена/поля из этого файла, а не копии примеров старого
README. Тесты моделей, admin, импорта и inline уже находятся рядом с фикстурами.

## Миграции и production-образ

Обычная suite отключает миграции через `DisableMigrations` в
[config/test_settings.py](../config/test_settings.py).
[tests/test_migration_bootstrap.py](test_migration_bootstrap.py) отдельно
запускает реальный граф исторических миграций в subprocess на пустой SQLite,
без сетевых обращений и без чтения runtime `.env`.

CI дополнительно выполняет bootstrap/migrate/фикстуры/check/static на отдельной
PostgreSQL 15 в готовом production-образе и проверяет Redis broker round trip.
Эти проверки не заменяются обычным быстрым pytest на SQLite.
[Workflow](../.github/workflows/deploy.yml).

## Shell-скрипты

Проверки backup/status/retention/logrotate находятся в
[scripts/tests/](../scripts/tests/). Запускайте их через bash, например:

```bash
bash scripts/tests/test-backup-retention.sh
bash scripts/tests/test-backup-status-contract.sh
bash scripts/tests/test-backup-integrity-verification.sh
```

Это изолированные тесты со своими временными данными; обычные backup, deploy
и setup-скрипты хоста не следует запускать как часть проверки документации.
