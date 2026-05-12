import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.text import get_valid_filename


ALLOWED_ATTACHMENT_EXTENSIONS = {
    "pdf",
    "jpg",
    "jpeg",
    "png",
    "doc",
    "docx",
    "xls",
    "xlsx",
}


@dataclass(frozen=True)
class AttachmentValidationResult:
    safe_filename: str
    content_type: str
    size: int
    checksum: str


def validate_outbound_attachment(uploaded_file) -> AttachmentValidationResult:
    if not uploaded_file:
        raise ValidationError("Файл обязателен")

    original_name = uploaded_file.name or ""
    if not original_name:
        raise ValidationError("Имя файла не может быть пустым")

    extension = Path(original_name).suffix.lower().lstrip(".")
    if not extension:
        raise ValidationError("Файл должен иметь расширение")
    if extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS))
        raise ValidationError(f"Недопустимый тип файла. Разрешены: {allowed}")

    max_size = settings.COMMUNICATIONS_ATTACHMENT_MAX_SIZE_MB * 1024 * 1024
    size = getattr(uploaded_file, "size", 0) or 0
    if size <= 0:
        raise ValidationError("Файл не может быть пустым")
    if size > max_size:
        max_mb = settings.COMMUNICATIONS_ATTACHMENT_MAX_SIZE_MB
        raise ValidationError(
            f"Размер файла превышает максимально допустимый ({max_mb}MB)"
        )

    safe_filename = get_valid_filename(original_name)
    if not safe_filename:
        raise ValidationError("Не удалось сформировать безопасное имя файла")

    checksum = calculate_uploaded_file_checksum(uploaded_file)
    guessed_content_type, _ = mimetypes.guess_type(original_name)
    content_type = (
        getattr(uploaded_file, "content_type", None)
        or guessed_content_type
        or "application/octet-stream"
    )
    return AttachmentValidationResult(
        safe_filename=safe_filename,
        content_type=content_type,
        size=size,
        checksum=checksum,
    )


def calculate_uploaded_file_checksum(uploaded_file) -> str:
    current_position = None
    if hasattr(uploaded_file, "tell"):
        try:
            current_position = uploaded_file.tell()
        except (OSError, ValueError):
            current_position = None

    if hasattr(uploaded_file, "seek"):
        try:
            uploaded_file.seek(0)
        except (OSError, ValueError):
            pass

    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)

    if hasattr(uploaded_file, "seek"):
        try:
            uploaded_file.seek(0 if current_position is None else current_position)
        except (OSError, ValueError):
            pass

    return digest.hexdigest()
