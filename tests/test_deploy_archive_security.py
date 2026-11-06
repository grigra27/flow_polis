"""Exercise the privileged archive boundary without Docker or production data."""

from dataclasses import replace
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace

import pytest


SPEC = importlib.util.spec_from_file_location(
    "deploy_archive_security_controller",
    Path(__file__).resolve().parents[1] / "scripts/deploy/controller.py",
)
controller = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = controller
SPEC.loader.exec_module(controller)

REVISION = "a" * 40
IMAGE_REF = f"insurance-broker:{REVISION}-42278908785-1"
CONFIG_PATH = "blobs/sha256/config"
LAYER_PATH = "blobs/sha256/layer"


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def tar_bytes(members):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, payload in members:
            header = (
                name if isinstance(name, tarfile.TarInfo) else tarfile.TarInfo(name)
            )
            header.size = len(payload)
            tar.addfile(header, io.BytesIO(payload))
    return output.getvalue()


@pytest.fixture
def bundle():
    layer = tar_bytes([("application.txt", b"tested application layer\n")])
    config = {
        "os": "linux",
        "architecture": "amd64",
        "config": {
            "Cmd": ["python", "manage.py", "check"],
            "Labels": {"org.opencontainers.image.revision": REVISION},
        },
        "rootfs": {"type": "layers", "diff_ids": [digest(layer)]},
    }
    config_blob = json_bytes(config)
    manifest = {"Config": CONFIG_PATH, "RepoTags": [IMAGE_REF], "Layers": [LAYER_PATH]}
    members = {
        CONFIG_PATH: config_blob,
        LAYER_PATH: layer,
        "manifest.json": json_bytes([manifest]),
    }
    request = controller.Request(
        "upload", "42278908785-1", REVISION, IMAGE_REF, digest(config_blob), "", 1
    )
    return SimpleNamespace(
        members=members,
        config=config,
        config_blob=config_blob,
        manifest=manifest,
        layer=layer,
        request=request,
    )


def sanitize(tmp_path, bundle, members=None, request=None):
    if members is None:
        members = bundle.members.items()
    packed = gzip.compress(tar_bytes(members), mtime=0)
    source, destination = tmp_path / "image.tar.gz", tmp_path / "sanitized.tar"
    source.write_bytes(packed)
    request = replace(
        request or bundle.request,
        archive_sha256=hashlib.sha256(packed).hexdigest(),
        size=len(packed),
    )
    config = controller.sanitize_archive(source, destination, request)
    return config, destination


@pytest.mark.parametrize("compressed_layer", [False, True])
def test_repack_excludes_hidden_protected_tags_and_preserves_tested_image(
    tmp_path, bundle, compressed_layer
):
    members = dict(bundle.members)
    if compressed_layer:
        members[LAYER_PATH] = gzip.compress(bundle.layer, mtime=0)
    # A Docker/containerd loader must never see these extra tag mappings.
    members["index.json"] = json_bytes(
        {
            "schemaVersion": 2,
            "manifests": [
                {"annotations": {"org.opencontainers.image.ref.name": "nginx:alpine"}}
            ],
        }
    )
    members["repositories"] = json_bytes(
        {"nginx": {"alpine": "attacker"}, "postgres": {"15-alpine": "attacker"}}
    )
    members["blobs/sha256/unreferenced"] = b"untrusted OCI side graph"
    config, output = sanitize(tmp_path, bundle, members.items())
    assert config == bundle.config
    with tarfile.open(output) as tar:
        assert tar.getnames() == ["config.json", "layer000.tar", "manifest.json"]
        assert all(member.isfile() and member.mode == 0o600 for member in tar)
        assert tar.extractfile("config.json").read() == bundle.config_blob
        assert tar.extractfile("layer000.tar").read() == bundle.layer
        assert json.load(tar.extractfile("manifest.json")) == [
            {
                "Config": "config.json",
                "RepoTags": [IMAGE_REF],
                "Layers": ["layer000.tar"],
            }
        ]


