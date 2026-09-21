"""Read the header policy and build the required header text."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Tuple


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = PLUGIN_ROOT / "header-policy.json"
VARIABLE_TOKEN = re.compile(r"\{\{([^{}]+)\}\}")


class HeaderPolicyError(RuntimeError):
    """Raised when runtime context or source content cannot produce a safe header."""


def load_policy() -> Dict[str, Any]:
    """Load the trusted policy and prepare its lookups and regular expressions."""
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    header = policy["header"]
    recognition = header["recognition"]

    policy["headerPattern"] = re.compile(recognition["pattern"])
    # Prefer a longer delimiter if configured starts overlap.
    policy["commentStyles"] = sorted(
        recognition["commentStyles"].items(),
        key=lambda item: len(item[1]["start"]),
        reverse=True,
    )

    policy["templatesByExtension"] = {}
    for template in header["templates"]:
        placement = template.get("placement", header["placement"])
        overrides = {
            extension.lower(): name
            for extension, name in template.get("placementOverrides", {}).items()
        }
        for extension in template["extensions"]:
            extension = extension.lower()
            policy["templatesByExtension"][extension] = {
                **template,
                "placementRule": header["placements"][overrides.get(extension, placement)],
            }

    for variable in policy["variables"].values():
        if "forbiddenPattern" in variable:
            variable["forbiddenValue"] = re.compile(variable["forbiddenPattern"])

    policy["excludedPathPatterns"] = [
        glob_to_regex(pattern) for pattern in policy["excludedPathGlobs"]
    ]
    return policy


def run_git(arguments: List[str], working_directory: Path) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(working_directory), *arguments],
            check=False,
            capture_output=True,
            encoding="utf-8",
            env={**os.environ, "LC_ALL": "C"},
            timeout=5,
        )
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as error:
        raise HeaderPolicyError(f"cannot run Git: {error}") from error


def find_git_root(file_path: Path) -> Path:
    result = run_git(["rev-parse", "--show-toplevel"], file_path.parent)
    if result.returncode != 0:
        detail = result.stderr.strip() or "not inside a Git working tree"
        raise HeaderPolicyError(detail)
    return Path(result.stdout.rstrip("\r\n")).resolve()


def resolve_variables(repo_root: Path, policy: Dict[str, Any]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for name, variable in policy["variables"].items():
        label = name
        if variable["source"] == "system-date":
            value = date.today().strftime(variable["format"])
        else:
            key = variable["key"]
            label = f"Git {key}"
            result = run_git(["config", "--get", key], repo_root)
            if result.returncode not in (0, 1):
                raise HeaderPolicyError(result.stderr.strip() or f"cannot read {label}")
            value = result.stdout.rstrip("\r\n") if result.returncode == 0 else ""
        if not value and variable.get("required", False):
            raise HeaderPolicyError(
                f"{label} is not configured; configure it before creating source files"
            )
        forbidden = variable.get("forbiddenValue")
        if forbidden is not None and forbidden.search(value):
            raise HeaderPolicyError(f"{label} contains unsafe source-header characters")
        values[name] = value
    return values


def glob_to_regex(glob: str) -> Pattern[str]:
    segments = glob.replace("\\", "/").split("/")
    expression = "^"
    for index, segment in enumerate(segments):
        is_last = index == len(segments) - 1
        if segment == "**":
            expression += ".*" if is_last else "(?:[^/]+/)*"
        else:
            for character in segment:
                if character == "*":
                    expression += "[^/]*"
                elif character == "?":
                    expression += "[^/]"
                else:
                    expression += re.escape(character)
            if not is_last:
                expression += "/"
    flags = re.IGNORECASE if os.name == "nt" else 0
    return re.compile(f"{expression}$", flags)


def is_excluded(policy: Dict[str, Any], relative_path: str) -> bool:
    return any(pattern.fullmatch(relative_path) for pattern in policy["excludedPathPatterns"])


def detect_newline(content: str) -> str:
    match = re.search(r"\r\n|\n|\r", content)
    return match.group(0) if match else "\n"


def first_line(content: str) -> str:
    return re.split(r"\r\n|\n|\r", content, maxsplit=1)[0]


def split_preamble(content: str, template: Dict[str, Any]) -> Tuple[str, str]:
    """Preserve a leading line according to the selected placement rule."""
    placement = template["placementRule"]
    prefix = placement.get("leadingLinePrefix")
    if prefix is None:
        return "", content
    leading_line = first_line(content)
    if not leading_line.startswith(prefix):
        if placement.get("required", False):
            raise HeaderPolicyError(placement["missingMessage"])
        return "", content
    newline = re.search(r"\r\n|\n|\r", content)
    body = content[newline.end():] if newline else ""
    return leading_line + detect_newline(content), body


def render_required_prefix(
    file_path: Path, policy: Dict[str, Any], content: str
) -> Optional[str]:
    template = policy["templatesByExtension"].get(file_path.suffix.lower())
    if template is None:
        return None

    repo_root = find_git_root(file_path)
    try:
        relative_path = file_path.relative_to(repo_root).as_posix()
    except ValueError as error:
        raise HeaderPolicyError("target file is outside its Git working tree") from error
    if is_excluded(policy, relative_path):
        return None

    newline = detect_newline(content)
    opening_lines = template.get("openingLines", [])
    closing_lines = template.get("closingLines", [])
    variables = resolve_variables(repo_root, policy)
    header_lines = [
        *opening_lines,
        *(f"{template['linePrefix']}{line}" for line in policy["header"]["contentLines"]),
        *closing_lines,
    ]
    header = VARIABLE_TOKEN.sub(
        lambda match: variables[match.group(1)],
        newline.join(header_lines),
    )

    content_without_bom = content[1:] if content.startswith("\ufeff") else content
    preamble, _ = split_preamble(content_without_bom, template)
    return f"{preamble}{header}{newline}"
