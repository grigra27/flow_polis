import re
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError

from apps.clients.models import Client
from apps.insurers.models import Branch, InsuranceType
from apps.policies.models import Policy


ACCEPT_IMPORT_SESSION_KEY = "policy_accept_imports"

BRANCH_CODE_MAP = {
    "АР": "Архангельск",
    "ВН": "Великий Новгород",
    "КЗ": "Казань",
    "КР": "Краснодар",
    "МН": "Мурманск",
    "МСК": "Москва",
    "ПС": "Псков",
    "СТ": "Краснодар",
    "ЧЛ": "Челябинск",
}


@dataclass
class AcceptResolvedData:
    policy_initial: dict = field(default_factory=dict)
    payment_initial: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    resolved: dict = field(default_factory=dict)

    def to_session_payload(self, parsed_data):
        return {
            "parsed": parsed_data.to_session_dict(),
            "policy_initial": self.policy_initial,
            "payment_initial": self.payment_initial,
            "warnings": self.warnings,
            "resolved": self.resolved,
        }


def resolve_accept_data(parsed_data, parser_warnings=None):
    resolver = AcceptResolver()
    return resolver.resolve(parsed_data, parser_warnings=parser_warnings or [])


class AcceptResolver:
    def resolve(self, parsed_data, parser_warnings=None):
        warnings = list(parser_warnings or [])
        policy_initial = {}
        payment_initial = {}
        resolved = {}

        self._set_text(policy_initial, "dfa_number", parsed_data.dfa_number)
        self._set_text(
            policy_initial, "property_description", parsed_data.property_description
        )
        if parsed_data.property_year:
            policy_initial["property_year"] = parsed_data.property_year
        if parsed_data.start_date:
            policy_initial["start_date"] = parsed_data.start_date.isoformat()
        if parsed_data.end_date:
            policy_initial["end_date"] = parsed_data.end_date.isoformat()

        client = self._resolve_client(parsed_data, warnings, resolved)
        if client:
            policy_initial["client"] = client.pk
            if self._is_lessee_policyholder(parsed_data.policyholder_text):
                policy_initial["policyholder"] = client.pk
                resolved["policyholder"] = {
                    "status": "matched",
                    "label": str(client),
                }
        elif parsed_data.policyholder_text:
            resolved["policyholder"] = {
                "status": "manual",
                "label": parsed_data.policyholder_text,
            }

        insurance_type = self._resolve_insurance_type(parsed_data, warnings, resolved)
        if insurance_type:
            policy_initial["insurance_type"] = insurance_type.pk

        branch = self._resolve_branch(parsed_data, warnings, resolved)
        if branch:
            policy_initial["branch"] = branch.pk

        vin_number = self._resolve_vin(parsed_data, warnings, resolved)
        if vin_number:
            policy_initial["vin_number"] = vin_number

        if parsed_data.purchase_price is not None:
            payment_initial.update(
                {
                    "year_number": 1,
                    "installment_number": 1,
                    "insurance_sum": str(parsed_data.purchase_price),
                }
            )
            if parsed_data.start_date:
                payment_initial["due_date"] = parsed_data.start_date.isoformat()
            resolved["payment_schedule"] = {
                "status": "partial",
                "label": "Первая строка графика подготовлена без страховой премии.",
            }
        else:
            warnings.append(
                "Первая строка графика платежей не подготовлена: страховая сумма не распознана."
            )

        return AcceptResolvedData(
            policy_initial=policy_initial,
            payment_initial=payment_initial,
            warnings=warnings,
            resolved=resolved,
        )

    def _resolve_client(self, parsed_data, warnings, resolved):
        if not parsed_data.client_inn:
            warnings.append("Клиент не сопоставлен: в акцепте нет ИНН.")
            resolved["client"] = {"status": "manual", "label": parsed_data.client_full}
            return None

        client = Client.objects.filter(client_inn=parsed_data.client_inn).first()
        if client:
            resolved["client"] = {
                "status": "matched",
                "label": f"{client.client_name} (ИНН {client.client_inn})",
            }
            return client

        label = (
            parsed_data.client_full
            or parsed_data.client_short
            or parsed_data.client_inn
        )
        warnings.append(
            f"Клиент с ИНН {parsed_data.client_inn} не найден в справочнике."
        )
        resolved["client"] = {"status": "manual", "label": label}
        return None

    def _resolve_insurance_type(self, parsed_data, warnings, resolved):
        if not parsed_data.insurance_type_name:
            warnings.append("Вид страхования не заполнен в акцепте.")
            resolved["insurance_type"] = {"status": "manual", "label": ""}
            return None

        insurance_type = (
            InsuranceType.objects.filter(name__iexact=parsed_data.insurance_type_name)
            .order_by("name")
            .first()
        )
        if insurance_type:
            resolved["insurance_type"] = {
                "status": "matched",
                "label": insurance_type.name,
            }
            return insurance_type

        warnings.append(
            f'Вид страхования "{parsed_data.insurance_type_name}" не найден в справочнике.'
        )
        resolved["insurance_type"] = {
            "status": "manual",
            "label": parsed_data.insurance_type_name,
        }
        return None

    def _resolve_branch(self, parsed_data, warnings, resolved):
        code = self._extract_branch_code(parsed_data.dfa_number)
        if not code:
            warnings.append("Филиал не определен: номер ДФА пустой или нестандартный.")
            resolved["branch"] = {"status": "manual", "label": ""}
            return None

        branch_name = BRANCH_CODE_MAP.get(code)
        if not branch_name:
            warnings.append(f'Филиал не определен по коду "{code}" из номера ДФА.')
            resolved["branch"] = {"status": "manual", "label": code}
            return None

        branch = Branch.objects.filter(branch_name__iexact=branch_name).first()
        if branch:
            resolved["branch"] = {"status": "matched", "label": branch.branch_name}
            return branch

        warnings.append(
            f'Филиал "{branch_name}" определен по ДФА, но не найден в справочнике.'
        )
        resolved["branch"] = {"status": "manual", "label": branch_name}
        return None

    def _resolve_vin(self, parsed_data, warnings, resolved):
        vin_number = (parsed_data.vin_number or "").strip().upper()
        if not vin_number:
            resolved["vin_number"] = {"status": "manual", "label": ""}
            return ""

        vin_field = Policy._meta.get_field("vin_number")
        try:
            vin_field.clean(vin_number, None)
        except ValidationError:
            warnings.append(
                f'VIN/ID "{vin_number}" не прошел валидацию и не будет подставлен.'
            )
            resolved["vin_number"] = {"status": "invalid", "label": vin_number}
            return ""

        resolved["vin_number"] = {"status": "matched", "label": vin_number}
        return vin_number

    def _extract_branch_code(self, dfa_number):
        parts = [part.strip().upper() for part in str(dfa_number or "").split("-")]
        if not parts:
            return ""
        code = parts[-1]
        return code if re.fullmatch(r"[А-ЯЁA-Z]{2,3}", code) else ""

    def _is_lessee_policyholder(self, value):
        return str(value or "").strip().lower() == "лизингополучатель"

    def _set_text(self, target, key, value):
        value = str(value or "").strip()
        if value:
            target[key] = value
