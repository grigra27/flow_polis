# Технический план реализации почтового контура MVP

Дата: 2026-05-11.

Базовый продуктовый документ: `docs/improvement plans/email-communications-plan.md`.

## 1. Цель MVP

Реализовать первый технический MVP почтового контура для блока "Очередные взносы".

MVP должен позволить суперпользователю отправлять из карточки задачи очередного взноса два уже существующих типа писем:

- письмо в страховую компанию с запросом счета;
- письмо в Альянс-лизинг с передачей счета в оплату.

Получатель на первом этапе вводится вручную в интерфейсе. Автоподбор адресов страховых компаний, менеджеров Альянса, филиалов и копий не входит в MVP.

Обычные пользователи на время тестирования продолжают работать по старой схеме: копируют тему и текст письма и отправляют письмо вручную через почтовый клиент. Кнопка отправки из системы видна только суперпользователю.

## 2. Scope первого релиза

Входит в MVP:

- новое приложение `apps.communications`;
- модели исходящих писем, получателей, вложений и попыток отправки;
- SMTP provider для отправки через общий системный ящик;
- Celery-задача отправки письма;
- ручной ввод email-получателя в карточке `BillingTask`;
- отправка письма в СК;
- отправка письма в Альянс;
- обязательное вложение для письма в Альянс;
- сохранение snapshot темы, текста, HTML, получателей и вложений;
- история попыток отправки;
- автоматическое изменение статуса `BillingTask` после успешной отправки;
- защита от повторной отправки одного и того же письма;
- тесты на модели, сервисы, views и Celery-задачу.

Не входит в MVP:

- четверговый отчет;
- входящий IMAP-контур;
- автоматическое сопоставление ответов;
- автоматическая загрузка счетов из входящих писем;
- автоподбор email-адресов СК/Альянса;
- личные ящики сотрудников;
- сохранение копии письма в папку Sent;
- редактирование темы и тела письма перед отправкой;
- отправка писем обычными пользователями.

## 3. Общий принцип интеграции

`apps.billing` остается владельцем бизнес-смысла:

- какое письмо нужно создать;
- по какой задаче;
- какой текст и тема используются;
- какой статус задачи нужно поставить после успешной отправки.

`apps.communications` становится владельцем почтовой инфраструктуры:

- хранение письма;
- хранение получателей;
- хранение вложений;
- постановка в очередь;
- отправка через SMTP;
- фиксация результата;
- повторные попытки;
- служебные заголовки и технические маркеры.

Бизнес-код `billing` не должен напрямую работать с SMTP, `EmailMessage`, Яндексом, Gmail или Zimbra.

## 4. Новое приложение `apps.communications`

### 4.1 Создать структуру

```text
apps/communications/
  __init__.py
  admin.py
  apps.py
  models.py
  services.py
  tasks.py
  urls.py
  views.py
  forms.py
  validators.py
  providers/
    __init__.py
    base.py
    smtp.py
  migrations/
    __init__.py
  tests/
    __init__.py
    test_models.py
    test_services.py
    test_tasks.py
    test_views.py
```

`urls.py` можно добавить сразу, но на первом этапе отдельные публичные страницы `communications` не обязательны. Если не будет отдельных страниц, URLs можно оставить пустыми или не подключать до появления списка писем.

### 4.2 Добавить приложение в настройки

В `config/settings.py` добавить:

```python
INSTALLED_APPS = [
    ...
    "apps.communications",
]
```

Разместить приложение рядом с локальными apps, логически после `apps.notifications` или перед `apps.billing`.

## 5. Настройки окружения

Нужен отдельный набор настроек для нового почтового контура, чтобы не смешивать его с текущими Django `EMAIL_*`, которые уже используются для старых уведомлений.

Добавить в `config/settings.py`:

```python
COMMUNICATIONS_EMAIL_ENABLED = config(
    "COMMUNICATIONS_EMAIL_ENABLED", default=False, cast=bool
)
COMMUNICATIONS_DEFAULT_ACCOUNT = config(
    "COMMUNICATIONS_DEFAULT_ACCOUNT", default="billing"
)
COMMUNICATIONS_SMTP_HOST = config("COMMUNICATIONS_SMTP_HOST", default="")
COMMUNICATIONS_SMTP_PORT = config("COMMUNICATIONS_SMTP_PORT", default=465, cast=int)
COMMUNICATIONS_SMTP_USE_TLS = config(
    "COMMUNICATIONS_SMTP_USE_TLS", default=False, cast=bool
)
COMMUNICATIONS_SMTP_USE_SSL = config(
    "COMMUNICATIONS_SMTP_USE_SSL", default=True, cast=bool
)
COMMUNICATIONS_SMTP_USERNAME = config("COMMUNICATIONS_SMTP_USERNAME", default="")
COMMUNICATIONS_SMTP_PASSWORD = config("COMMUNICATIONS_SMTP_PASSWORD", default="")
COMMUNICATIONS_FROM_EMAIL = config("COMMUNICATIONS_FROM_EMAIL", default="")
COMMUNICATIONS_FROM_NAME = config("COMMUNICATIONS_FROM_NAME", default="")
COMMUNICATIONS_MESSAGE_ID_DOMAIN = config(
    "COMMUNICATIONS_MESSAGE_ID_DOMAIN", default=""
)
COMMUNICATIONS_ATTACHMENT_MAX_SIZE_MB = config(
    "COMMUNICATIONS_ATTACHMENT_MAX_SIZE_MB", default=10, cast=int
)
COMMUNICATIONS_SEND_TIMEOUT = config(
    "COMMUNICATIONS_SEND_TIMEOUT", default=30, cast=int
)
```

