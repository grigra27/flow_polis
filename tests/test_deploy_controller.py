"""Controller protocol/state contracts. No Docker, production data or network."""
import copy
from dataclasses import replace
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile

import pytest


SPEC = importlib.util.spec_from_file_location(
    "onlinepolis_deploy_controller_contract",
    Path(__file__).parents[1] / "scripts/deploy/controller.py",
)
controller = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = controller
SPEC.loader.exec_module(controller)
REVISION = "a" * 40
RUN = "123456-1"
REFERENCE = f"insurance-broker:{REVISION}-123456-1"
NATIVE_IMAGE = "sha256:" + "b" * 64


def valid_bundle():
    layer = io.BytesIO()
    with tarfile.open(fileobj=layer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        header = tarfile.TarInfo("app/example.txt")
        header.size = 7
        archive.addfile(header, io.BytesIO(b"example"))
    layer = layer.getvalue()
    config = {
        "os": "linux",
        "architecture": "amd64",
        "rootfs": {
            "type": "layers",
            "diff_ids": ["sha256:" + hashlib.sha256(layer).hexdigest()],
        },
        "config": {
            "Labels": {"org.opencontainers.image.revision": REVISION},
            "Env": ["PYTHONUNBUFFERED=1"],
            "Cmd": ["python"],
            "Entrypoint": ["/entrypoint.sh"],
            "WorkingDir": "/app",
        },
    }
    config_blob = json.dumps(config).encode()
    manifest = [
        {
            "Config": "original-config.json",
            "RepoTags": [REFERENCE],
            "Layers": ["original-layer.tar"],
        }
    ]
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, payload in (
            ("original-config.json", config_blob),
            ("original-layer.tar", layer),
            ("manifest.json", json.dumps(manifest).encode()),
        ):
            header = tarfile.TarInfo(name)
            header.size = len(payload)
            archive.addfile(header, io.BytesIO(payload))
    payload = gzip.compress(output.getvalue(), mtime=0)
    request = controller.Request(
        "upload",
        RUN,
        REVISION,
        REFERENCE,
        "sha256:" + hashlib.sha256(config_blob).hexdigest(),
        hashlib.sha256(payload).hexdigest(),
        len(payload),
    )
    return request, payload


class Docker:
    def __init__(self, paths):
        self.paths = paths
        self.calls, self.tags, self.loaded = [], {}, {}
        self.images = {
            service: "sha256:" + hashlib.sha256(service.encode()).hexdigest()
            for service in controller.APP_SERVICES
        }
        self.original = dict(self.images)
        self.fail = None
        common = {
            "environment": {
                "DB_NAME": "fixture_database",
                "DB_USER": "fixture_user",
                "DB_PASSWORD": "fixture_password",  # pragma: allowlist secret
            },
            "user": "10001:10001",
            "entrypoint": [],
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "volumes": [
                {"type": "volume", "source": "media_volume", "target": "/app/media"},
                {
                    "type": "bind",
                    "source": str(paths.project / "logs"),
                    "target": "/app/logs",
                },
            ],
        }
        self.policy = {
            "services": {
                service: copy.deepcopy(common)
                if service in controller.APP_SERVICES
                else {}
                for service in controller.SERVICES
            }
        }
        self.policy["services"]["db"]["environment"] = {
            "POSTGRES_DB": "fixture_database",
            "POSTGRES_USER": "fixture_user",
            "POSTGRES_PASSWORD": "fixture_password",  # pragma: allowlist secret
        }

    def failure(self, stage):
        if self.fail == stage:
            self.fail = None
            raise controller.DeploymentError("Synthetic failure")

    def __call__(self, args, *, capture=False, timeout=240):
        self.calls.append(list(args))
        if args[0] == "/usr/bin/curl":
            self.failure("http")
            return b'<input name="username"><input name="password">\n200'
        assert args[:3] == ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock"]
        args = args[3:]
        if args[:2] == ["image", "load"]:
            self.failure("load")
            with tarfile.open(args[-1]) as archive:
                self.loaded = json.load(archive.extractfile("config.json"))
                assert archive.getnames() == [
                    "config.json",
                    "layer000.tar",
                    "manifest.json",
                ]
            self.tags[REFERENCE] = NATIVE_IMAGE
            return b""
        if args[:2] == ["image", "inspect"]:
            config = dict(self.loaded["config"])
            config.setdefault("User", "")
            return json.dumps(
                [
                    {
                        "Id": NATIVE_IMAGE,
                        "Os": "linux",
                        "Architecture": "amd64",
                        "Config": config,
                        "RootFS": {"Layers": self.loaded["rootfs"]["diff_ids"]},
                    }
                ]
            ).encode()
        if args[:2] == ["image", "tag"]:
            self.tags[args[3]] = self.tags.get(args[2], args[2])
            return b""
        if args[0] == "ps":
            service = (
                args[args.index("--filter") + 1]
                .removeprefix("name=^/insurance_broker_")
                .removesuffix("$")
            )
            return b"container-id" if service in self.images else b""
        if args[0] == "inspect":
            service = args[1].removeprefix("insurance_broker_")
            image = (
                self.images[service]
                if service in controller.APP_SERVICES
                else "infra-" + service
            )
            return json.dumps(
                [
                    {
                        "Image": image,
                        "State": {
                            "Status": "running",
                            **(
                                {"Health": {"Status": "healthy"}}
                                if service not in ("celery_beat", "certbot")
                                else {}
                            ),
                        },
                        "Config": {"User": "10001:10001"},
                        "HostConfig": {
                            "Privileged": False,
                            "CapDrop": ["ALL"],
                            "SecurityOpt": ["no-new-privileges:true"],
                        },
                    }
                ]
            ).encode()
        if args[0] == "rm":
            return b""
        assert args[0] == "compose"
        operation = next(
            value for value in args if value in ("config", "run", "up", "exec")
        )
        if operation == "config":
            return json.dumps(self.policy).encode()
        if operation == "run":
            self.failure("migrate" if "migrate" in args else "static")
        if operation == "up":
            assert all(flag in args for flag in ("--no-deps", "--no-build", "--wait"))
            assert args[args.index("--pull") + 1] == "never"
            override = next(
                (Path(value) for value in args if value.endswith("rollback.json")), None
            )
            if args[-1] == "nginx":
                if override is None:
                    self.failure("nginx_up")
            else:
                assert args[-3:] == list(controller.APP_SERVICES)
                if override:
                    config = json.loads(override.read_text())
                    self.images = {
                        service: self.tags[config["services"][service]["image"]]
                        for service in controller.APP_SERVICES
                    }
                else:
                    self.images = {
                        service: self.tags[f"insurance_broker_{service}:latest"]
                        for service in controller.APP_SERVICES
                    }
                    self.failure("app_up")
        return b""


@pytest.fixture
def setup(tmp_path):
    paths = controller.Paths(
        tmp_path / "control",
        tmp_path / "state",
        tmp_path / "project",
        tmp_path / "shared.lock",
    )
    paths.control.mkdir(mode=0o700)
    paths.project.mkdir(mode=0o700)
    (paths.project / "nginx").mkdir(mode=0o700)
    for path in (
        paths.control / "compose.yml",
        paths.control / "security.override.yml",
        paths.project / ".env.prod",
        paths.project / "nginx/nginx.conf",
        paths.project / "nginx/default.conf",
    ):
        path.write_text("fixed administrator-owned input")
    docker = Docker(paths)
    instance = controller.Controller(paths, docker, os.getuid())
    request, payload = valid_bundle()
    return instance, docker, request, payload


def uploaded(setup):
    instance, docker, request, payload = setup
    assert instance.execute(request, io.BytesIO(payload))["status"] == "uploaded"
    return instance, docker, request, instance.release(RUN)


def test_valid_protocol_and_build_attempt_can_differ_from_release_attempt():
    request, _ = valid_bundle()
    args = [
        "upload",
        "123456-2",
        request.revision,
        request.image_ref,
        request.config_digest,
        request.archive_sha256,
        str(request.size),
    ]
    parsed = controller.parse_request(args)
    assert parsed.run_id == "123456-2" and parsed.image_ref.endswith("123456-1")


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["sh"],
        ["status", "extra"],
        ["activate", "../root"],
        ["health", "1-1\n"],
        ["rollback", "0-1"],
        ["activate", "1-1", "--privileged"],
    ],
)
def test_protocol_rejects_shell_paths_extra_args_and_invalid_ids(arguments):
    with pytest.raises(controller.DeploymentError):
        controller.parse_request(arguments)


