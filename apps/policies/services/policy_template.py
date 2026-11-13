"""Начальные значения для оформления нового договора из карточки полиса."""


def can_create_from_policy(user):
    return (
        user.is_active
        and user.is_staff
        and user.has_perms(("policies.add_policy", "policies.add_paymentschedule"))
    )


def policy_template_initial(source):
    return {
        "client": source.client_id,
        "policyholder": source.policyholder_id,
        "branch": source.branch_id,
        "leasing_manager": source.leasing_manager_id,
        "dfa_number": source.dfa_number,
        "property_description": source.property_description,
        "property_year": source.property_year,
        "vin_number": source.vin_number,
        "insurer": source.insurer_id,
        "insurance_type": source.insurance_type_id,
        "start_date": source.start_date,
        "end_date": source.end_date,
        "franchise": source.franchise,
        "broker_participation": source.broker_participation,
    }
