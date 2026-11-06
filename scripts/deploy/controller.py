#!/usr/bin/python3 -I
"""Root-owned, fixed-policy deployment controller. Never execute a CI shell/script.

The key authorizes application replacement (including access to application data
and credentials). It does not independently authenticate GitHub provenance.
"""
import contextlib
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass


APP_SERVICES = ("web", "celery_worker", "celery_beat")
SERVICES = ("db", "redis", *APP_SERVICES, "nginx", "certbot")
MAX_COMPRESSED = 1024**3
MAX_EXPANDED = 2 * 1024**3
MAX_MANIFEST = 2 * 1024**2
MAX_CONFIG = 4 * 1024**2
MAX_MEMBERS = 4096
MAX_OUTPUT = 8 * 1024**2
RUN_ID = r"[1-9][0-9]{0,19}-[1-9][0-9]{0,5}"
ROOT_ENV = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/root",
    "DOCKER_CONFIG": "/root/.docker",
}
RUNTIME_FIELDS = (
    "Env",
    "Entrypoint",
    "Cmd",
    "Labels",
    "User",
    "WorkingDir",
    "StopSignal",
    "Healthcheck",
    "Volumes",
    "ExposedPorts",
)


class DeploymentError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise DeploymentError(message)


@dataclass(frozen=True)
class Request:
    operation: str
    run_id: str = ""
    revision: str = ""
    image_ref: str = ""
    config_digest: str = ""
    archive_sha256: str = ""
    size: int = 0


def parse_request(arguments):
    require(
        all(isinstance(arg, str) and arg.isascii() for arg in arguments),
        "Invalid request",
    )
    if arguments == ["status"]:
        return Request("status")
    require(len(arguments) in (2, 7), "Invalid request")
    operation, run_id = arguments[:2]
    require(re.fullmatch(RUN_ID, run_id), "Invalid release ID")
    if operation in ("activate", "health", "rollback") and len(arguments) == 2:
        return Request(operation, run_id)
    require(operation == "upload" and len(arguments) == 7, "Invalid request")
    _, _, revision, image_ref, config_digest, archive_sha256, size = arguments
    require(re.fullmatch(r"[0-9a-f]{40}", revision), "Invalid revision")
    require(
        re.fullmatch("insurance-broker:" + revision + "-" + RUN_ID, image_ref),
        "Invalid image reference",
    )
    require(
        re.fullmatch(r"sha256:[0-9a-f]{64}", config_digest), "Invalid config digest"
    )
    require(re.fullmatch(r"[0-9a-f]{64}", archive_sha256), "Invalid archive checksum")
    require(
        re.fullmatch(r"[1-9][0-9]{0,9}", size) and int(size) <= MAX_COMPRESSED,
        "Invalid upload size",
    )
    return Request(
        operation, run_id, revision, image_ref, config_digest, archive_sha256, int(size)
    )


def command(arguments, *, capture=False, timeout=240):
    """All child stdin is detached; never return application/CLI failure output."""
    process = subprocess.Popen(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=ROOT_ENV,
        cwd="/",
        start_new_session=True,
    )
    output = bytearray()
    try:
        if capture:
            deadline = time.monotonic() + timeout
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    require(remaining > 0, "Command timed out")
                    require(selector.select(remaining), "Command timed out")
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        selector.unregister(process.stdout)
                    else:
                        output.extend(chunk)
                        require(
                            len(output) <= MAX_OUTPUT, "Command output limit exceeded"
                        )
        require(process.wait(timeout=timeout) == 0, "Deployment command failed")
        return bytes(output)
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


class LimitedReader:
    def __init__(self, stream):
        self.stream, self.total = stream, 0

    def read(self, size=-1):
        size = 65536 if size < 0 else min(size, MAX_EXPANDED - self.total + 1)
        result = self.stream.read(size)
        self.total += len(result)
        require(self.total <= MAX_EXPANDED, "Expanded archive limit exceeded")
        return result


def member_name(name):
    path = PurePosixPath(name)
    require(
        len(name) <= 255 and name and "\\" not in name and "\x00" not in name,
        "Invalid archive member",
    )
    require(
        not path.is_absolute()
        and ".." not in path.parts
        and str(path) == name.rstrip("/"),
        "Invalid archive path",
    )
    return name.rstrip("/")