Для staging на Яндекс.Почте:

```text
COMMUNICATIONS_EMAIL_ENABLED=True
COMMUNICATIONS_DEFAULT_ACCOUNT=billing
COMMUNICATIONS_SMTP_HOST=smtp.yandex.com
COMMUNICATIONS_SMTP_PORT=465
COMMUNICATIONS_SMTP_USE_SSL=True
COMMUNICATIONS_SMTP_USE_TLS=False
COMMUNICATIONS_SMTP_USERNAME=test-mailbox@yandex.ru
COMMUNICATIONS_SMTP_PASSWORD=...
COMMUNICATIONS_FROM_EMAIL=test-mailbox@yandex.ru
COMMUNICATIONS_FROM_NAME=ОнлайнПолис
COMMUNICATIONS_MESSAGE_ID_DOMAIN=onlinepolis.local
```

Для production на Zimbra значения будут заменены на настройки Zimbra.

Важно: пароль тестового или боевого ящика не хранить в репозитории.

## 6. Модели данных

### 6.1 `MailAccount`

Для MVP можно сделать модель аккаунта, но фактические секреты брать из settings. Это оставляет место для будущих нескольких ящиков, но не заставляет хранить пароль в БД.

Поля:

```python
class MailAccount(TimeStampedModel):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=255)
    email = models.EmailField()
    display_name = models.CharField(max_length=255, blank=True)
    provider = models.CharField(max_length=50, default="smtp")
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    settings_prefix = models.CharField(max_length=100, default="COMMUNICATIONS")
```

Индексы:

- `code`;
- `is_active`;
- `is_default`.

Для первого релиза можно создать аккаунт через data migration или management command. Более простой путь: сервис `get_default_account()` создает/возвращает `MailAccount` с `code=settings.COMMUNICATIONS_DEFAULT_ACCOUNT`, если его еще нет.

### 6.2 `OutboundEmail`

Поля:

```python
class OutboundEmail(TimeStampedModel):
    KIND_BILLING_INSURER_REQUEST = "billing_insurer_request"
    KIND_BILLING_ALLIANCE_FORWARD = "billing_alliance_forward"

    STATUS_DRAFT = "draft"
    STATUS_QUEUED = "queued"
    STATUS_SENDING = "sending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    account = models.ForeignKey(MailAccount, on_delete=models.PROTECT)
    kind = models.CharField(max_length=80, db_index=True)
    status = models.CharField(max_length=30, default=STATUS_DRAFT, db_index=True)

    from_email = models.EmailField()
    from_name = models.CharField(max_length=255, blank=True)
    reply_to = models.EmailField(blank=True)

    subject = models.CharField(max_length=500)
    body_text = models.TextField()
    body_html = models.TextField(blank=True)

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_outbound_emails",
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_outbound_emails",
    )

    queued_at = models.DateTimeField(null=True, blank=True)
    sending_started_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    message_id = models.CharField(max_length=255, blank=True, db_index=True)
    provider_message_id = models.CharField(max_length=255, blank=True)
    headers = models.JSONField(default=dict, blank=True)
```

Индексы:

- `status`;
- `kind`;
- `created_at`;
- `sent_at`;
- `content_type`, `object_id`;
- `message_id`.

Ограничения:

- запрещать перевод `sent` обратно в `queued` обычным сервисом;
- `subject` и `body_text` обязательны;
- должен быть хотя бы один `to` получатель перед постановкой в очередь.

### 6.3 `OutboundEmailRecipient`

Поля:

```python
class OutboundEmailRecipient(TimeStampedModel):
    TYPE_TO = "to"
    TYPE_CC = "cc"
    TYPE_BCC = "bcc"

    email = models.ForeignKey(
        OutboundEmail,
        on_delete=models.CASCADE,
        related_name="recipients",
    )
    recipient_type = models.CharField(max_length=10, default=TYPE_TO)
    address = models.EmailField()
    name = models.CharField(max_length=255, blank=True)
```

