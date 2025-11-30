"""
Property-based tests for file upload validation.
Feature: security-optimization-audit

Tests validate:
- Property 11: Валидация типов загружаемых файлов
- Property 12: Проверка MIME-типа файлов
- Property 13: Рандомизация имен файлов

Validates: Requirements 8.1, 8.2, 8.3
"""
import pytest
import io
import uuid
from hypothesis import given, strategies as st, settings, assume
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.core.file_validators import FileUploadValidator


# Strategy for generating file extensions
allowed_extensions = st.sampled_from(["jpg", "jpeg", "png", "pdf", "xlsx"])
disallowed_extensions = st.sampled_from(
    ["exe", "sh", "bat", "js", "html", "php", "py", "zip", "rar"]
)


# Strategy for generating filenames
@st.composite
def filename_with_extension(draw, extension_strategy):
    """Generate a filename with a given extension."""
    base_name = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"),
                min_codepoint=65,
                max_codepoint=122,
            ),
            min_size=1,
            max_size=50,
        )
    )
    extension = draw(extension_strategy)
    return f"{base_name}.{extension}"


# Strategy for generating file content with proper magic bytes
def create_jpeg_content():
    """Create minimal valid JPEG content."""
    # JPEG magic bytes: FF D8 FF
    return (
        b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\x00" * 100
    )


def create_png_content():
    """Create minimal valid PNG content."""
    # PNG magic bytes: 89 50 4E 47 0D 0A 1A 0A
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
        + b"\x00" * 100
    )


def create_pdf_content():
    """Create minimal valid PDF content."""
    # PDF magic bytes: %PDF-
    return b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n" + b"\x00" * 100


def create_xlsx_content():
    """Create minimal valid XLSX content (ZIP format)."""
    # XLSX is a ZIP file, ZIP magic bytes: PK
    return b"PK\x03\x04" + b"\x00" * 100


def create_invalid_content():
    """Create content that doesn't match any expected MIME type."""
    return b"INVALID_CONTENT" + b"\x00" * 100


# Map extensions to content generators
content_generators = {
    "jpg": create_jpeg_content,
    "jpeg": create_jpeg_content,
    "png": create_png_content,
    "pdf": create_pdf_content,
    "xlsx": create_xlsx_content,
}


@st.composite
def valid_uploaded_file(draw):
    """Generate a valid uploaded file with matching extension and MIME type."""
    extension = draw(allowed_extensions)
    filename = draw(filename_with_extension(st.just(extension)))

    # Generate appropriate content for the extension
    content_generator = content_generators[extension]
    content = content_generator()

    # File size between 1KB and 5MB (well within 10MB limit)
    size = draw(st.integers(min_value=1024, max_value=5 * 1024 * 1024))
    # Pad content to desired size
    content = content + b"\x00" * (size - len(content))

    return SimpleUploadedFile(
        filename, content, content_type="application/octet-stream"
    )


@st.composite
def invalid_extension_file(draw):
    """Generate a file with disallowed extension."""
    extension = draw(disallowed_extensions)
    filename = draw(filename_with_extension(st.just(extension)))
    content = draw(st.binary(min_size=100, max_size=1024))

    return SimpleUploadedFile(
        filename, content, content_type="application/octet-stream"
    )


@st.composite
def oversized_file(draw):
    """Generate a file that exceeds size limit."""
    extension = draw(allowed_extensions)
    filename = draw(filename_with_extension(st.just(extension)))

    # Generate content larger than 10MB
    size = draw(st.integers(min_value=11 * 1024 * 1024, max_value=15 * 1024 * 1024))
    content = b"\x00" * size

    return SimpleUploadedFile(
        filename, content, content_type="application/octet-stream"
    )


@st.composite
def mime_mismatch_file(draw):
    """Generate a file where extension doesn't match content MIME type."""
    # Pick an extension
    extension = draw(allowed_extensions)
    filename = draw(filename_with_extension(st.just(extension)))

    # Use content from a different type
    # Ensure we pick a truly different type (not just different extension for same type)
    if extension in ["jpg", "jpeg"]:
        # For JPEG, use PNG or PDF content
        wrong_extension = draw(st.sampled_from(["png", "pdf"]))
    elif extension == "png":
        # For PNG, use JPEG or PDF content
        wrong_extension = draw(st.sampled_from(["jpg", "pdf"]))
    elif extension == "pdf":
        # For PDF, use image content
        wrong_extension = draw(st.sampled_from(["jpg", "png"]))
    else:  # xlsx
        # For XLSX, use image or PDF content (not ZIP-based)
        wrong_extension = draw(st.sampled_from(["jpg", "png", "pdf"]))

    content_generator = content_generators[wrong_extension]
    content = content_generator()

    return SimpleUploadedFile(
        filename, content, content_type="application/octet-stream"
    )