class SectionReader:
    def __init__(self, stream, remaining):
        self.stream, self.remaining = stream, remaining

    def read(self, size=-1):
        size = self.remaining if size < 0 else min(size, self.remaining)
        data = self.stream.read(size)
        require(len(data) == size, "Truncated archive")
        self.remaining -= len(data)
        return data


def archive_members(path):
    # Parse one fixed-size header before reading any untrusted payload. tarfile's
    # automatic PAX/longname parsing can allocate a huge extension before yield.
    with gzip.open(path, "rb") as expanded:
        bounded, count, declared = LimitedReader(expanded), 0, 0
        while True:
            header = bounded.read(512)
            require(len(header) == 512, "Truncated archive header")
            if header == b"\0" * 512:
                require(bounded.read(512) == b"\0" * 512, "Invalid archive terminator")
                while True:
                    padding = bounded.read(65536)
                    if not padding:
                        return
                    require(
                        not padding.strip(b"\0"), "Unexpected trailing archive data"
                    )
            member = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
            count += 1
            require(count <= MAX_MEMBERS, "Excess archive members")
            require(
                member.type in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE),
                "Archive links/extensions/devices are forbidden",
            )
            require(0 <= member.size <= MAX_EXPANDED, "Invalid archive member size")
            declared += member.size
            require(declared <= MAX_EXPANDED, "Declared archive limit exceeded")
            data = SectionReader(bounded, member.size)
            yield member, data
            while data.remaining:
                data.read(min(65536, data.remaining))
            padding = (-member.size) % 512
            require(bounded.read(padding) == b"\0" * padding, "Invalid archive padding")


def sanitize_archive(source, destination, request):
    """Repack only a single validated Docker image, excluding OCI/tag side graphs."""
    members, manifest = {}, None
    for member, stream in archive_members(source):
        name = member_name(member.name)
        require(name not in members, "Duplicate archive members")
        require(not member.isdir() or member.size == 0, "Invalid archive directory")
        members[name] = (member.size, member.isfile())
        if name == "manifest.json":
            require(
                member.isfile() and member.size <= MAX_MANIFEST,
                "Invalid Docker manifest",
            )
            manifest = json.loads(stream.read())
    require(
        isinstance(manifest, list) and len(manifest) == 1, "Expected one Docker image"
    )
    entry = manifest[0]
    require(isinstance(entry, dict), "Invalid Docker manifest")
    require(entry.get("RepoTags") == [request.image_ref], "Unexpected image tags")
    config_name = member_name(entry.get("Config", ""))
    layers = entry.get("Layers")
    require(isinstance(layers, list) and 0 < len(layers) <= 128, "Invalid image layers")
    layers = [member_name(name) for name in layers]
    require(
        len(set(layers)) == len(layers) and config_name not in layers,
        "Duplicate image paths",
    )
    require(
        config_name in members
        and members[config_name][1]
        and members[config_name][0] <= MAX_CONFIG,
        "Invalid image config",
    )
    require(
        all(name in members and members[name][1] for name in layers),
        "Missing image layer",
    )
    for member, stream in archive_members(source):
        if member_name(member.name) == config_name:
            config_blob = stream.read()
            break
    config = json.loads(config_blob)
    require(
        "sha256:" + hashlib.sha256(config_blob).hexdigest() == request.config_digest,
        "Image config digest mismatch",
    )
    require(
        config.get("os") == "linux" and config.get("architecture") == "amd64",
        "Image platform mismatch",
    )
    require(
        config.get("config", {})
        .get("Labels", {})
        .get("org.opencontainers.image.revision")
        == request.revision,
        "Image revision mismatch",
    )
    diff_ids = config.get("rootfs", {}).get("diff_ids")
    require(
        config.get("rootfs", {}).get("type") == "layers"
        and isinstance(diff_ids, list)
        and len(diff_ids) == len(layers),
        "Invalid root filesystem",
    )
    require(
        all(re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in diff_ids),
        "Invalid layer digest",
    )
    layer_names = {name: f"layer{index:03}.tar" for index, name in enumerate(layers)}
    expanded_layers = 0
    with tarfile.open(destination, "w", format=tarfile.USTAR_FORMAT) as clean:
        header = tarfile.TarInfo("config.json")
        header.mode, header.size = 0o600, len(config_blob)
        clean.addfile(header, io.BytesIO(config_blob))
        for member, stream in archive_members(source):
            name = member_name(member.name)
            if name not in layer_names:
                continue
            first = stream.read(min(2, member.size))
            prefixed = io.BufferedReader(PrefixReader(first, stream))
            layer = (
                gzip.GzipFile(fileobj=prefixed) if first == b"\x1f\x8b" else prefixed
            )
            with tempfile.TemporaryFile(dir=destination.parent) as temporary:
                digest, size = hashlib.sha256(), 0
                while True:
                    chunk = layer.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    expanded_layers += len(chunk)
                    require(
                        expanded_layers <= MAX_EXPANDED,
                        "Expanded image layers limit exceeded",
                    )
                    digest.update(chunk)
                    temporary.write(chunk)
                require(
                    "sha256:" + digest.hexdigest() == diff_ids[layers.index(name)],
                    "Image layer digest mismatch",
                )
                temporary.seek(0)
                header = tarfile.TarInfo(layer_names[name])
                header.mode, header.size = 0o600, size
                clean.addfile(header, temporary)
        payload = json.dumps(
            {
                "Config": "config.json",
                "RepoTags": [request.image_ref],
                "Layers": [layer_names[name] for name in layers],
            }
        )
        payload = ("[" + payload + "]").encode()
        header = tarfile.TarInfo("manifest.json")
        header.mode, header.size = 0o600, len(payload)
        clean.addfile(header, io.BytesIO(payload))
    return config