Индексы:

- `email`, `recipient_type`;
- `address`.

На первом этапе UI создает только `to`, но модель сразу поддерживает `cc/bcc`.

### 6.4 `OutboundEmailAttachment`

Поля:

```python
class OutboundEmailAttachment(TimeStampedModel):
    email = models.ForeignKey(
        OutboundEmail,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(upload_to="communications/outbound/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255, blank=True)
    size = models.PositiveIntegerField(default=0)
    checksum = models.CharField(max_length=64, blank=True)
```

Для MVP attachment нужен прежде всего для письма в Альянс.

### 6.5 `EmailDeliveryAttempt`

Поля:

```python
class EmailDeliveryAttempt(TimeStampedModel):
    email = models.ForeignKey(
        OutboundEmail,
        on_delete=models.CASCADE,
        related_name="delivery_attempts",
    )
    attempt_number = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=30)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    provider_response = models.TextField(blank=True)
```

Индексы:

- `email`, `attempt_number`;
- `status`;
- `created_at`.

## 7. Валидатор вложений

В проекте уже есть `apps.core.file_validators.FileUploadValidator`, но он сейчас разрешает `jpg`, `jpeg`, `png`, `pdf`, `xlsx`, `xls`. Для MVP нужны еще `doc` и `docx`.

Чтобы не менять поведение всех существующих загрузок, лучше создать отдельный валидатор:

```text
apps/communications/validators.py
```

Разрешения:

- `pdf`;
- `jpg`;
- `jpeg`;
- `png`;
- `doc`;
- `docx`;
- `xls`;
- `xlsx`.

Лимит:

- по умолчанию 10 MB;
- читать из `COMMUNICATIONS_ATTACHMENT_MAX_SIZE_MB`.

Проверки:

- расширение из whitelist;
- размер больше 0;
- размер не превышает лимит;
- безопасное имя файла;
- checksum SHA-256.

Для `doc/docx` на первом этапе можно ограничиться extension + size + безопасное имя, если нет надежной MIME/magic-byte проверки. Это стоит явно покрыть тестами и логировать отклонения.

## 8. Provider-слой

### 8.1 Базовый интерфейс

`apps/communications/providers/base.py`:

```python
class BaseEmailProvider:
    def send(self, outbound_email: OutboundEmail) -> SendResult:
        raise NotImplementedError
```

`SendResult`:

```python
@dataclass
class SendResult:
    success: bool
    provider_message_id: str = ""
    response: str = ""
```

### 8.2 SMTP provider

`apps/communications/providers/smtp.py`.

Реализация через Django:

- `django.core.mail.get_connection`;
- `EmailMultiAlternatives`;
- `attach_alternative` для HTML;
- `attach_file` или `attach(filename, content, mimetype)`;
- `headers` для служебных заголовков.

Пример логики:

1. Собрать `to`, `cc`, `bcc`.
2. Создать connection из `settings.COMMUNICATIONS_*`.
3. Создать `EmailMultiAlternatives`.
4. Добавить HTML alternative, если есть.
5. Добавить вложения.
6. Добавить headers:
   - `Message-ID`;
   - `X-Onlinepolis-Object`;
   - `X-Onlinepolis-Email-Kind`.
7. Отправить.
8. Вернуть `SendResult`.

Важно: `fail_silently=False`.

## 9. Сервисный слой `apps.communications`

### 9.1 `create_outbound_email`

Создает письмо и snapshot.

Вход:

- `kind`;
- `content_object`;
- `subject`;
- `body_text`;
- `body_html`;
- `to`;
- `created_by`;
- `attachments`.

Логика:

- получить default account;
- определить `from_email` и `from_name`;
- сгенерировать `message_id`;
- добавить технический блок в тело письма;
- создать `OutboundEmail`;
- создать `OutboundEmailRecipient`;
- сохранить вложения;
- вернуть письмо.

### 9.2 `queue_outbound_email`

Переводит письмо в `queued` и ставит Celery-задачу.

Проверки:

- письмо не `sent`;
- письмо не `queued`;
- письмо не `sending`;
- есть хотя бы один `to`;
- `COMMUNICATIONS_EMAIL_ENABLED=True`;
- для `billing_alliance_forward` есть хотя бы одно вложение.

Логика:

- транзакция;
- `select_for_update`;
- статус `queued`;
- `queued_at=timezone.now()`;
- создать delivery attempt или подготовить номер попытки;
- вызвать `send_outbound_email.delay(email.id)`.

### 9.3 `send_outbound_email_now`

Используется Celery-задачей.

Логика:

