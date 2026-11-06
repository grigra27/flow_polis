"""Private media downloads require a session and stay inside MEDIA_ROOT."""

from urllib.parse import parse_qs, quote, urlsplit

import pytest
from django.urls import reverse


pytestmark = pytest.mark.django_db


@pytest.fixture
def media_root(settings, tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    settings.MEDIA_ROOT = root
    return root


@pytest.fixture
def private_document(media_root):
    document = media_root / "documents" / "policy.pdf"
    document.parent.mkdir()
    document.write_bytes(b"%PDF-1.4\nprivate policy fixture\n")
    return document


@pytest.fixture
def authenticated_client(client, django_user_model):
    user = django_user_model.objects.create_user(username="media-reader")
    assert not user.is_staff
    assert not user.is_superuser
    client.force_login(user)
    return client


def assert_not_cacheable(response):
    directives = {
        directive.strip().lower() for directive in response["Cache-Control"].split(",")
    }
    assert "no-store" in directives
    assert "private" in directives


@pytest.mark.parametrize("method", ["get", "head"])
def test_anonymous_document_download_requires_login_and_is_not_cacheable(
    client, private_document, method
):
    url = "/media/documents/policy.pdf"

    response = getattr(client, method)(url)

    assert response.status_code == 302
    redirect = urlsplit(response["Location"])
    assert redirect.path == reverse("accounts:login")
    assert parse_qs(redirect.query)["next"] == [url]
    assert_not_cacheable(response)
    assert private_document.read_bytes() not in response.content


def test_regular_user_can_download_document_as_uncached_attachment(
    authenticated_client, private_document
):
    response = authenticated_client.get("/media/documents/policy.pdf")

    try:
        assert response.status_code == 200
        assert b"".join(response.streaming_content) == private_document.read_bytes()
        assert response["Content-Type"] == "application/pdf"
        assert response["Content-Disposition"] == 'attachment; filename="policy.pdf"'
        assert response["X-Content-Type-Options"] == "nosniff"
        assert_not_cacheable(response)
    finally:
        response.close()


def test_authenticated_head_returns_download_headers_without_document_body(
    authenticated_client, private_document
):
    response = authenticated_client.head("/media/documents/policy.pdf")

    try:
        assert response.status_code == 200
        assert b"".join(response.streaming_content) == b""
        assert int(response["Content-Length"]) == private_document.stat().st_size
        assert response["Content-Disposition"] == 'attachment; filename="policy.pdf"'
        assert response["X-Content-Type-Options"] == "nosniff"
        assert_not_cacheable(response)
    finally:
        response.close()


@pytest.mark.parametrize("path", ["missing.pdf", "documents/"])
def test_missing_files_and_directories_return_404(
    authenticated_client, private_document, path
):
    response = authenticated_client.get(f"/media/{path}")

    assert response.status_code == 404


@pytest.mark.parametrize("method", ["get", "head"])
def test_parent_traversal_cannot_read_a_sibling_with_the_same_path_prefix(
    authenticated_client, media_root, method
):
    sibling = media_root.with_name("media-sibling")
    sibling.mkdir()
    secret = sibling / "outside.pdf"
    secret.write_bytes(b"outside media root")

    response = getattr(authenticated_client, method)(
        "/media/%2e%2e/media-sibling/outside.pdf"
    )

    assert response.status_code == 404


def test_symlink_cannot_escape_media_root(authenticated_client, media_root):
    sibling = media_root.with_name("media-sibling")
    sibling.mkdir()
    secret = sibling / "outside.pdf"
    secret.write_bytes(b"outside media root")
    (media_root / "linked.pdf").symlink_to(secret)

    response = authenticated_client.get("/media/linked.pdf")

    assert response.status_code == 404


def test_unicode_filename_is_a_valid_rfc5987_attachment(
    authenticated_client, media_root
):
    filename = "Полис № 125.pdf"
    payload = b"%PDF-1.4\nunicode filename fixture\n"
    (media_root / filename).write_bytes(payload)

    response = authenticated_client.get(f"/media/{quote(filename)}")

    try:
        assert response.status_code == 200
        assert b"".join(response.streaming_content) == payload
        assert response["Content-Disposition"] == (
            f"attachment; filename*=utf-8''{quote(filename)}"
        )
        assert_not_cacheable(response)
    finally:
        response.close()
