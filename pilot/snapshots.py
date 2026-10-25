"""Read base files and apply ordinary text patches inside temporary directories."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import difflib
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import tokenize

MAX_PATCH_BYTES = 5 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 200


class PatchError(ValueError):
    """The patch cannot be analyzed with the pilot's supported input format."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(
    args: list[str], *, cwd: Path, data: bytes | None = None, timeout: float = 30
) -> subprocess.CompletedProcess:
    git_executable = shutil.which("git")
    if not git_executable:
        raise PatchError("Git executable not found on PATH.")
    env = dict(os.environ)
    # Read/apply text only: no user git aliases, attributes, external filters or hooks.
    for name in list(env):
        if name.startswith("GIT_"):
            env.pop(name)
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_ATTR_NOSYSTEM="1",
        GIT_LITERAL_PATHSPECS="1",
        GIT_TERMINAL_PROMPT="0",
    )
    try:
        return subprocess.run(
            [
                git_executable,
                "-c",
                f"core.hooksPath={os.devnull}",
                "-c",
                "core.fsmonitor=false",
                *args,
            ],
            cwd=cwd,
            input=data,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PatchError(f"Git could not complete: {exc}") from exc


def safe_path(name: str) -> str:
    p = PurePosixPath(name)
    if (
        not name
        or not p.parts
        or p.is_absolute()
        or ".." in p.parts
        or "\\" in name
        or any(c in name for c in "\x00\t\r\n")
        or any(part.lower() == ".git" for part in p.parts)
        or ":" in p.parts[0]
        or name.startswith("-")
    ):
        raise PatchError(f"Unsupported or unsafe patch path: {name!r}")
    return p.as_posix()


def patch_paths(patch: bytes, cwd: Path) -> list[str]:
    if not patch.strip():
        raise PatchError("Patch is empty.")
    if len(patch) > MAX_PATCH_BYTES:
        raise PatchError("Patch exceeds the 5 MiB pilot limit.")
    try:
        text = patch.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PatchError("The pilot accepts UTF-8 unified text patches only.") from exc
    if "\x00" in text:
        raise PatchError("Binary patch content is unsupported.")
    forbidden = r"^(?:rename from |rename to |copy from |copy to |GIT binary patch|Binary files |(?:new file mode|old mode|new mode|deleted file mode) (?:120000|160000))"
    if re.search(forbidden, text, re.M):
        raise PatchError(
            "Renames, copies, binary changes, symlinks and submodules are unsupported; split these from the text patch."
        )
    stat = git(["apply", "--numstat", "-z", "-"], cwd=cwd, data=patch)
    if stat.returncode:
        raise PatchError(
            "Invalid unified diff: " + stat.stderr.decode(errors="replace")[:1000]
        )
    paths = []
    for record in stat.stdout.split(b"\0"):
        if not record:
            continue
        fields = record.split(b"\t", 2)
        if len(fields) != 3 or fields[0] == b"-" or fields[1] == b"-":
            raise PatchError("Unsupported numstat record or binary file.")
        try:
            name = safe_path(fields[2].decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise PatchError("Patch paths must be UTF-8.") from exc
        if name in paths:
            raise PatchError("Repeated file entries are unsupported: " + name)
        paths.append(name)
    if not paths:
        raise PatchError("Patch contains no supported file changes.")
    if len(paths) > MAX_FILES:
        raise PatchError(f"Patch exceeds the {MAX_FILES}-file pilot limit.")
    return paths


def decode_source(data: bytes, path: str) -> str:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
        return data.decode(encoding)
    except (SyntaxError, UnicodeError, LookupError) as exc:
        raise PatchError(f"Cannot decode Python source {path}: {exc}") from exc


def read_worktree(repo: Path, path: str) -> bytes | None:
    current = repo
    for part in PurePosixPath(path).parts:
        current = current / part
        if current.is_symlink():
            raise PatchError("Symlink paths are unsupported: " + path)
    if not current.exists():
        return None
    if not current.is_file():
        raise PatchError("Not a regular source file: " + path)
    if current.stat().st_size > MAX_FILE_BYTES:
        raise PatchError("Base file exceeds 2 MiB: " + path)
    return current.read_bytes()


def read_commit(repo: Path, commit: str, path: str) -> bytes | None:
    # Do not silently materialize a file through a symlink/submodule ancestor.
    parents = list(PurePosixPath(path).parents)[:-1]
    for parent in parents:
        listing = git(["ls-tree", "-z", commit, "--", parent.as_posix()], cwd=repo)
        if listing.returncode:
            raise PatchError("Cannot inspect Git parent path: " + parent.as_posix())
        if listing.stdout and not listing.stdout.startswith(b"040000 tree "):
            raise PatchError(
                "Git parent is not an ordinary directory: " + parent.as_posix()
            )
    listing = git(["ls-tree", "-z", commit, "--", path], cwd=repo)
    if listing.returncode:
        raise PatchError(listing.stderr.decode(errors="replace")[:1000])
    if not listing.stdout:
        return None
    records = listing.stdout.rstrip(b"\0").split(b"\0")
    if len(records) != 1:
        raise PatchError("Ambiguous Git tree path: " + path)
    metadata, listed_path = records[0].split(b"\t", 1)
    mode, kind, oid = metadata.split()
    if (
        listed_path.decode("utf-8") != path
        or mode not in [b"100644", b"100755"]
        or kind != b"blob"
    ):
        raise PatchError("Git path is not a regular blob: " + path)
    size = git(["cat-file", "-s", oid.decode()], cwd=repo)
    if size.returncode or int(size.stdout) > MAX_FILE_BYTES:
        raise PatchError("Git blob unavailable or exceeds 2 MiB: " + path)
    blob = git(["cat-file", "blob", oid.decode()], cwd=repo)
    if blob.returncode:
        raise PatchError("Could not read Git blob: " + path)
    return blob.stdout


def changed_lines(before: str, after: str) -> tuple[set[int], set[int], dict[int, int]]:
    removed: set[int] = set()
    added: set[int] = set()
    mapping: dict[int, int] = {}
    for tag, i, j, k, last in difflib.SequenceMatcher(
        None,
        before.splitlines(),
        after.splitlines(),
        autojunk=False,
    ).get_opcodes():
        if tag == "equal":
            mapping.update((x + 1, y + 1) for x, y in zip(range(i, j), range(k, last)))
        else:
            removed.update(range(i + 1, j + 1))
            added.update(range(k + 1, last + 1))
    return removed, added, mapping


@dataclass
class Snapshot:
    path: str
    before: str | None
    after: str | None
    before_sha256: str | None
    after_sha256: str | None
    removed_lines: set[int]
    added_lines: set[int]
    line_map: dict[int, int]


@contextmanager
def materialize(repo: Path, patch: bytes, base: str = "worktree"):
    repo = repo.expanduser().resolve()
    if not repo.is_dir():
        raise PatchError("Repository/base directory does not exist: " + str(repo))
    paths = patch_paths(patch, repo)
    commit = None
    if base != "worktree":
        ref = git(
            ["rev-parse", "--verify", "--end-of-options", base + "^{commit}"], cwd=repo
        )
        if ref.returncode:
            raise PatchError("Cannot resolve --base to a local Git commit.")
        commit = ref.stdout.decode().strip()
    original = {
        p: read_commit(repo, commit, p) if commit else read_worktree(repo, p)
        for p in paths
    }
    with tempfile.TemporaryDirectory(prefix="patch-gate-pilot-") as td:
        work = Path(td)
        for path, source in original.items():
            if source is not None:
                target = work / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source)
        applied = git(["apply", "--whitespace=nowarn", "-"], cwd=work, data=patch)
        if applied.returncode:
            raise PatchError(
                "Patch does not apply to this base: "
                + applied.stderr.decode(errors="replace")[:1500]
            )
        snapshots = []
        for path in paths:
            target = work / path
            if target.exists() and (not target.is_file() or target.is_symlink()):
                raise PatchError("Patch produced a nonregular file: " + path)
            if target.exists() and target.stat().st_size > MAX_FILE_BYTES:
                raise PatchError("Patched file exceeds 2 MiB: " + path)
            after = target.read_bytes() if target.exists() else None
            before = original[path]
            if not path.endswith(".py"):
                continue
            b = decode_source(before, path) if before is not None else None
            a = decode_source(after, path) if after is not None else None
            removed, added, mapping = changed_lines(b or "", a or "")
            snapshots.append(
                Snapshot(
                    path,
                    b,
                    a,
                    digest(before) if before is not None else None,
                    digest(after) if after is not None else None,
                    removed,
                    added,
                    mapping,
                )
            )
        yield (
            snapshots,
            {
                "repo": str(repo),
                "base": base,
                "resolved_commit": commit,
                "patch_sha256": digest(patch),
                "all_changed_paths": paths,
                "unscanned_non_python_paths": [
                    p for p in paths if not p.endswith(".py")
                ],
            },
        )