- транзакционно взять письмо `select_for_update`;
- убедиться, что статус `queued` или допустимый `failed` retry;
- перевести в `sending`;
- создать `EmailDeliveryAttempt`;
- вызвать provider;
- при успехе:
  - `status=sent`;
  - `sent_at=now`;
  - сохранить `provider_message_id`;
  - закрыть attempt успехом;
  - вызвать hook бизнес-объекта;
- при ошибке:
  - `status=failed`;
  - `failed_at=now`;
  - `last_error`;
  - закрыть attempt ошибкой;
  - не менять бизнес-статус.

### 9.4 Hook после успешной отправки

Нужен простой dispatch:

```python
def handle_outbound_email_sent(email):
    if email.kind in billing kinds:
        apps.billing.mail_handlers.handle_billing_email_sent(email)
```

Альтернатива: Django signal `outbound_email_sent`. Для MVP проще явный service dispatch, его легче тестировать.

## 10. Интеграция с `apps.billing`

### 10.1 Новый файл `apps/billing/mail_builders.py`

Сервисы:

```python
def build_insurer_request_email_payload(task: BillingTask, recipient_email: str) -> dict
def build_alliance_forward_email_payload(task: BillingTask, recipient_email: str) -> dict
```

Для СК:

- `kind=billing_insurer_request`;
- `subject=task.build_letter_subject()`;
- `body_text=task.build_letter_text()`;
- `body_html=task.build_letter_html()`.

Для Альянса:

- `kind=billing_alliance_forward`;
- `subject=task.build_alliance_letter_subject()`;
- `body_text=task.build_alliance_letter_text()`;
- `body_html=task.build_alliance_letter_html()`;
- обязательное вложение счета.

### 10.2 Технический код в теле

Тему письма не менять.

В тело письма при создании `OutboundEmail` добавить служебный блок:

```text

---
Код запроса: OP-BILLING-{task_id}
```

Для HTML:

```html
<hr>
<p><small>Код запроса: OP-BILLING-{task_id}</small></p>
```

Код должен добавляться только к snapshot исходящего письма, а не менять методы `BillingTask.build_letter_text()` напрямую. Так текущие кнопки копирования останутся с прежним текстом, если это желательно. Если нужно, чтобы копируемый текст тоже содержал код, это отдельное решение.

### 10.3 Hook успешной отправки

`apps/billing/mail_handlers.py`:

```python
def handle_billing_email_sent(email: OutboundEmail) -> None:
    task = email.content_object
    if email.kind == OutboundEmail.KIND_BILLING_INSURER_REQUEST:
        update_task(task, email.sent_by, new_status=BillingTask.STATUS_REQUESTED)
    elif email.kind == OutboundEmail.KIND_BILLING_ALLIANCE_FORWARD:
        update_task(task, email.sent_by, new_status=BillingTask.STATUS_SENT_TO_LEASING)
```

Если `sent_by` пустой, fallback на `created_by`.

## 11. Views и URLs

### 11.1 Новые URLs в `apps.policies.urls`

Так как карточка задачи живет в `policies` namespace, проще добавить routes туда:

```python
path(
    "payments/scheduled/tasks/<int:pk>/send-insurer-email/",
    billing_views.BillingTaskSendInsurerEmailView.as_view(),
    name="scheduled_payment_send_insurer_email",
),
path(
    "payments/scheduled/tasks/<int:pk>/send-alliance-email/",
    billing_views.BillingTaskSendAllianceEmailView.as_view(),
    name="scheduled_payment_send_alliance_email",
),
```

### 11.2 `BillingTaskSendInsurerEmailView`

Только POST.

Доступ:

- `LoginRequiredMixin`;
- проверка `request.user.is_superuser`;
- если не superuser, вернуть 403 или redirect с warning.

Поля POST:

- `recipient_email`;
- `next`.

Логика:

1. Получить `BillingTask` с теми же `select_related`, что detail view.
2. Проверить `recipient_email` через Django `EmailField`/form.
3. Создать `OutboundEmail`.
4. Поставить в очередь.
5. Показать success message: письмо поставлено в очередь.
6. Redirect обратно на detail.

### 11.3 `BillingTaskSendAllianceEmailView`

Только POST.

Доступ:

- только superuser.

Поля POST:

- `recipient_email`;
- `invoice_file`;
- `next`.

Логика:

1. Проверить email.
2. Проверить наличие файла.
3. Провалидировать файл через `communications.validators`.
4. Создать `OutboundEmail` с вложением.
5. Поставить в очередь.
6. Redirect обратно на detail.

### 11.4 Forms

Можно сделать в `apps/billing/forms.py`:

```python
class ManualRecipientEmailForm(forms.Form):
    recipient_email = forms.EmailField(label="Email получателя")

class AllianceEmailForm(ManualRecipientEmailForm):
    invoice_file = forms.FileField(label="Счет")
```