class PrefixReader(io.RawIOBase):
    def __init__(self, prefix, stream):
        self.prefix, self.stream = prefix, stream

    def readable(self):
        return True

    def readinto(self, buffer):
        first = self.prefix[: len(buffer)]
        self.prefix = self.prefix[len(first) :]
        tail = self.stream.read(len(buffer) - len(first))
        data = first + tail
        buffer[: len(data)] = data
        return len(data)


@dataclass(frozen=True)
class Paths:
    control: Path = Path("/etc/onlinepolis-deploy")
    state: Path = Path("/var/lib/onlinepolis-deploy")
    project: Path = Path("/root/insurance_broker")
    lock: Path = Path("/root/.local/state/onlinepolis-deploy.lock")


class Controller:
    def __init__(self, paths=Paths(), runner=command, owner_uid=0):
        self.paths, self.runner, self.owner_uid = paths, runner, owner_uid

    def secure(self, path, directory=False):
        info = path.lstat()
        require(
            info.st_uid == self.owner_uid and not info.st_mode & 0o022,
            "Untrusted deployment file ownership/permissions",
        )
        require(
            stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),
            "Deployment links/special files are forbidden",
        )
        require(directory or info.st_nlink == 1, "Deployment hard links are forbidden")

    def run(self, args, capture=False, timeout=240):
        return self.runner(args, capture=capture, timeout=timeout)

    def docker(self, *args, capture=False, timeout=240):
        return self.run(
            ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock", *args],
            capture,
            timeout,
        )

    def compose(self, *args, override=None, capture=False, timeout=240):
        files = [
            "-f",
            str(self.paths.control / "compose.yml"),
            "-f",
            str(self.paths.control / "security.override.yml"),
        ]
        if override is not None:
            files += ["-f", str(override)]
        return self.docker(
            "compose",
            "--compatibility",
            "--project-directory",
            str(self.paths.project),
            "-p",
            "insurance_broker",
            "--env-file",
            str(self.paths.project / ".env.prod"),
            *files,
            *args,
            capture=capture,
            timeout=timeout,
        )

    def source_hashes(self):
        paths = {
            "docker-compose.prod.yml": self.paths.control / "compose.yml",
            "scripts/deploy/security.override.yml": self.paths.control
            / "security.override.yml",
            "nginx/nginx.conf": self.paths.project / "nginx/nginx.conf",
            "nginx/default.conf": self.paths.project / "nginx/default.conf",
        }
        for directory in (
            self.paths.control,
            self.paths.project,
            self.paths.project / "nginx",
        ):
            self.secure(directory, True)
        for path in [*paths.values(), self.paths.project / ".env.prod"]:
            self.secure(path)
        return {name: sha256(path) for name, path in paths.items()}

    def validate_policy(self):
        hashes = self.source_hashes()
        policy = json.loads(self.compose("config", "--format", "json", capture=True))
        require(
            set(policy["services"]) == set(SERVICES), "Unexpected deployment services"
        )
        db_environment = policy["services"]["db"].get("environment", {})
        db_keys = {
            "DB_NAME": "POSTGRES_DB",
            "DB_USER": "POSTGRES_USER",
            "DB_PASSWORD": "POSTGRES_PASSWORD",  # pragma: allowlist secret
        }
        for legacy, primary in db_keys.items():
            require(db_environment.get(primary), "Missing database configuration")
            require(
                legacy not in db_environment
                or db_environment[legacy] == db_environment[primary],
                "Legacy database configuration differs from primary settings",
            )
        for service in APP_SERVICES:
            config = policy["services"][service]
            require(
                all(
                    config.get("environment", {}).get(legacy) == db_environment[primary]
                    for legacy, primary in db_keys.items()
                ),
                "Application database configuration differs from primary settings",
            )
            require(
                config.get("user") == "10001:10001" and config.get("entrypoint") == [],
                "Applications must run directly as UID/GID 10001",
            )
            require(
                set(config.get("cap_drop", [])) == {"ALL"}
                and not config.get("cap_add"),
                "Application capabilities must be dropped",
            )
            require(
                any(
                    value in ("no-new-privileges:true", "no-new-privileges")
                    for value in config.get("security_opt", [])
                ),
                "no-new-privileges is required",
            )
            require(
                not any(
                    config.get(key)
                    for key in (
                        "privileged",
                        "build",
                        "devices",
                        "volumes_from",
                        "group_add",
                        "use_api_socket",
                        "post_start",
                        "pre_start",
                        "pre_stop",
                    )
                ),
                "Unsafe application policy",
            )
            require(
                not any(
                    config.get(key) == "host"
                    for key in ("network_mode", "pid", "ipc", "userns_mode")
                ),
                "Host namespaces are forbidden",
            )
            for volume in config.get("volumes", []):
                allowed = {"/app/media", "/app/logs"}
                if service == "web":
                    allowed |= {"/app/staticfiles", "/app/server_backups"}
                require(volume["target"] in allowed, "Unexpected application mount")
                if volume["type"] == "bind":
                    require(
                        volume["target"] in ("/app/logs", "/app/server_backups"),
                        "Unexpected application bind target",
                    )
                    expected = (
                        self.paths.project / "logs"
                        if volume["target"] == "/app/logs"
                        else Path("/root/insurance_broker_backups")
                    )
                    require(
                        volume["source"] == str(expected),
                        "Unexpected application bind source",
                    )
                    require(
                        volume["target"] != "/app/server_backups"
                        or volume.get("read_only"),
                        "Backups must be read-only",
                    )
                else:
                    expected = {
                        "/app/media": "media_volume",
                        "/app/staticfiles": "static_volume",
                    }
                    require(
                        volume["type"] == "volume"
                        and volume["source"] == expected.get(volume["target"]),
                        "Unexpected application volume",
                    )
        return hashes

    @contextlib.contextmanager
    def locked(self):
        self.paths.state.mkdir(mode=0o700, exist_ok=True)
        self.secure(self.paths.state, True)
        self.secure(self.paths.lock.parent, True)
        lock = os.open(
            self.paths.lock,
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
        )
        try:
            info = os.fstat(lock)
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_uid == self.owner_uid
                and not info.st_mode & 0o022,
                "Unsafe deployment lock",
            )
            deadline = time.monotonic() + 3600
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    require(time.monotonic() < deadline, "Deployment lock timed out")
                    time.sleep(0.1)
            yield
        finally:
            os.close(lock)

    def release(self, run_id, create=False):
        base = self.paths.state / "releases"
        base.mkdir(mode=0o700, exist_ok=True)
        self.secure(base, True)
        path = base / run_id
        if create:
            path.mkdir(mode=0o700, exist_ok=True)
        if path.exists() or path.is_symlink():
            self.secure(path, True)
        return path

    def read_json(self, path):
        self.secure(path)
        require(
            path.stat().st_size <= 8 * MAX_CONFIG, "Deployment metadata limit exceeded"
        )
        return json.loads(path.read_text())

    def write_json(self, path, value, exclusive=False):
        if path.exists() or path.is_symlink():
            require(not exclusive, "Immutable release metadata already exists")
            self.secure(path)
        fd, name = tempfile.mkstemp(prefix=".metadata-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(value, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            if exclusive:
                os.link(name, path)
            else:
                os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)

    def upload(self, request, source):
        release = self.release(request.run_id, True)
        record = {
            key: getattr(request, key)
            for key in (
                "run_id",
                "revision",
                "image_ref",
                "config_digest",
                "archive_sha256",
                "size",
            )
        }
        existing = release / "upload.json"
        if existing.exists() or existing.is_symlink():
            stored = self.read_json(existing)
            require(
                all(stored.get(key) == value for key, value in record.items()),
                "Release payload is immutable",
            )
        fd, temporary = tempfile.mkstemp(prefix=".upload-", dir=release)
        temporary, sanitized = Path(temporary), release / ".sanitized-upload.tar"
        try:
            digest, remaining = hashlib.sha256(), request.size
            with os.fdopen(fd, "wb") as destination:
                while remaining:
                    chunk = source.read(min(65536, remaining))
                    require(chunk, "Incomplete upload")
                    destination.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                require(not source.read(1), "Excess upload data")
            require(
                digest.hexdigest() == request.archive_sha256, "Upload checksum mismatch"
            )
            if existing.exists():
                self.secure(release / "image.tar")
                require(
                    sha256(release / "image.tar") == stored["sanitized_sha256"],
                    "Stored image checksum mismatch",
                )
                return {"ok": True, "status": "uploaded", "idempotent": True}
            require(
                not sanitized.exists() and not sanitized.is_symlink(),
                "Unsafe staging file",
            )
            with sanitized.open("xb"):
                pass
            config = sanitize_archive(temporary, sanitized, request)
            record.update(image_config=config, sanitized_sha256=sha256(sanitized))
            os.link(sanitized, release / "image.tar")
            os.chmod(release / "image.tar", 0o400)
            self.write_json(existing, record, True)
            self.write_json(release / "state.json", {"status": "uploaded"})
            return {"ok": True, "status": "uploaded", "revision": request.revision}
        finally:
            temporary.unlink(missing_ok=True)
            sanitized.unlink(missing_ok=True)

    def image(self, reference):
        return json.loads(self.docker("image", "inspect", reference, capture=True))[0]

    def container(self, service, missing_ok=False):
        if missing_ok:
            present = self.docker(
                "ps",
                "-a",
                "--filter",
                "name=^/insurance_broker_" + service + "$",
                "--format",
                "{{.ID}}",
                capture=True,
            )
            if not present.strip():
                return None
        return json.loads(
            self.docker("inspect", "insurance_broker_" + service, capture=True)
        )[0]

    def snapshot(self, release, run_id):
        images = {service: self.container(service)["Image"] for service in APP_SERVICES}
        existing = release / "snapshot.json"
        if existing.exists() or existing.is_symlink():
            require(
                self.read_json(existing)["images"] == images,
                "Refusing to overwrite the original release snapshot",
            )
            self.write_json(release / "state.json", {"status": "prepared"})
            return
        for service, image_id in images.items():
            self.docker(
                "image", "tag", image_id, f"onlinepolis-rollback:{run_id}-{service}"
            )
        self.write_json(existing, {"images": images}, True)
        self.write_json(release / "state.json", {"status": "prepared"})

    def verify_image(self, metadata):
        image = self.image(metadata["image_ref"])
        config = metadata["image_config"]
        require(
            image["Os"] == "linux" and image["Architecture"] == "amd64",
            "Loaded image platform mismatch",
        )
        require(
            image["RootFS"]["Layers"] == config["rootfs"]["diff_ids"],
            "Loaded image filesystem mismatch",
        )
        for key in RUNTIME_FIELDS:
            default = (
                ""
                if key in ("User", "WorkingDir", "StopSignal")
                else []
                if key in ("Env", "Entrypoint", "Cmd")
                else {}
            )
            require(
                (image["Config"].get(key) or default)
                == (config["config"].get(key) or default),
                "Loaded image runtime mismatch",
            )
        require(
            re.fullmatch(r"sha256:[0-9a-f]{64}", image["Id"]),
            "Invalid local image identity",
        )
        return image["Id"]

    def oneoff(self, run_id, stage, *arguments):
        name = f"onlinepolis-deploy-{run_id}-{stage}"
        try:
            self.compose(
                "run",
                "--rm",
                "-T",
                "--interactive=false",
                "--no-deps",
                "--pull",
                "never",
                "--name",
                name,
                "web",
                *arguments,
                timeout=600,
            )
        finally:
            with contextlib.suppress(Exception):
                self.docker("rm", "-f", name)

    def switch(self, override=None):
        self.compose(
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--pull",
            "never",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "180",
            *APP_SERVICES,
            override=override,
        )
        self.compose(
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--pull",
            "never",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "90",
            "nginx",
            override=override,
        )
        self.compose("exec", "-T", "--interactive=false", "nginx", "nginx", "-t")
        self.compose(
            "exec", "-T", "--interactive=false", "nginx", "nginx", "-s", "reload"
        )

    def verify_services(self, images):
        states = {}
        for service in SERVICES:
            container = self.container(service)
            state, health = container["State"]["Status"], container["State"].get(
                "Health", {}
            ).get("Status")
            require(
                state == "running"
                and (
                    health == "healthy"
                    or service in ("celery_beat", "certbot")
                    and health is None
                ),
                "Production service is not healthy",
            )
            if service in APP_SERVICES:
                require(container["Image"] == images[service], "Running image mismatch")
                require(
                    container["Config"].get("User") == "10001:10001",
                    "Application runtime user mismatch",
                )
                host = container["HostConfig"]
                require(
                    not host.get("Privileged")
                    and set(host.get("CapDrop", [])) == {"ALL"},
                    "Application runtime privileges mismatch",
                )
                require(
                    any(
                        value in ("no-new-privileges", "no-new-privileges:true")
                        for value in host.get("SecurityOpt", [])
                    ),
                    "Application no-new-privileges missing",
                )
            states[service] = {"status": state, "health": health}
        page = self.run(
            [
                "/usr/bin/curl",
                "-q",
                "--noproxy",
                "*",
                "--fail",
                "--silent",
                "--max-time",
                "20",
                "--max-filesize",
                "1048576",
                "--resolve",
                "polis.insflow.ru:443:127.0.0.1",
                "--write-out",
                "\n%{http_code}",
                "https://polis.insflow.ru/accounts/login/",
            ],
            True,
            30,
        )
        require(
            page.endswith(b"\n200")
            and b'name="username"' in page
            and b'name="password"' in page,
            "HTTPS login verification failed",
        )
        return states

    def rollback(self, release, run_id):
        if not (release / "snapshot.json").exists():
            return {"ok": True, "status": "nothing_to_restore"}
        state, snapshot = self.read_json(release / "state.json"), self.read_json(
            release / "snapshot.json"
        )
        if state["status"] == "rolled_back":
            return {"ok": True, "status": "rolled_back", "idempotent": True}
        for service, old_id in snapshot["images"].items():
            current = self.container(service, missing_ok=True)
            require(
                current is None
                or current["Image"] in (old_id, state.get("new_image_id")),
                "Refusing to change an unrelated release",
            )
        for service, old_id in snapshot["images"].items():
            self.docker("image", "tag", old_id, f"insurance_broker_{service}:latest")
        if state.get("activated"):
            override = release / "rollback.json"
            self.write_json(
                override,
                {
                    "services": {
                        service: {"image": f"onlinepolis-rollback:{run_id}-{service}"}
                        for service in APP_SERVICES
                    }
                },
            )
            self.switch(override)
            self.verify_services(snapshot["images"])
        self.write_json(release / "state.json", {"status": "rolled_back"})
        return {
            "ok": True,
            "status": "rolled_back",
            "database_migrations_reversed": False,
        }

    def activate(self, release, run_id):
        metadata, state = self.read_json(release / "upload.json"), self.read_json(
            release / "state.json"
        )
        if state["status"] == "verified":
            return self.health(release)
        if state["status"] in ("prepared", "activating"):
            self.rollback(release, run_id)
            raise DeploymentError(
                "Interrupted activation recovered; review database compatibility before retry"
            )
        self.secure(release / "image.tar")
        require(
            sha256(release / "image.tar") == metadata["sanitized_sha256"],
            "Stored image checksum mismatch",
        )
        self.snapshot(release, run_id)
        try:
            self.docker(
                "image", "load", "--input", str(release / "image.tar"), timeout=600
            )
            image_id = self.verify_image(metadata)
            state = {"status": "prepared", "new_image_id": image_id, "activated": False}
            self.write_json(release / "state.json", state)
            for service in APP_SERVICES:
                self.docker(
                    "image",
                    "tag",
                    metadata["image_ref"],
                    f"insurance_broker_{service}:latest",
                )
            self.oneoff(
                run_id, "migrate", "python", "manage.py", "migrate", "--noinput"
            )
            self.oneoff(
                run_id, "static", "python", "manage.py", "collectstatic", "--noinput"
            )
            state.update(status="activating", activated=True)
            self.write_json(release / "state.json", state)
            self.switch()
            services = self.verify_services(
                {service: image_id for service in APP_SERVICES}
            )
            state["status"] = "verified"
            self.write_json(release / "state.json", state)
            return {
                "ok": True,
                "status": "verified",
                "revision": metadata["revision"],
                "image_id": image_id,
                "services": services,
            }
        except BaseException:
            try:
                self.rollback(release, run_id)
            except Exception:
                raise DeploymentError(
                    "Activation failed; recovery needs administrator attention"
                ) from None
            raise DeploymentError(
                "Activation failed; saved application images restored; database migrations were not reversed"
            ) from None

    def health(self, release):
        state = self.read_json(release / "state.json")
        require(
            state["status"] == "verified" and state.get("activated"),
            "Release was not activated",
        )
        services = self.verify_services(
            {service: state["new_image_id"] for service in APP_SERVICES}
        )
        metadata = self.read_json(release / "upload.json")
        return {
            "ok": True,
            "status": "verified",
            "revision": metadata["revision"],
            "image_id": state["new_image_id"],
            "services": services,
        }

    def execute(self, request, source=None):
        with self.locked():
            hashes = self.validate_policy()
            if request.operation == "status":
                return {
                    "ok": True,
                    "protocol": 1,
                    "config_sha256": hashes["docker-compose.prod.yml"],
                    "config_source_hashes": hashes,
                }
            if request.operation == "upload":
                return self.upload(request, source)
            release = self.release(request.run_id)
            if request.operation == "rollback":
                return self.rollback(release, request.run_id)
            require(release.is_dir(), "Unknown release")
            return (
                self.activate(release, request.run_id)
                if request.operation == "activate"
                else self.health(release)
            )


def main(arguments=None):
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    def timeout(signum, frame):
        raise DeploymentError("Controller operation timed out")

    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(1800)
    try:
        require(os.geteuid() == 0, "Controller must run as root")
        request = parse_request(sys.argv[1:] if arguments is None else arguments)
        if request.operation == "upload":
            signal.alarm(600)
        reply, code = Controller().execute(request, sys.stdin.buffer), 0
    except DeploymentError as error:
        reply, code = {"ok": False, "error": str(error)}, 1
    except Exception:
        # Do not echo input, environment, Docker output or application exceptions.
        reply, code = {
            "ok": False,
            "error": "Deployment request failed; administrator review may be required",
        }, 1
    try:
        print(json.dumps(reply, sort_keys=True), flush=True)
    except BrokenPipeError:
        pass
    finally:
        signal.alarm(0)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
