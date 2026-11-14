#!/usr/bin/python3 -I
"""Administrator-installed hourly retention, serialized with deployment.

Default is a dry run. Only verified releases beyond the newest six are removed.
All container images and retained releases' forward/rollback images are protected.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

RELEASES = Path("/var/lib/onlinepolis-deploy/releases")
LOCK = Path("/root/.local/state/onlinepolis-deploy.lock")
RUN = r"[1-9][0-9]{0,19}-[1-9][0-9]{0,5}"
FILES = {
    "state.json",
    "upload.json",
    "snapshot.json",
    "rollback.json",
    "image.tar",
    "image.tar.archived.gz",
}


def docker(*args):
    return subprocess.check_output(
        ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock", *args],
        stdin=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=300,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/root"},
    ).decode()


def trusted(path, directory=False):
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not kind(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError("Unsafe maintenance path: " + str(path))
    if not directory and info.st_nlink != 1:
        raise RuntimeError("Hard-linked maintenance file: " + str(path))


def load_releases():
    for path in [RELEASES.parent, RELEASES]:
        trusted(path, True)
    releases = []
    for path in RELEASES.iterdir():
        if not re.fullmatch(RUN, path.name):
            raise RuntimeError("Unexpected release directory")
        trusted(path, True)
        for child in path.iterdir():
            trusted(child)
            if child.name not in FILES:
                raise RuntimeError("Unexpected release file: " + str(child))

        def read(name):
            file = path / name
            return json.loads(file.read_text()) if file.exists() else {}

        releases.append(
            {
                "id": path.name,
                "state": read("state.json"),
                "upload": read("upload.json"),
                "snapshot": read("snapshot.json"),
            }
        )
    return releases


def plan(releases, containers, images, keep=6):
    """Return obsolete release IDs and tags, preserving all recovery references."""
    if keep < 6:
        raise ValueError("Keep at least six verified releases")
    ordered = sorted(
        releases, key=lambda r: tuple(map(int, r["id"].split("-"))), reverse=True
    )
    live = {c["Image"] for c in containers}
    verified = [r for r in ordered if r["state"].get("status") == "verified"]
    protected = {r["id"] for r in verified[:keep]}
    protected.update(
        r["id"]
        for r in ordered
        if r["state"].get("status") != "verified"
        or r["state"].get("new_image_id") in live
    )
    protected_images = set(live)
    protected_refs = set()
    for release in ordered:
        if release["id"] in protected:
            protected_images.update(release["snapshot"].get("images", {}).values())
            image_id = release["state"].get("new_image_id")
            if image_id:
                protected_images.add(image_id)
            ref = release["upload"].get("image_ref")
            if ref:
                protected_refs.add(ref)
    obsolete = {r["id"] for r in ordered if r["id"] not in protected}
    cutoff = (
        tuple(map(int, verified[keep - 1]["id"].split("-")))
        if len(verified) >= keep
        else (0, 0)
    )
    tags = []
    for entry in images:
        tag, image_id = entry["tag"], entry["id"]
        if image_id in protected_images or tag in protected_refs:
            continue
        match = re.fullmatch(r"insurance-broker:[0-9a-f]{40}-(" + RUN + ")", tag)
        if not match:
            match = re.fullmatch(
                r"onlinepolis-rollback:(" + RUN + r")-(web|celery_worker|celery_beat)",
                tag,
            )
        # Also collect old tags whose metadata expired on a previous run while
        # their image was still needed by the oldest retained rollback snapshot.
        if (
            match
            and match[1] not in protected
            and tuple(map(int, match[1].split("-"))) < cutoff
        ):
            tags.append(tag)
    return (
        sorted(obsolete),
        sorted(set(tags)),
        sorted(protected_images),
        sorted(protected_refs),
    )


def maintain(apply=False):
    # Same inode/lock as Controller.locked(); skip rather than wait during deploy.
    trusted(LOCK.parent, True)
    fd = os.open(LOCK, os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(fd, "r+") as lock:
        trusted(LOCK)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"skipped": "deployment lock busy"}))
            return
        releases = load_releases()
        ids = docker("ps", "-aq").split()
        containers = json.loads(docker("inspect", *ids)) if ids else []
        # Fail closed if production is absent or its app containers disagree.
        apps = [
            c
            for c in containers
            if c["Name"]
            in {
                "/insurance_broker_web",
                "/insurance_broker_celery_worker",
                "/insurance_broker_celery_beat",
            }
        ]
        if len(apps) != 3 or len({c["Image"] for c in apps}) != 1:
            raise RuntimeError("Expected three application containers with one image")
        current = apps[0]["Image"]
        if not any(
            r["state"].get("status") == "verified"
            and r["state"].get("new_image_id") == current
            for r in releases
        ):
            raise RuntimeError("Current image has no verified release")
        images = []
        for line in docker(
            "image", "ls", "--no-trunc", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}"
        ).splitlines():
            tag, image_id = line.split()
            images.append({"tag": tag, "id": image_id})
        obsolete, tags, protected_images, protected_refs = plan(
            releases, containers, images
        )
        # Verify recovery images exist before deleting anything.
        for ref in protected_images + protected_refs:
            docker("image", "inspect", "--format", "{{.Id}}", ref)
        archive_bytes = sum(
            p.stat().st_size for rid in obsolete for p in (RELEASES / rid).iterdir()
        )
        report = {
            "apply": apply,
            "remove_releases": obsolete,
            "remove_tags": tags,
            "archive_bytes": archive_bytes,
            "protected_images": protected_images,
        }
        print(json.dumps(report), flush=True)
        if apply:
            # Delete tags first: failure keeps metadata available for a later retry.
            for tag in tags:
                docker("image", "rm", tag)  # No --force, no global prune, no volumes.
            for rid in obsolete:
                path = RELEASES / rid
                for child in path.iterdir():
                    trusted(child)
                    if child.name not in FILES:
                        raise RuntimeError("Release changed during maintenance")
                    child.unlink()
                path.rmdir()
            print(
                json.dumps(
                    {"removed_releases": len(obsolete), "removed_tags": len(tags)}
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise RuntimeError("Run manually as root")
        maintain(args.apply)
    except Exception as error:
        # Never print captured Docker inspection/configuration or stderr.
        print("Retention failed: " + type(error).__name__, file=sys.stderr)
        sys.exit(1)