Файловая форма использует communications attachment validator.

## 12. UI в `billing/task_detail.html`

### 12.1 СК

В блоке письма в страховую:

- оставить текущие кнопки "Скопировать тему" и "Скопировать текст";
- для `request.user.is_superuser` показать форму отправки:
  - email получателя;
  - кнопка "Отправить в СК";
  - текстовый статус, что отправка идет с системного ящика;
  - тема и текст остаются read-only.

Форма:

```html
<form method="post" action="{% url 'policies:scheduled_payment_send_insurer_email' task.pk %}">
  {% csrf_token %}
  <input type="email" name="recipient_email" required>
  <input type="hidden" name="next" value="{{ request.get_full_path }}">
  <button type="submit">Отправить в СК</button>
</form>
```

### 12.2 Альянс

В блоке письма в Альянс:

- оставить кнопки копирования;
- для superuser показать форму:
  - email получателя;
  - upload файла счета;
  - кнопка "Отправить в Альянс".

Форма должна иметь:

```html
enctype="multipart/form-data"
```

### 12.3 История писем

В detail context добавить последние исходящие письма по задаче:

```python
outbound_emails = OutboundEmail.objects.for_object(task).prefetch_related(
    "recipients",
    "attachments",
    "delivery_attempts",
)
```

В UI показать компактный блок:

- тип письма;
- статус;
- получатель;
- дата создания;
- дата отправки;
- последняя ошибка, если есть.

Для MVP достаточно read-only истории на карточке задачи.

## 13. Celery task

`apps/communications/tasks.py`:

```python
@shared_task(bind=True, max_retries=0)
def send_outbound_email(self, email_id):
    return send_outbound_email_now(email_id)
```

На первом этапе автоматические retries лучше не включать, чтобы случайно не плодить повторные отправки. Повторная отправка - ручная кнопка после анализа ошибки.

Позже можно добавить controlled retry для технических transient-ошибок.

## 14. Admin

Зарегистрировать модели:

- `MailAccount`;
- `OutboundEmail`;
- `OutboundEmailRecipient`;
- `OutboundEmailAttachment`;
- `EmailDeliveryAttempt`.

Для `OutboundEmailAdmin`:

- `list_display`: id, kind, status, subject, from_email, created_by, sent_at, created_at;
- `list_filter`: kind, status, account, created_at, sent_at;
- `search_fields`: subject, recipients address, message_id;
- readonly для тела, headers, дат и ошибок после отправки;
- inline recipients;
- inline attachments;
- inline attempts.

## 15. Idempotency и защита от дублей

Нужно предотвратить повторную отправку одного письма:

- queue-сервис блокирует письмо через `select_for_update`;
- нельзя queue, если `status in (queued, sending, sent)`;
- повторная отправка failed-письма должна идти через отдельный retry service;
- кнопка в UI после POST делает redirect;
- Celery task повторно проверяет статус перед отправкой.

Можно дополнительно добавить поле:

```python
dedupe_key = models.CharField(max_length=255, blank=True, db_index=True)
```

Но для MVP это не обязательно, потому что каждое нажатие superuser сознательно создает новое письмо. Главное - не отправить одно созданное письмо дважды.

## 16. Статусы `BillingTask`

После успешной отправки:

- `billing_insurer_request` -> `BillingTask.STATUS_REQUESTED`;
- `billing_alliance_forward` -> `BillingTask.STATUS_SENT_TO_LEASING`.

Если задача уже в нужном или более позднем статусе:

- не откатывать статус назад;
- событие письма все равно оставить в истории email;
- `update_task` уже не должен создавать лишнее событие, если статус не изменился.

Ошибка отправки:

- не меняет `BillingTask.status`;
- сохраняет ошибку в `OutboundEmail.last_error`;
- показывает message пользователю на следующем открытии страницы.

## 17. Тестовый план

### 17.1 Unit tests `communications`

Модели:

- создается `MailAccount`;
- создается `OutboundEmail` с generic relation на `BillingTask`;
- создаются recipients;
- создаются attachments;
- статусы и indexes не ломают миграции.

Сервисы:

- `create_outbound_email` создает snapshot;
- добавляет ручного получателя;
- добавляет технический код в тело;
- генерирует `Message-ID`;
- `queue_outbound_email` запрещает письмо без получателя;
- `queue_outbound_email` запрещает отправку при `COMMUNICATIONS_EMAIL_ENABLED=False`;
- `queue_outbound_email` запрещает повторную постановку `sent` письма;
- `billing_alliance_forward` без attachment не ставится в очередь.

Provider:

- мокнуть Django email backend;
- проверить `to`;
- проверить `subject`;
- проверить `body`;
- проверить HTML alternative;
- проверить custom headers;
- проверить attachment.