def test_status_exposes_only_fixed_managed_hashes(setup):
    instance, _, _, _ = setup
    result = instance.execute(controller.parse_request(["status"]))
    assert result["protocol"] == 1
    assert set(result["config_source_hashes"]) == {
        "docker-compose.prod.yml",
        "scripts/deploy/security.override.yml",
        "nginx/nginx.conf",
        "nginx/default.conf",
    }
    assert (
        result["config_sha256"]
        == result["config_source_hashes"]["docker-compose.prod.yml"]
    )
    assert "administrator-owned" not in json.dumps(result)


def test_upload_is_immutable_idempotent_and_does_not_touch_docker_runtime(setup):
    instance, docker, request, payload = setup
    instance.execute(request, io.BytesIO(payload))
    assert instance.execute(request, io.BytesIO(payload))["idempotent"] is True
    with pytest.raises(controller.DeploymentError, match="immutable"):
        instance.execute(replace(request, archive_sha256="f" * 64), io.BytesIO(payload))
    assert docker.images == docker.original
    assert not any("load" in call or "up" in call for call in docker.calls)


@pytest.mark.parametrize(
    "change", [{"size": -1}, {"size": 100000}, {"archive_sha256": "0" * 64}]
)
def test_failed_upload_has_no_manifest_or_runtime_changes(setup, change):
    instance, docker, request, payload = setup
    if change.get("size") == -1:
        change = {"size": request.size - 1}
    with pytest.raises(controller.DeploymentError):
        instance.execute(replace(request, **change), io.BytesIO(payload))
    assert not (instance.release(RUN) / "upload.json").exists()
    assert docker.images == docker.original


