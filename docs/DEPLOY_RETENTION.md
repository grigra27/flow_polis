# Хранение релизов Onlinepolis

Административная очистка установлена на `ssh polis` отдельно от ограниченного
CI-контроллера. Исходники: `scripts/deploy/retention.py` и `retention.cron`.

Каждый час, в 17 минут, сохраняются шесть последних verified-релизов
(текущий и пять предыдущих). Дополнительно сохраняются релизы, соответствующие
образам любых контейнеров, и все незавершённые/неуспешные релизы. Образы из
`snapshot.json` сохранённых релизов защищены, поэтому полный сценарий отката
остаётся доступным; фактическое число образов может превышать шесть.

У старых verified-релизов удаляются каталоги с архивами/метаданными и старые теги
`insurance-broker:<revision>-<run>` и `onlinepolis-rollback:<run>-<service>`.
Теги других проектов, специальные legacy-теги, volumes, БД, media, logs,
резервные копии и build cache не очищаются. Запуск не перезапускает контейнеры.

Скрипт берёт `/root/.local/state/onlinepolis-deploy.lock`, как основной контроллер,
и пропускает запуск, если блокировка занята. При неожиданных файлах,
небезопасных правах или отсутствии образов для сохранённых сценариев отката
очистка прекращается. `docker image rm` используется без `--force`.

Просмотр плана и ручной запуск от root:

```sh
/usr/local/sbin/onlinepolis-deploy-retention
/usr/local/sbin/onlinepolis-deploy-retention --apply
journalctl -t onlinepolis-retention
```

Административная установка из проверенного checkout (не из CI):

```sh
install -o root -g root -m 0700 scripts/deploy/retention.py /usr/local/sbin/onlinepolis-deploy-retention
install -o root -g root -m 0644 scripts/deploy/retention.cron /etc/cron.d/onlinepolis-deploy-retention
```

Для отключения расписания убрать `/etc/cron.d/onlinepolis-deploy-retention`.
Удалённые старые релизы не входят в доступное локальное окно отката.
Приложение и ограниченный SSH-протокол деплоя не меняются.

Проверка политики: `./venv/bin/pytest -q tests/test_deploy_retention.py`.