Celery:

- успешная отправка переводит статус в `sent`;
- ошибка provider переводит статус в `failed`;
- success вызывает billing hook;
- failed не вызывает billing hook.

### 17.2 Tests `billing`

Views:

- обычный пользователь не видит форму отправки;
- superuser видит форму отправки;
- обычный пользователь не может POST отправку;
- superuser может POST отправку в СК;
- invalid email дает warning/error;
- POST создает `OutboundEmail`;
- POST ставит письмо в очередь;
- POST в Альянс без файла отклоняется;
- POST в Альянс с разрешенным файлом создает attachment.

Статусы:

- успешная отправка письма в СК ставит `requested`;
- успешная отправка письма в Альянс ставит `sent_to_leasing`;
- failed письмо не меняет статус задачи.

Регрессии:

- текущие кнопки копирования остаются в HTML;
- текущие тесты генерации тем и текстов продолжают проходить.

### 17.3 Интеграционный smoke test

На staging:

1. Настроить тестовый Яндекс-ящик.
2. Включить `COMMUNICATIONS_EMAIL_ENABLED=True`.
3. Создать тестовую задачу очередного взноса.
4. Под суперпользователем отправить письмо в СК на свой тестовый email.
5. Проверить, что письмо пришло.
6. Проверить, что статус задачи поменялся.
7. Отправить письмо в Альянс с тестовым PDF.
8. Проверить вложение.
9. Проверить историю отправок.

## 18. Порядок реализации

### Шаг 1. Каркас приложения

- создать `apps/communications`;
- добавить в `INSTALLED_APPS`;
- создать базовые модели;
- создать миграции;
- зарегистрировать в admin.

### Шаг 2. Settings и default account

- добавить `COMMUNICATIONS_*` settings;
- реализовать `get_default_mail_account`;
- покрыть тестами дефолтные настройки.

### Шаг 3. Provider и сервисы

- реализовать SMTP provider;
- реализовать `create_outbound_email`;
- реализовать `queue_outbound_email`;
- реализовать `send_outbound_email_now`;
- реализовать Celery task;
- покрыть мок-тестами.

### Шаг 4. Billing integration services

- добавить `apps/billing/mail_builders.py`;
- добавить `apps/billing/mail_handlers.py`;
- добавить forms;
- добавить views отправки.

### Шаг 5. URLs и UI

- добавить routes в `apps/policies/urls.py`;
- обновить `task_detail.html`;
- добавить блок истории писем;
- убедиться, что формы видны только superuser.

### Шаг 6. Вложения для Альянса

- добавить attachment validator;
- подключить upload в форме;
- проверить multipart form;
- покрыть тестами.

### Шаг 7. Тесты и регрессии

- добавить tests для communications;
- расширить `apps/billing/test_billing_workflow.py`;
- запустить релевантные тесты:

```text
./venv/bin/python manage.py test apps.billing apps.communications
```

Если локальная БД требует env:

```text
DB_NAME='' SENTRY_DSN='' ./venv/bin/python manage.py test apps.billing apps.communications
```

### Шаг 8. Staging проверка

- добавить env для тестового Яндекс-ящика;
- создать/проверить superuser;
- отправить тестовые письма;
- зафиксировать результат.

## 19. Риски и решения

### Риск: письмо ушло дважды

Решение:

- статусная машина;
- `select_for_update`;
- запрет queue для `queued/sending/sent`;
- redirect после POST.

### Риск: письмо не ушло, а задача поменяла статус

Решение:

- менять `BillingTask` только в success hook после provider success.

### Риск: неправильный email получателя

Решение:

- Django `EmailField`;
- preview email перед кнопкой;
- на MVP ответственность за ручной ввод у superuser.

### Риск: вложение опасного типа

Решение:

- whitelist extensions;
- size limit;
- safe filename;
- checksum;
- отдельный communications validator.

### Риск: SMTP credentials попали в код

Решение:

- только env;
- не хранить пароль в `MailAccount`;
- добавить docs/env описание позже.

### Риск: обычные пользователи увидят экспериментальную отправку

Решение:

- UI condition `request.user.is_superuser`;
- server-side check в view;
- тест на POST обычным пользователем.

## 20. Что нужно будет получить перед staging

Для начала реализации кода эти данные не нужны, потому что можно тестировать с console/mocked backend.

Для staging-проверки понадобятся:

- адрес тестового Яндекс-ящика;
- пароль приложения или SMTP-пароль;
- SMTP host/port;
- SSL/TLS режим;
- email, на который можно отправлять тестовые письма;
- тестовый файл счета.

Для production позже понадобятся:

