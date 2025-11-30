"""
File upload validation utilities.
Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5
"""
import os
import uuid
import filetype
from typing import Tuple, Optional
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
import logging

# Get security logger
security_logger = logging.getLogger("security")


class FileUploadValidator:
    """
    Validates uploaded files for security and compliance.

    Validates:
    - File extensions (whitelist)
    - MIME types (magic bytes)
    - File size limits
    - Generates secure random filenames
    """

    # Whitelist of allowed file extensions
    ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "pdf", "xlsx"]

    # Maximum file size in bytes (10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    # Mapping of extensions to expected MIME types
    MIME_TYPE_MAP = {
        "jpg": ["image/jpeg"],
        "jpeg": ["image/jpeg"],
        "png": ["image/png"],
        "pdf": ["application/pdf"],
        "xlsx": [
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
            "application/zip",  # XLSX files are ZIP archives
        ],
    }

    @classmethod
    def validate_file(
        cls, uploaded_file: UploadedFile
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validates an uploaded file.

        Args:
            uploaded_file: Django UploadedFile object

        Returns:
            Tuple of (is_valid, error_message, safe_filename)
            - is_valid: True if file passes all validations
            - error_message: Error message if validation fails, None otherwise
            - safe_filename: Generated safe filename if valid, None otherwise
        """
        # Validate extension
        is_valid, error = cls.validate_extension(uploaded_file.name)
        if not is_valid:
            security_logger.warning(
                f"File upload rejected - invalid extension: {uploaded_file.name}"
            )
            return False, error, None

        # Validate file size
        is_valid, error = cls.validate_size(uploaded_file.size)
        if not is_valid:
            security_logger.warning(
                f"File upload rejected - size too large: {uploaded_file.name} ({uploaded_file.size} bytes)"
            )
            return False, error, None

        # Validate MIME type
        is_valid, error = cls.validate_mime_type(uploaded_file)
        if not is_valid:
            security_logger.warning(
                f"File upload rejected - MIME type mismatch: {uploaded_file.name}"
            )
            return False, error, None

        # Generate safe filename
        safe_filename = cls.generate_safe_filename(uploaded_file.name)

        return True, None, safe_filename

    @classmethod
    def validate_extension(cls, filename: str) -> Tuple[bool, Optional[str]]:
        """
        Validates file extension against whitelist.

        Args:
            filename: Original filename

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not filename:
            return False, "Имя файла не может быть пустым"

        # Get extension
        ext = cls.get_extension(filename)

        if not ext:
            return False, "Файл должен иметь расширение"

        if ext.lower() not in cls.ALLOWED_EXTENSIONS:
            allowed = ", ".join(cls.ALLOWED_EXTENSIONS)
            return False, f"Недопустимый тип файла. Разрешены: {allowed}"

        return True, None

    @classmethod
    def validate_size(cls, file_size: int) -> Tuple[bool, Optional[str]]:
        """
        Validates file size.

        Args:
            file_size: Size of file in bytes

        Returns:
            Tuple of (is_valid, error_message)
        """
        if file_size > cls.MAX_FILE_SIZE:
            max_mb = cls.MAX_FILE_SIZE / (1024 * 1024)
            return (
                False,
                f"Размер файла превышает максимально допустимый ({max_mb:.0f}MB)",
            )

        if file_size == 0:
            return False, "Файл не может быть пустым"

        return True, None

    @classmethod
    def validate_mime_type(
        cls, uploaded_file: UploadedFile
    ) -> Tuple[bool, Optional[str]]:
        """
        Validates MIME type using magic bytes.

        Args:
            uploaded_file: Django UploadedFile object

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Get extension
        ext = cls.get_extension(uploaded_file.name)
        if not ext:
            return False, "Не удалось определить расширение файла"

        # Get expected MIME types for this extension
        expected_mimes = cls.MIME_TYPE_MAP.get(ext.lower(), [])
        if not expected_mimes:
            return False, f"Неизвестный тип файла: {ext}"

        # Read file content to check MIME type
        try:
            # Save current position
            current_pos = uploaded_file.tell()

            # Read beginning of file for magic bytes
            uploaded_file.seek(0)
            file_content = uploaded_file.read(2048)  # Read first 2KB

            # Reset file position
            uploaded_file.seek(current_pos)

            # Detect file type using filetype library
            kind = filetype.guess(file_content)

            if kind is None:
                return False, "Не удалось определить тип файла по содержимому"

            detected_mime = kind.mime

            # Check if detected MIME matches expected
            if detected_mime not in expected_mimes:
                return (
                    False,
                    f"Содержимое файла не соответствует заявленному типу. Ожидается: {', '.join(expected_mimes)}, обнаружено: {detected_mime}",
                )

            return True, None

        except Exception as e:
            security_logger.error(f"Error validating MIME type: {str(e)}")
            return False, "Ошибка при проверке типа файла"

    @classmethod
    def get_extension(cls, filename: str) -> Optional[str]:
        """
        Extracts file extension from filename.

        Args:
            filename: Original filename

        Returns:
            File extension without dot, or None if no extension
        """
        if not filename or "." not in filename:
            return None

        return filename.rsplit(".", 1)[-1].lower()

    @classmethod
    def generate_safe_filename(cls, original_filename: str) -> str:
        """
        Generates a safe random filename using UUID.

        Args:
            original_filename: Original filename

        Returns:
            Safe filename with UUID and original extension
        """
        ext = cls.get_extension(original_filename)

        # Generate UUID
        unique_id = uuid.uuid4().hex

        # Combine UUID with extension
        if ext:
            return f"{unique_id}.{ext}"
        else:
            return unique_id

    @classmethod
    def validate_and_save(
        cls, uploaded_file: UploadedFile, upload_to: str = ""
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validates file and returns safe path for saving.

        Args:
            uploaded_file: Django UploadedFile object
            upload_to: Subdirectory to save file in (relative to MEDIA_ROOT)

        Returns:
            Tuple of (is_valid, error_message, safe_path)
            - is_valid: True if file passes all validations
            - error_message: Error message if validation fails, None otherwise
            - safe_path: Safe path for saving (relative to MEDIA_ROOT), None if invalid
        """
        is_valid, error, safe_filename = cls.validate_file(uploaded_file)

        if not is_valid:
            return False, error, None

        # Construct safe path
        if upload_to:
            safe_path = os.path.join(upload_to, safe_filename)
        else:
            safe_path = safe_filename

        return True, None, safe_path


def validate_image_file(uploaded_file: UploadedFile) -> None:
    """
    Django validator function for image files.
    Can be used in model field validators.

    Args:
        uploaded_file: Django UploadedFile object

    Raises:
        ValidationError: If file validation fails
    """
    is_valid, error, _ = FileUploadValidator.validate_file(uploaded_file)

    if not is_valid:
        raise ValidationError(error)