def test_staging_symlink_is_rejected_without_following_it(setup, tmp_path):
    instance, docker, request, payload = setup
    outside = tmp_path / "outside"
    outside.mkdir()
    instance.paths.state.mkdir(mode=0o700)
    (instance.paths.state / "releases").mkdir(mode=0o700)
    (instance.paths.state / "releases" / RUN).symlink_to(
        outside, target_is_directory=True
    )
    # Symlink permission bits differ by OS; either guard must reject the link.
    with pytest.raises(controller.DeploymentError):
        instance.execute(request, io.BytesIO(payload))
    assert list(outside.iterdir()) == []
    assert docker.images == docker.original


@pytest.mark.parametrize(
    "key,value",
    [
        ("user", "root"),
        ("entrypoint", ["gosu", "app"]),
        ("cap_drop", []),
        ("security_opt", []),
        ("privileged", True),
        ("network_mode", "host"),
    ],
)
def test_privileged_or_image_controlled_runtime_policy_is_rejected(setup, key, value):
    instance, docker, request, payload = setup
    docker.policy["services"]["web"][key] = value
    with pytest.raises(controller.DeploymentError):
        instance.execute(request, io.BytesIO(payload))
    assert not instance.paths.state.joinpath("releases", RUN).exists()


@pytest.mark.parametrize(
    "primary,legacy",
    [
        ("POSTGRES_DB", "DB_NAME"),
        ("POSTGRES_USER", "DB_USER"),
        ("POSTGRES_PASSWORD", "DB_PASSWORD"),
    ],
)
def test_legacy_database_env_must_match_primary_without_exposing_values(
    setup, primary, legacy
):
    instance, docker, _, _ = setup
    environment = docker.policy["services"]["db"]["environment"]
    environment[legacy] = "private_fixture_mismatch"
    with pytest.raises(controller.DeploymentError, match="Legacy database") as error:
        instance.execute(controller.parse_request(["status"]))
    assert "private_fixture_mismatch" not in str(error.value)
    environment[legacy] = environment[primary]
    assert instance.execute(controller.parse_request(["status"]))["protocol"] == 1


@pytest.mark.parametrize(
    "primary", ["POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"]
)
def test_missing_primary_database_setting_is_rejected(setup, primary):
    instance, docker, _, _ = setup
    docker.policy["services"]["db"]["environment"][primary] = ""
    with pytest.raises(controller.DeploymentError, match="Missing database"):
        instance.execute(controller.parse_request(["status"]))


