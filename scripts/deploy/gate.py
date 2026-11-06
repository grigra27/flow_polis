#!/usr/bin/python3 -I
"""Forced SSH command: expose only the deployment controller protocol."""

import os
import re
import shlex
import sys

CONTROLLER = "/usr/local/sbin/onlinepolis-deploy-controller"
MAX_COMMAND_BYTES = 1024
MAX_ARCHIVE_BYTES = 1024**3
RUN_ID = re.compile(r"[1-9][0-9]{0,19}-[1-9][0-9]{0,5}\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
ARCHIVE_SHA = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_REF = re.compile(
    r"insurance-broker:([0-9a-f]{40})-[1-9][0-9]{0,19}-[1-9][0-9]{0,5}\Z"
)


def parse_command(command):
    """Reject shell syntax and malformed arguments before invoking sudo."""
    if not isinstance(command, str) or not command:
        raise ValueError("command required")
    if len(command.encode("utf-8")) > MAX_COMMAND_BYTES or any(
        ord(char) < 32 or ord(char) == 127 for char in command
    ):
        raise ValueError("invalid command encoding")
    args = shlex.split(command, posix=True)
    if args == ["status"]:
        return args
    if (
        len(args) == 2
        and args[0] in {"activate", "health", "rollback"}
        and RUN_ID.fullmatch(args[1])
    ):
        return args
    if len(args) != 7 or args[0] != "upload":
        raise ValueError("unsupported command")
    _, run_id, revision, image_ref, config_digest, archive_sha, size = args
    image_match = IMAGE_REF.fullmatch(image_ref)
    if not (
        RUN_ID.fullmatch(run_id)
        and REVISION.fullmatch(revision)
        and image_match
        and image_match.group(1) == revision
        and DIGEST.fullmatch(config_digest)
        and ARCHIVE_SHA.fullmatch(archive_sha)
        and re.fullmatch(r"[1-9][0-9]{0,9}", size)
        and int(size) <= MAX_ARCHIVE_BYTES
    ):
        raise ValueError("invalid upload metadata")
    return args


def main():
    try:
        args = parse_command(os.environ.get("SSH_ORIGINAL_COMMAND"))
    except (ValueError, UnicodeError):
        # Never echo attacker-controlled commands or archive metadata to logs.
        print("Deployment command rejected.", file=sys.stderr)
        return 2
    try:
        # execv preserves upload stdin; no shell and no user-controlled executable.
        os.execv("/usr/bin/sudo", ["sudo", "-n", "--", CONTROLLER, *args])
    except OSError:
        print("Deployment controller unavailable.", file=sys.stderr)
        return 126


if __name__ == "__main__":
    sys.exit(main())