def test_config_bytes_must_match_trusted_digest(tmp_path, bundle):
    members = dict(bundle.members)
    members[CONFIG_PATH] += b" "
    with pytest.raises(controller.DeploymentError, match="config digest mismatch"):
        sanitize(tmp_path, bundle, members.items())


@pytest.mark.parametrize("target", ["os", "architecture", "revision", "diff_id"])
def test_config_semantics_remain_checked_after_digest_verification(
    tmp_path, bundle, target
):
    config = json.loads(bundle.config_blob)
    if target in ("os", "architecture"):
        config[target] = "unexpected"
    elif target == "revision":
        config["config"]["Labels"]["org.opencontainers.image.revision"] = "b" * 40
    else:
        config["rootfs"]["diff_ids"] = ["sha256:" + "0" * 64]
    blob = json_bytes(config)
    members = {**bundle.members, CONFIG_PATH: blob}
    with pytest.raises(controller.DeploymentError, match="mismatch"):
        sanitize(
            tmp_path,
            bundle,
            members.items(),
            replace(bundle.request, config_digest=digest(blob)),
        )


@pytest.mark.parametrize("compressed", [False, True])
def test_layer_tampering_is_rejected(tmp_path, bundle, compressed):
    modified = bundle.layer.replace(b"tested application", b"hostile executable", 1)
    assert modified != bundle.layer
    if compressed:
        modified = gzip.compress(modified, mtime=0)
    members = {**bundle.members, LAYER_PATH: modified}
    with pytest.raises(controller.DeploymentError, match="layer digest mismatch"):
        sanitize(tmp_path, bundle, members.items())


def test_repack_binds_layer_order_even_when_archive_members_have_different_order(
    tmp_path, bundle
):
    second_path = "blobs/sha256/second-layer"
    second_layer = tar_bytes([("next.txt", b"second application layer\n")])
    config = json.loads(bundle.config_blob)
    config["rootfs"]["diff_ids"] = [digest(second_layer), digest(bundle.layer)]
    config_blob = json_bytes(config)
    manifest = {**bundle.manifest, "Layers": [second_path, LAYER_PATH]}
    members = {
        **bundle.members,
        CONFIG_PATH: config_blob,
        "manifest.json": json_bytes([manifest]),
        second_path: second_layer,
    }
    _, output = sanitize(
        tmp_path,
        bundle,
        members.items(),
        replace(bundle.request, config_digest=digest(config_blob)),
    )
    with tarfile.open(output) as tar:
        manifest = json.load(tar.extractfile("manifest.json"))[0]
        assert manifest["Layers"] == ["layer000.tar", "layer001.tar"]
        assert tar.extractfile("layer000.tar").read() == second_layer
        assert tar.extractfile("layer001.tar").read() == bundle.layer


@pytest.mark.parametrize(
    "mutation", ["extra_tag", "second_image", "duplicate_layer", "too_many_layers"]
)
def test_manifest_cannot_add_tags_images_or_ambiguous_layers(
    tmp_path, bundle, mutation
):
    manifest = json.loads(json_bytes(bundle.manifest))
    entries = [manifest]
    if mutation == "extra_tag":
        manifest["RepoTags"].append("nginx:alpine")
    elif mutation == "second_image":
        entries.append({**manifest, "RepoTags": ["nginx:alpine"]})
    elif mutation == "duplicate_layer":
        manifest["Layers"] *= 2
    else:
        manifest["Layers"] = [f"layers/{index}" for index in range(129)]
    members = {**bundle.members, "manifest.json": json_bytes(entries)}
    with pytest.raises(controller.DeploymentError):
        sanitize(tmp_path, bundle, members.items())


def test_missing_layer_is_rejected(tmp_path, bundle):
    members = {
        name: data for name, data in bundle.members.items() if name != LAYER_PATH
    }
    with pytest.raises(controller.DeploymentError, match="Missing image layer"):
        sanitize(tmp_path, bundle, members.items())


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "./relative", "two//slashes", "windows\\path"]
)
def test_archive_paths_are_rejected_before_repack(tmp_path, bundle, name):
    members = [*bundle.members.items(), (name, b"host file")]
    with pytest.raises(controller.DeploymentError, match="archive (path|member)"):
        sanitize(tmp_path, bundle, members)


