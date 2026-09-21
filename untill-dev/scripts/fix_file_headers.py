"""Fix headers in new source files when the agent finishes responding."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Set

from build_header_from_policy import (
    HeaderPolicyError,
    blank_lines_after,
    detect_newline,
    find_git_root,
    is_excluded,
    load_policy,
    match_existing_header,
    render_required_prefix,
    run_git,
    split_preamble,
)


NEWLINE = re.compile(r"\r\n|\n|\r")
LEADING_BLANK_LINES = re.compile(r"^(?:[ \t]*(?:\r\n|\n|\r))+")


def new_files(repo_root: Path) -> Set[str]:
    """Find untracked files and additions, including staged and intent-to-add paths."""
    files: Set[str] = set()
    for arguments in (
        ["ls-files", "--others", "--exclude-standard", "-z"],
        ["diff", "--cached", "--name-only", "--diff-filter=A", "--no-renames", "-z"],
        ["diff", "--name-only", "--diff-filter=A", "--no-renames", "-z"],
    ):
        result = run_git(arguments, repo_root)
        if result.returncode:
            raise HeaderPolicyError(result.stderr.strip() or "cannot list new Git paths")
        files.update(path for path in result.stdout.split("\0") if path)
    return files


def strip_old_headers(content: str, template: Dict[str, Any], policy: Dict[str, Any]) -> str:
    """Remove header comments in the leading comment region; retain other text.

    Only metadata lines are removed from comments without an ending delimiter,
    so adjacent directives and descriptive comments survive.
    """
    kept: List[str] = []
    position = 0
    while position < len(content):
        whitespace = re.match(r"\s*", content[position:]).group(0)
        kept.append(whitespace)
        position += len(whitespace)
        if position == len(content):
            break

        matching = next(
            (
                (name, style)
                for name, style in policy["commentStyles"]
                if content.startswith(style["start"], position)
            ),
            None,
        )
        if matching is None:
            break
        name, style = matching
        if "end" in style:
            closing = content.find(style["end"], position + len(style["start"]))
            if closing == -1:
                if policy["headerPattern"].search(content[position:]):
                    raise HeaderPolicyError("cannot safely replace an unterminated header comment")
                break
            end = closing + len(style["end"])
            comment = content[position:end]
        else:
            newline = NEWLINE.search(content, position)
            end = newline.start() if newline else len(content)
            comment = content[position:end]
        is_header = policy["headerPattern"].search(comment) is not None
        if name not in template["commentStyles"] and not is_header:
            break
        if is_header:
            # Consume the comment's newline, but preserve blank lines and body.
            trailing_newline = NEWLINE.match(content, end)
            position = trailing_newline.end() if trailing_newline else end
        else:
            kept.append(content[position:end])
            position = end
    kept.append(content[position:])
    return "".join(kept)


def repair_file(path: Path, repo_root: Path, policy: Dict[str, Any]) -> bool:
    """Repair one regular file, assuming no other process modifies it during repair."""
    template = policy["templatesByExtension"].get(path.suffix.lower())
    if (
        template is None
        or not path.is_file()
        or is_excluded(policy, path.relative_to(repo_root).as_posix())
    ):
        return False

    original = path.read_bytes()
    encoding = policy["header"]["encoding"]
    content = original.decode(encoding)
    bom = "\ufeff" if content.startswith("\ufeff") else ""
    content_without_bom = content[len(bom):]
    existing = match_existing_header(content_without_bom, template, policy)
    if existing is not None:
        existing_header, body = existing
        body = LEADING_BLANK_LINES.sub("", body)
        # A second leading header makes the prefix invalid rather than exempting
        # the file from duplicate cleanup.
        if strip_old_headers(body, template, policy) == body:
            newline = detect_newline(content)
            prefix = existing_header + newline * (blank_lines_after(policy) + 1)
        else:
            existing = None
    if existing is None:
        prefix = render_required_prefix(path, policy, content)
        if prefix is None:
            return False
        _, body = split_preamble(content_without_bom, template)
        body = strip_old_headers(body, template, policy)
        if blank_lines_after(policy):
            # The rendered prefix owns this boundary. Remove separators left by an
            # old header (or present in a new file) before adding the configured one.
            body = LEADING_BLANK_LINES.sub("", body)
    updated = (bom + prefix + body).encode(encoding)
    if updated == original:
        return False

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".untill-header-", suffix=".tmp", delete=False
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(updated)
        shutil.copymode(path, temporary_path)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return True


def required_string(payload: Dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise HeaderPolicyError(f"hook input must include a non-empty {key}")
    return value


def hook(payload: Dict[str, Any]) -> None:
    event = required_string(payload, "hook_event_name")
    if event != "Stop":
        raise HeaderPolicyError(f"unsupported hook event: {event}")
    cwd = Path(required_string(payload, "cwd")).resolve()
    result = run_git(["rev-parse", "--show-toplevel"], cwd)
    if result.returncode:
        if "not a git repository" not in result.stderr.lower():
            raise HeaderPolicyError(result.stderr.strip() or "cannot locate Git working tree")
        return
    repo_root = Path(result.stdout.rstrip("\r\n")).resolve()
    policy = load_policy()
    errors = []
    for relative in sorted(new_files(repo_root)):
        try:
            repair_file(repo_root / relative, repo_root, policy)
        except (HeaderPolicyError, OSError, ValueError) as error:
            errors.append(f"{relative}: {error}")
    if errors:
        raise HeaderPolicyError("\n".join(errors))


def main(arguments: List[str]) -> int:
    sys.stderr.reconfigure(encoding="utf-8")
    hook_mode = arguments == ["--hook"]
    if not arguments or (arguments[0].startswith("--") and not hook_mode):
        print("usage: fix_file_headers.py FILE [FILE ...] | --hook", file=sys.stderr)
        return 2
    try:
        if hook_mode:
            payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise HeaderPolicyError("hook input must be a JSON object")
            hook(payload)
        else:
            policy = load_policy()
            for argument in arguments:
                path = Path(os.path.abspath(argument))
                if not path.is_file():
                    raise HeaderPolicyError(f"not a regular file: {path}")
                if path.suffix.lower() not in policy["templatesByExtension"]:
                    continue
                if any(part.lower() == ".git" for part in path.parts):
                    continue
                repo_root = find_git_root(path)
                repair_file(path, repo_root, policy)
    except (HeaderPolicyError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"source-file-headers: {error}", file=sys.stderr)
        # Stop errors must not block completion and start another agent turn.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
