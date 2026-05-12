import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.communications.validators import (
    ALLOWED_ATTACHMENT_EXTENSIONS,
    validate_outbound_attachment,
)


def _upload(name, content=b"data", content_type="application/octet-stream"):
    return SimpleUploadedFile(name, content, content_type=content_type)


def test_allowed_extensions_are_whitelisted():
    assert ALLOWED_ATTACHMENT_EXTENSIONS == {
        "pdf",
        "jpg",
        "jpeg",
        "png",
        "doc",
        "docx",
        "xls",
        "xlsx",
    }


def test_validate_outbound_attachment_returns_metadata_for_pdf():
    upload = _upload("invoice.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")

    result = validate_outbound_attachment(upload)

    assert result.safe_filename == "invoice.pdf"
    assert result.content_type == "application/pdf"
    assert result.size == len(b"%PDF-1.4\n%%EOF\n")
    assert len(result.checksum) == 64  # SHA-256 hex


def test_validate_outbound_attachment_rejects_unknown_extension():
    upload = _upload("invoice.exe", b"MZ\x90\x00", "application/octet-stream")

    with pytest.raises(ValidationError) as exc_info:
        validate_outbound_attachment(upload)

    assert "Недопустимый тип файла" in str(exc_info.value)


def test_validate_outbound_attachment_rejects_missing_extension():
    upload = _upload("invoice", b"data")

    with pytest.raises(ValidationError):
        validate_outbound_attachment(upload)


def test_validate_outbound_attachment_rejects_empty_file():
    upload = _upload("invoice.pdf", b"")

    with pytest.raises(ValidationError) as exc_info:
        validate_outbound_attachment(upload)

    assert "не может быть пустым" in str(exc_info.value)


@override_settings(COMMUNICATIONS_ATTACHMENT_MAX_SIZE_MB=1)
def test_validate_outbound_attachment_rejects_oversized_file():
    upload = _upload("invoice.pdf", b"\x00" * (1024 * 1024 + 1))

    with pytest.raises(ValidationError) as exc_info:
        validate_outbound_attachment(upload)

    assert "Размер файла превышает" in str(exc_info.value)


def test_validate_outbound_attachment_normalises_unsafe_filename():
    upload = _upload("счёт за услуги.pdf", b"%PDF-1.4 ok")

    result = validate_outbound_attachment(upload)

    # Кириллица допустима, но get_valid_filename убирает пробелы и опасные символы.
    assert " " not in result.safe_filename
    assert result.safe_filename.endswith(".pdf")