- Zimbra SMTP host;
- Zimbra SMTP port;
- SSL/TLS режим;
- логин и пароль системного ящика;
- From email;
- From display name;
- подтверждение SPF/DKIM/DMARC у администратора почты.

## 21. Критерии готовности MVP

MVP можно считать готовым, если:

- миграции применяются;
- superuser видит формы отправки в карточке очередного взноса;
- обычный пользователь не видит формы отправки;
- обычный пользователь не может отправить письмо POST-запросом;
- письмо в СК создается, ставится в очередь и отправляется;
- письмо в СК после успешной отправки меняет статус задачи на "Счет запрошен у СК";
- письмо в Альянс требует файл счета;
- письмо в Альянс с файлом отправляется;
- письмо в Альянс после успешной отправки меняет статус задачи на "Передан в оплату в Альянс";
- failed-отправка не меняет статус задачи;
- история писем видна в карточке задачи;
- старые кнопки копирования остались;
- тесты `apps.billing` и `apps.communications` проходят.

## 22. Пересмотренные требования по итогам ревью MVP

Эти разделы добавлены после ревью реализованного первого этапа. Они уточняют пункты §13 и §19, делают требования более строгими и закрывают пробелы, которые в плане были описаны слишком общими словами.

### S1. Status-machine: запрет отката статуса

Hook `apps.billing.mail_handlers.handle_billing_email_sent` должен сравнивать статус задачи по упорядоченному списку:

```text
to_request < requested < sent_to_leasing
```

Если целевой статус письма «ниже» текущего, hook не должен ничего менять. Это нужно из-за следующих сценариев:

- суперпользователь повторно отправляет письмо в СК уже после того, как задача переведена в `sent_to_leasing`;
- по одной задаче в разное время отправлены оба письма, и второй email-success приходит позже первого.

Реализация хранит ordinal-таблицу в `mail_handlers.py` и явно делает проверку перед `update_task`. Ordinal-таблица — единственный источник истины: не вычислять её по `BillingTask.STATUS_CHOICES`, потому что добавление новых статусов в `STATUS_CHOICES` (например, «отменён») не должно автоматически становиться «более поздним» состоянием.

### S2. Транзакционная фиксация постановки в Celery

`send_outbound_email.delay(...)` ставится через `transaction.on_commit`. Это гарантирует, что worker не получит ID письма до фиксации транзакции и не увидит «фантомные» строки. Соответствующее ограничение для тестов: pytest-тест, прогоняющий полный путь queue → delay, должен оборачиваться в `TestCase.captureOnCommitCallbacks(execute=True)`.

Тесты во view-слое monkey-patch'ат `queue_outbound_email` целиком — там on_commit не нужен.

### S3. Celery soft/hard time-limits

Для `apps.communications.tasks.send_outbound_email` рекомендуется:

```python
@shared_task(bind=True, max_retries=0, soft_time_limit=60, time_limit=120)
```

`COMMUNICATIONS_SEND_TIMEOUT` уже защищает SMTP-этап, но worker может зависнуть на чтении больших вложений, IMAP-копии в Sent (когда будет), DNS-резолве. На staging проверить, что hung worker корректно убивается без сохранения промежуточных статусов.

### S4. Permission-модель и feature flag

Жёсткая проверка `request.user.is_superuser` запрещена. Используем:

1. Django-permission `communications.send_outbound_email` (объявлена в `OutboundEmail.Meta.permissions`).
2. Feature flag `COMMUNICATIONS_RESTRICT_TO_SUPERUSER` (default=True). Пока он включён, доступ имеет только суперпользователь; при выключении доступ управляется permission'ом.

Helper `apps.billing.views.user_can_send_outbound_email(user)` — единственный источник истины и для server-side, и для template-условий (`can_send_outbound_email`). UI и view используют один и тот же helper, чтобы их состояния не расходились.

### S5. Защита от двойного клика на server side

`create_outbound_email` отказывает в создании нового письма того же `kind` для того же `content_object`, если в окне `RECENT_DUPLICATE_WINDOW` (60 секунд) уже есть письмо в статусе `draft/queued/sending/sent`. Это страхует JS-блокировку submit'а: даже если она не сработает, второй POST вернёт `CommunicationsQueueError` и пользователь увидит человекочитаемое сообщение.

Окно умеренно широкое (60 сек), потому что:

- двойной клик — это секунды;
- ретрансмит браузера — это секунды;
- сетевые таймауты на reverse proxy — это секунды;
- но через минуту повторная сознательная отправка уже возможна.

### S6. Retry для failed-писем

Failed-письмо ставится обратно в очередь через сервис `retry_outbound_email`. Он:

- разрешает retry только из статуса `failed`;
- проверяет наличие получателя;
- для `billing_alliance_forward` проверяет наличие вложения;
- очищает `last_error`, проставляет новый `queued_at`;
- ставит `transaction.on_commit` для `send_outbound_email.delay`.

