"""Однополевые правки из карточки полиса."""

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

from .models import PaymentSchedule


def can_edit_card_field(user, model):
    return (
        user.is_active
        and user.is_staff
        and user.has_perm(f"policies.change_{model._meta.model_name}")
    )


def check_original(request, current, proposed):
    """Повтор сохранения идемпотентен; чужую более свежую правку показываем оператору."""
    if current == proposed:
        return HttpResponse(status=204)
    if request.POST.get("original") != current:
        return JsonResponse(
            {"error": "Значение уже изменилось. Обновите карточку и проверьте его."},
            status=409,
        )


@login_required
@require_POST
def update_payment_date(request, pk, payment_id, field):
    if not can_edit_card_field(request.user, PaymentSchedule):
        raise PermissionDenied
    if field not in ("paid_date", "insurer_date"):
        return JsonResponse({"error": "Неизвестное поле платежа."}, status=400)
    try:
        value = forms.DateField(required=False, input_formats=["%Y-%m-%d"]).clean(
            request.POST["value"]
        )
    except KeyError:
        return JsonResponse({"error": "Укажите дату."}, status=400)
    except ValidationError as error:
        return JsonResponse({"error": " ".join(error.messages)}, status=422)

    try:
        with transaction.atomic():
            # Соседние взносы участвуют в проверке порядка дат. Все редакторы
            # берут блокировки одного графика в одинаковом порядке.
            schedule = list(
                PaymentSchedule.objects.select_for_update()
                .filter(policy_id=pk)
                .order_by("year_number", "installment_number")
            )
            for index, payment in enumerate(schedule):
                if payment.pk == payment_id:
                    break
            else:
                raise Http404
            current = getattr(payment, field)
            result = check_original(
                request,
                current.isoformat() if current else "",
                value.isoformat() if value else "",
            )
            if result is not None:
                return result
            setattr(payment, field, value)
            if index + 1 < len(schedule):
                following = schedule[index + 1]
                if field in following.date_sequence_errors(payment):
                    raise ValidationError(
                        f"Дата должна быть раньше даты следующего взноса "
                        f"({following.year_number}/{following.installment_number}, "
                        f"{getattr(following, field):%d.%m.%Y})."
                    )
            # save() проверяет модель и предыдущий взнос, запускает аудит и billing.
            payment.save(update_fields=[field, "updated_at"])
    except ValidationError as error:
        return JsonResponse({"error": " ".join(error.messages)}, status=422)
    return HttpResponse(status=204)