def test_duplicate_members_are_rejected(tmp_path, bundle):
    members = [*bundle.members.items(), ("manifest.json", b"[]")]
    with pytest.raises(controller.DeploymentError, match="Duplicate archive members"):
        sanitize(tmp_path, bundle, members)


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE]
)
def test_outer_archive_links_and_special_files_are_forbidden(tmp_path, bundle, kind):
    header = tarfile.TarInfo("untrusted")
    header.type, header.linkname = kind, "/etc/onlinepolis-deploy/compose.yml"
    with pytest.raises(controller.DeploymentError, match="forbidden"):
        sanitize(tmp_path, bundle, [*bundle.members.items(), (header, b"")])


@pytest.mark.parametrize(
    "kind", [tarfile.REGTYPE, tarfile.XHDTYPE, tarfile.GNUTYPE_LONGNAME]
)
def test_oversized_headers_are_rejected_without_reading_declared_payload(
    tmp_path, bundle, monkeypatch, kind
):
    header = tarfile.TarInfo("oversized")
    header.type = kind
    header.size = controller.MAX_EXPANDED + 1
    source = tmp_path / "oversized.tar.gz"
    source.write_bytes(gzip.compress(header.tobuf(tarfile.USTAR_FORMAT), mtime=0))
    real_open, reads = gzip.open, []

    class GuardedStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size=-1):
            reads.append(size)
            assert 0 <= size <= 65536, "Parser attempted an unbounded payload read"
            return self.stream.read(size)

    monkeypatch.setattr(
        controller.gzip,
        "open",
        lambda *args, **kwargs: GuardedStream(real_open(*args, **kwargs)),
    )
    with pytest.raises(controller.DeploymentError, match="size|forbidden"):
        controller.sanitize_archive(source, tmp_path / "result.tar", bundle.request)
    assert reads == [512]


def test_outer_member_count_is_bounded(tmp_path, bundle, monkeypatch):
    monkeypatch.setattr(controller, "MAX_MEMBERS", 2)
    with pytest.raises(controller.DeploymentError, match="Excess archive members"):
        sanitize(tmp_path, bundle)


@pytest.mark.parametrize("limit", ["MAX_CONFIG", "MAX_MANIFEST", "MAX_EXPANDED"])
def test_outer_archive_and_metadata_sizes_are_bounded(
    tmp_path, bundle, monkeypatch, limit
):
    monkeypatch.setattr(controller, limit, 8192 if limit == "MAX_EXPANDED" else 8)
    with pytest.raises(controller.DeploymentError):
        sanitize(tmp_path, bundle)


def test_nested_gzip_layer_expansion_has_separate_budget(tmp_path, bundle, monkeypatch):
    monkeypatch.setattr(controller, "MAX_EXPANDED", 32768)
    expanded = b"\0" * 65536
    config = json.loads(bundle.config_blob)
    config["rootfs"]["diff_ids"] = [digest(expanded)]
    config_blob = json_bytes(config)
    members = {
        **bundle.members,
        CONFIG_PATH: config_blob,
        LAYER_PATH: gzip.compress(expanded, mtime=0),
    }
    with pytest.raises(controller.DeploymentError, match="Expanded image layers limit"):
        sanitize(
            tmp_path,
            bundle,
            members.items(),
            replace(bundle.request, config_digest=digest(config_blob)),
        )


def test_nonzero_trailing_archive_data_is_rejected(tmp_path, bundle):
    source = tmp_path / "trailing.tar.gz"
    source.write_bytes(
        gzip.compress(tar_bytes(bundle.members.items()) + b"hidden", mtime=0)
    )
    with pytest.raises(
        controller.DeploymentError, match="Unexpected trailing archive data"
    ):
        controller.sanitize_archive(source, tmp_path / "result.tar", bundle.request)