# Property 11: Валидация типов загружаемых файлов
# For any file with an extension not in the whitelist, upload should be rejected
@pytest.mark.django_db
@given(uploaded_file=invalid_extension_file())
@settings(max_examples=100, deadline=5000)
def test_property_11_file_extension_validation(uploaded_file):
    """
    Feature: security-optimization-audit, Property 11: Валидация типов загружаемых файлов
    Validates: Requirements 8.1

    For any file with an extension not in the whitelist (jpg, jpeg, png, pdf, xlsx),
    the upload should be rejected.
    """
    is_valid, error, safe_filename = FileUploadValidator.validate_file(uploaded_file)

    # File should be rejected
    assert (
        not is_valid
    ), f"File with disallowed extension should be rejected: {uploaded_file.name}"
    assert error is not None, "Error message should be provided for invalid file"
    assert "Недопустимый тип файла" in error or "Разрешены" in error


# Property 12: Проверка MIME-типа файлов
# For any file, the declared MIME type (from extension) must match actual content
@pytest.mark.django_db
@given(uploaded_file=mime_mismatch_file())
@settings(max_examples=100, deadline=5000)
def test_property_12_mime_type_validation(uploaded_file):
    """
    Feature: security-optimization-audit, Property 12: Проверка MIME-типа файлов
    Validates: Requirements 8.2

    For any file, if the content MIME type (magic bytes) doesn't match the extension,
    the upload should be rejected.
    """
    is_valid, error, safe_filename = FileUploadValidator.validate_file(uploaded_file)

    # File should be rejected due to MIME mismatch
    assert (
        not is_valid
    ), f"File with MIME mismatch should be rejected: {uploaded_file.name}"
    assert error is not None, "Error message should be provided for MIME mismatch"
    assert "не соответствует" in error or "Ожидается" in error


# Property 13: Рандомизация имен файлов
# For any valid file, the generated filename should be random (UUID-based) and not contain original name
@pytest.mark.django_db
@given(uploaded_file=valid_uploaded_file())
@settings(max_examples=100, deadline=5000)
def test_property_13_filename_randomization(uploaded_file):
    """
    Feature: security-optimization-audit, Property 13: Рандомизация имен файлов
    Validates: Requirements 8.3

    For any valid uploaded file, the generated safe filename should:
    1. Be different from the original filename
    2. Not contain the original filename
    3. Be a valid UUID-based name
    4. Preserve the file extension
    """
    is_valid, error, safe_filename = FileUploadValidator.validate_file(uploaded_file)

    # Skip if file is invalid (e.g., too large)
    assume(is_valid)

    original_name = uploaded_file.name
    original_ext = FileUploadValidator.get_extension(original_name)

    # Safe filename should be different from original
    assert safe_filename != original_name, "Safe filename should differ from original"

    # Safe filename should not contain original name (except extension)
    # Only check if original base is longer than 1 character to avoid false positives
    original_base = original_name.rsplit(".", 1)[0]
    safe_base = safe_filename.rsplit(".", 1)[0]
    if len(original_base) > 1:
        assert (
            original_base.lower() not in safe_base.lower()
        ), "Safe filename should not contain original base name"

    # Safe filename should preserve extension
    safe_ext = FileUploadValidator.get_extension(safe_filename)
    assert (
        safe_ext == original_ext
    ), f"Extension should be preserved: expected {original_ext}, got {safe_ext}"

    # Safe filename base should be a valid hex string (UUID format)
    try:
        uuid.UUID(safe_base, version=4)
    except ValueError:
        # If not a valid UUID, at least check it's a hex string
        assert all(
            c in "0123456789abcdef" for c in safe_base.lower()
        ), f"Safe filename should be UUID-based hex string: {safe_base}"


# Additional property: File size validation
@pytest.mark.django_db
@given(uploaded_file=oversized_file())
@settings(max_examples=50, deadline=5000)
def test_property_file_size_validation(uploaded_file):
    """
    For any file exceeding the 10MB limit, upload should be rejected.
    Validates: Requirement 8.4
    """
    is_valid, error, safe_filename = FileUploadValidator.validate_file(uploaded_file)

    # File should be rejected
    assert not is_valid, "Oversized file should be rejected"
    assert error is not None, "Error message should be provided for oversized file"
    assert "превышает" in error or "10MB" in error or "10" in error


# Additional property: Valid files should pass all checks
@pytest.mark.django_db
@given(uploaded_file=valid_uploaded_file())
@settings(max_examples=100, deadline=5000)
def test_property_valid_files_accepted(uploaded_file):
    """
    For any file with valid extension, matching MIME type, and acceptable size,
    upload should be accepted.
    """
    is_valid, error, safe_filename = FileUploadValidator.validate_file(uploaded_file)

    # File should be accepted
    assert (
        is_valid
    ), f"Valid file should be accepted: {uploaded_file.name}, error: {error}"
    assert error is None, "No error should be provided for valid file"
    assert safe_filename is not None, "Safe filename should be generated for valid file"
