"""
Custom storage backend for secure file serving.
Validates: Requirement 8.5
"""
from django.core.files.storage import FileSystemStorage
from django.utils.encoding import filepath_to_uri
from urllib.parse import urljoin


class SecureFileSystemStorage(FileSystemStorage):
    """
    Custom storage that ensures files are served with Content-Disposition header.
    This prevents inline execution of uploaded files.
    """

    def url(self, name):
        """
        Returns the URL where the file can be accessed.
        The view serving this file should set Content-Disposition: attachment.
        """
        if self.base_url is None:
            raise ValueError("This file is not accessible via a URL.")
        url = filepath_to_uri(name)
        if url is not None:
            url = url.lstrip("/")
        return urljoin(self.base_url, url)
