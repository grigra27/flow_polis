# Архитектура БД - текст

### 1. **Client** (Клиент)

Информация о клиентах (под клиентами на данном этапе понимаем лизингополучателей, но в перспективе может быть расширено и до иных клиентов).

- **id** *(serial)* — PK.
- **client_name** *(varchar)* — название компании.
- **client_inn** *(varchar, nullable)* — идентификатор (ИНН для юрлица).

### 2. **Insurer** (Страховая компания)

Справочник страховых компаний.

- **id** *(serial)* — PK.
- **insurer_name** *(varchar)* — название страховой компании.

### 3. **Branch** (Филиал)

- **id** *(serial)* — PK.
- **branch_name** *(varchar)* — название филиала (Москва, Казань, Псков, Архангельск и т. д.).

### 4. **InfoTag** (Справочник меток для Инфо 1/2)

- **id** *(serial)* — PK.
- **name** *(varchar unique)* - конкретный тэг.

### **5. InsuranceType** (Вид страхования)

- **id** *(serial)* — PK.
- **name** *(varchar unique)* — например: «КАСКО», «Имущество», «Спецтехника».

### 6. **CommissionRate** (Ставки комиссий по видам страхования и страховым компаниям)

- **id** *(serial)* — PK.
- **insurer_id** *(FK → Insurer.id)* — страховщик.
- **insurance_type_id** *(FK → InsuranceType.id)* — вид страхования.
- **kv_percent** *(numeric)* — ставка комиссии в процентах.
- **created_at** *(timestamp)*
- **updated_at** *(timestamp)*

### 7. **Policy** (Страховой полис)

Центральная сущность — договор страхования.

- **id** *(serial)* — PK.
- **policy_number** *(varchar)* — номер договора у страховщика.
- **dfa_number** *(varchar)* — номер ДФА от лизинговой компании.
- **client_id** *(FK → Client.id)* - лизингополучатель.
- **policyholder_id** *(FK → Client.id, nullable)* - страхователь (если АЛ - завести клиентом).
- **insurer_id** *(FK → Insurer.id) - страховщик.*
- **property_description** *(varchar)* — описание застрахованного имущества.
- **start_date** *(date)* - дата начала страхования.
- **end_date** *(date)* - дата окончания страхования.
- **property_value** *(numeric)* — стоимость имущества (__СС за первый год__).
- **premium_total** *(numeric)* — общая сумма страховой премии (сумма всех премий из ***PaymentSchedule***).
- **insurance_type_id** *(FK → InsuranceType.id)* — вид страхования.
- **branch_id** *(FK → Branch.id)* — филиал, к которому относится полис.
- **leasing_manager** (*varchar*) -  фамилия менеджера лизинговой компании.
- **franchise** (*numeric*) - размер франшизы, если франшизы нет то ставить 0.
- **info3** (varchar) - свободное текстовое поле (видно в журнале)
- **info4** (*varchar*) - свободное текстовое поле (не видно в журнале)
- **policy_active** (*boolean*) - полис активен или закрыт
- **dfa_active** (*boolean*) - ДФА активен или закрыт
- **policy_uploaded** (*boolean*) - полис подгружен (по умолчанию false)
- **created_at** *(timestamp)*
- **updated_at** *(timestamp)*

### 8. **PaymentSchedule** (График платежей)

Разбивка по конкретным платежам для полиса.

- **id** *(serial/uuid)*
- **policy_id** *(FK → Policy.id)*
- **year_number** (*int*) - порядковый номер года.
- **installment_number** (*int*) - порядковый номер платежа.
- **due_date** *(date)* — дата платежа (из договора).
- **amount** *(numeric)* — сумма.
- **kv_percent** *(FK → CommissionRate.id)* - процент комиссии.
- **kv_rub** *(numeric)* — сумма комиссии (по умолчанию как **amount*****kv_percent**).
- **paid_date** *(date, nullable)* — фактическая дата оплаты.
- **insurer_date** *(date, nullable)* —  дата согласования СК.
- **payment_info** (*varchar*) - свободное текстовое поле.
- **created_at** *(timestamp)*
- **updated_at** *(timestamp)*

### 9. **PolicyInfo** (Связка полис ↔ метки для инфо-полей)

- **id** *(serial)*
- **policy_id** *(FK → Policy.id)*
- **tag_id** *(FK → InfoTag.id)*
- **info_field** *(smallint)* → 1 = Инфо 1, 2 = Инфо 2
- **created_at** *(timestamp)*
- **updated_at** *(timestamp)*


---

##  Логика и связи

- Один **Client** может иметь много **Policy**.
- Один **Insurer** может быть у многих **Policy**.
- У одного **Policy** может быть несколько записей в **PaymentSchedule**.
- **Policy ↔ PaymentSchedule** — один-ко-многим.
- **Policy ↔ InfoTag** — многие-ко-многим через PolicyInfo, где info_field задаёт, к какому полю относится метка.
- **Client / Insurer / Branch** — справочники для ссылок из Policy.
- **InsuranceType ↔ Insurer ↔ CommissionRate** — связка ставок комиссий.