@pytest.mark.parametrize("service", controller.APP_SERVICES)
def test_app_database_setting_must_match_primary_database(setup, service):
    instance, docker, _, _ = setup
    docker.policy["services"][service]["environment"][
        "DB_NAME"
    ] = "different_fixture_db"
    with pytest.raises(controller.DeploymentError, match="Application database"):
        instance.execute(controller.parse_request(["status"]))


def test_activate_reuses_one_loaded_image_and_keeps_infrastructure_out_of_up(setup):
    instance, docker, request, release = uploaded(setup)
    result = instance.execute(controller.parse_request(["activate", RUN]))
    assert result["status"] == "verified"
    assert set(docker.images.values()) == {NATIVE_IMAGE}
    assert (
        instance.execute(controller.parse_request(["health", RUN]))["image_id"]
        == NATIVE_IMAGE
    )
    assert (
        instance.execute(controller.parse_request(["activate", RUN]))["status"]
        == "verified"
    )
    snapshot = instance.read_json(release / "snapshot.json")
    assert snapshot["images"] == docker.original
    for call in docker.calls:
        if "up" in call:
            assert call[-1] == "nginx" or call[-3:] == list(controller.APP_SERVICES)
        assert "build" not in call and "down" not in call


@pytest.mark.parametrize(
    "failure", ["load", "migrate", "static", "app_up", "nginx_up", "http"]
)
def test_activation_failures_restore_original_images_and_aliases(setup, failure):
    instance, docker, request, release = uploaded(setup)
    docker.fail = failure
    with pytest.raises(controller.DeploymentError, match="restored"):
        instance.execute(controller.parse_request(["activate", RUN]))
    assert docker.images == docker.original
    assert all(
        docker.tags[f"insurance_broker_{service}:latest"] == image
        for service, image in docker.original.items()
    )
    assert instance.read_json(release / "state.json")["status"] == "rolled_back"
    assert (
        instance.execute(controller.parse_request(["rollback", RUN]))["idempotent"]
        is True
    )


def test_interrupted_activation_recovers_without_overwriting_original_snapshot(setup):
    instance, docker, request, release = uploaded(setup)
    instance.snapshot(release, RUN)
    original = (release / "snapshot.json").read_bytes()
    instance.write_json(
        release / "state.json",
        {"status": "activating", "activated": True, "new_image_id": NATIVE_IMAGE},
    )
    docker.images["web"] = NATIVE_IMAGE
    with pytest.raises(
        controller.DeploymentError, match="Interrupted activation recovered"
    ):
        instance.execute(controller.parse_request(["activate", RUN]))
    assert (release / "snapshot.json").read_bytes() == original
    assert docker.images == docker.original


def test_snapshot_cannot_be_replaced_by_partial_new_runtime(setup):
    instance, docker, request, release = uploaded(setup)
    instance.snapshot(release, RUN)
    docker.images["web"] = NATIVE_IMAGE
    with pytest.raises(controller.DeploymentError, match="original release snapshot"):
        instance.snapshot(release, RUN)
    assert instance.read_json(release / "snapshot.json")["images"] == docker.original


def test_rollback_can_recreate_a_missing_app_container(setup):
    instance, docker, request, release = uploaded(setup)
    instance.snapshot(release, RUN)
    instance.write_json(
        release / "state.json",
        {"status": "activating", "activated": True, "new_image_id": NATIVE_IMAGE},
    )
    del docker.images["web"]
    assert (
        instance.execute(controller.parse_request(["rollback", RUN]))["status"]
        == "rolled_back"
    )
    assert docker.images == docker.original


def test_rollback_refuses_to_change_unrelated_release(setup):
    instance, docker, request, release = uploaded(setup)
    instance.snapshot(release, RUN)
    docker.images["web"] = "sha256:" + "c" * 64
    before = dict(docker.images)
    with pytest.raises(controller.DeploymentError, match="unrelated release"):
        instance.execute(controller.parse_request(["rollback", RUN]))
    assert docker.images == before


def test_unknown_release_rollback_is_a_noop(setup):
    instance, docker, _, _ = setup
    assert (
        instance.execute(controller.parse_request(["rollback", "999-1"]))["status"]
        == "nothing_to_restore"
    )
    assert docker.images == docker.original