В UI карточки задачи под каждым failed-письмом отображается форма «Повторить отправку» с CSRF-токеном. В админке есть admin action «Повторить отправку failed-писем».

Snapshot тела/получателей/вложений при retry не теряется. Это сознательно отличает retry от «отправить такое же письмо заново».

### S7. Семантика `provider_message_id`

Поле `provider_message_id` предназначено для ID, возвращённого почтовым сервером (например, Zimbra REST API). SMTP backend Django такого ID не возвращает. Поэтому `SmtpEmailProvider` оставляет `provider_message_id` пустым — наш собственный `Message-ID` лежит отдельно в `OutboundEmail.message_id` и в `headers["Message-ID"]`.

Если в будущем появится Zimbra API-провайдер, он должен заполнять `provider_message_id` тем, что вернул сервер. Запрос «найти письмо у провайдера по нашему Message-ID» допустим, но не должен заменять server-side ID.

### S8. Domain Message-ID и DKIM

`COMMUNICATIONS_MESSAGE_ID_DOMAIN` должен совпадать с DKIM-доменом отправителя. По умолчанию берём домен `COMMUNICATIONS_FROM_EMAIL`. Если для production используется поддомен (например, `billing.example.ru`) — то и Message-ID, и DKIM-подпись должны быть в этом же домене.

Перед production администратор почты подтверждает:

- SPF разрешает наш IP;
- DKIM настроен на DKIM-домене;
- DMARC alignment проходит (Message-ID-домен идёт в одной зоне со From-доменом).

### S9. HTML-санитизация технического кода

`append_technical_code_to_html` escape'ит технический код через `django.utils.html.escape`. Сейчас код имеет фиксированный формат `OP-<APP_LABEL>-<INT>` и опасных символов не содержит, но привычка обязательна — она защитит от будущей фантазии вида «добавим в код имя пользователя».

### S10. Snapshot vs current state

`OutboundEmail` хранит snapshot темы, тела, HTML, получателей и вложений. Это значит:

- изменение `BillingTask` после отправки письма не меняет содержимое уже отправленного письма;
- в UI блок «История отправок» должен показывать тело письма (через `<details>`), чтобы было видно, что было отправлено;
- при retry мы не пересчитываем subject/body заново — это специально, чтобы получатель не получил неожиданно изменённое письмо.

Если в будущем понадобится «пересоздать письмо по актуальным данным задачи» — это отдельный сервис `recreate_outbound_email_from_task(task)`, а не флаг на retry.

### S11. Auditlog: что писать, что нет

В `auditlog.registry` регистрируем только `MailAccount` и `OutboundEmail`. Не регистрируем:

- `OutboundEmailRecipient`, `OutboundEmailAttachment`, `EmailDeliveryAttempt` — это технические подчинённые сущности, их история уже хранится в полях.

Для `OutboundEmail` исключаем технические поля: `queued_at`, `sending_started_at`, `sent_at`, `failed_at`, `last_error`, `provider_message_id`, `headers`, `body_text`, `body_html`. Они меняются часто и сами по себе аудита не требуют — аудит важен на бизнес-операциях (создание письма, смена статуса), а не на тайминге отправки.

Это особенно важно потому, что `daily_digest` читает auditlog для сводки и не должен заваливаться техническими событиями.

### S12. Admin: read-only для подчинённых

В админке `OutboundEmail` запрещено создавать/менять recipients, attachments и attempts вручную (`has_add_permission = False`, `has_change_permission = False` на inline'ах). Сам `OutboundEmail` тоже запрещён к ручному созданию (`has_add_permission = False` на ModelAdmin). Это страхует от случайного обхода snapshot-логики.

Allowed actions:

- посмотреть письмо;
- запустить retry failed-писем admin action'ом.

Запрещённые операции:

- добавить вручную получателя или вложение к отправленному письму;
- пере-добавить delivery attempt;
- создать «ручное» письмо без `BillingTask`.

### S13. Просмотр тела письма из карточки задачи

В карточке задачи блок «История отправок» включает `<details>` с `body_text` для каждого письма. Это покрывает базовый кейс «что именно мы отправили». Если бизнесу понадобится отдельная страница для письма с headers/attempts/HTML — это отдельный list/detail view, но в MVP его делать не нужно.

### S14. Что осталось зафиксировать до этапа 2

Перед началом этапа 2 («четверговый отчёт через communications»):

- получить адрес общего ящика billing на Яндекс/Zimbra;
- определить, как формируется подпись (внутри `build_letter_text` или отдельным шаблоном);
- зафиксировать, в каких ящиках хранятся ответы СК — это нужно для будущего IMAP-этапа.
