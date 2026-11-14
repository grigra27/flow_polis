"""Изображения справочников для Dashboard и имущественных отчётов."""

from apps.insurers.models import Branch, InsuranceType, Insurer


class ReferenceImages:
    """Три запроса на весь экран, без обращений к БД из строк таблиц."""

    def __init__(self):
        self.urls = {}
        for dimension, model, field in (
            ("branch", Branch, "logo"),
            ("insurer", Insurer, "logo"),
            ("type", InsuranceType, "icon"),
        ):
            self.urls[dimension] = {
                obj.pk: image.url
                for obj in model.objects.only("pk", field)
                if (image := getattr(obj, field))
            }

    def get(self, dimension, pk):
        return self.urls[dimension].get(pk, "")

    def attach(self, rows, dimension):
        for row in rows:
            row["image_url"] = self.get(dimension, row["key"])
