"""Test header generation, file repair, and hook behavior."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PLUGIN_ROOT / "scripts" / "fix_file_headers.py"
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import build_header_from_policy


class HeaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="untill header tests ")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.repo = self.base / "repo with spaces"
        self.repo.mkdir()
        empty_config = self.base / "empty-gitconfig"
        empty_config.write_text("", encoding="utf-8")
        self.environment = os.environ.copy()
        for key in list(self.environment):
            if key.startswith("GIT_"):
                del self.environment[key]
        self.environment.update({
            "GIT_CONFIG_GLOBAL": str(empty_config),
            "GIT_CONFIG_NOSYSTEM": "1",
            "TMPDIR": str(self.base),
            "TEMP": str(self.base),
            "TMP": str(self.base),
        })
        self.policy = build_header_from_policy.load_policy()
        self.dialects = list(self.policy["templatesByExtension"].items())
        self.default = self.dialects[0]
        self.required = next(
            dialect for dialect in self.dialects if dialect[1]["placementRule"].get("required")
        )
        self.author_key = next(
            variable["key"] for variable in self.policy["variables"].values()
            if variable["source"] == "git-config"
        )
        self.git("init", "--quiet")
        self.git("config", self.author_key, "Header Test Author")
        self.git("config", "user.email", "headers@example.test")

    def git(self, *arguments):
        return subprocess.run(
            ["git", "-C", str(self.repo), *arguments],
            env=self.environment, check=True, capture_output=True,
        )

    def write(self, relative, content):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return path

    def source(self, name="new", content="body\n", dialect=None):
        return self.write(name + (dialect or self.default)[0], content)

    def run_script(self, *arguments, payload=None, expected=0, script=SCRIPT_PATH):
        result = subprocess.run(
            [sys.executable, str(script), *map(str, arguments)],
            input=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None,
            cwd=self.repo, env=self.environment, capture_output=True,
        )
        self.assertEqual(result.returncode, expected, result.stderr.decode("utf-8"))
        self.assertEqual(result.stdout, b"")
        return result

    def stop(self, cwd=None, expected=0):
        return self.run_script("--hook", payload={
            "hook_event_name": "Stop", "cwd": str(cwd or self.repo),
            "session_id": "session-1", "stop_hook_active": False,
        }, expected=expected)

    def content_lines(self, author="Header Test Author"):
        values = {
            name: date.today().strftime(variable["format"])
            if variable["source"] == "system-date" else author
            for name, variable in self.policy["variables"].items()
        }
        return [
            re.sub(r"\{\{([^{}]+)\}\}", lambda match: values[match[1]], line)
            for line in self.policy["header"]["contentLines"]
        ]

    def header(self, dialect=None, newline="\n", author="Header Test Author"):
        template = (dialect or self.default)[1]
        return newline.join([
            *template.get("openingLines", []),
            *(template["linePrefix"] + line for line in self.content_lines(author)),
            *template.get("closingLines", []),
            *([""] * (self.policy["header"].get("blankLinesAfter", 0) + 1)),
        ])

    def preamble(self, dialect, newline="\n"):
        prefix = dialect[1]["placementRule"].get("leadingLinePrefix")
        return prefix + "interpreter" + newline if prefix else ""

    @staticmethod
    def comment(style, lines, newline="\n"):
        if "end" in style:
            return newline.join([style["start"], *lines, style["end"], ""])
        return "".join(style["start"] + " " + line + newline for line in lines)

    def test_every_configured_extension_gets_its_header(self):
        paths = []
        for index, dialect in enumerate(self.dialects):
            leading = self.preamble(dialect)
            path = self.source(str(index), leading + "body\n", dialect)
            paths.append((path, leading + self.header(dialect) + "body\n"))
        self.run_script(*(path for path, _ in paths))
        for path, expected in paths:
            with self.subTest(path=path.name):
                self.assertEqual(path.read_bytes(), expected.encode())

    def test_wrong_and_duplicate_headers_are_replaced(self):
        path = self.source(content=self.header(author="Old Author") + self.header() + "body\n")
        self.run_script(path)
        self.assertEqual(path.read_bytes(), (self.header() + "body\n").encode())

    def test_wrong_fixed_header_text_is_replaced(self):
        wrong = self.header().replace(
            "unTill Software Development Group B.V.", "Wrong Company"
        )
        path = self.source(content=wrong + "body\n")
        self.run_script(path)
        self.assertEqual(path.read_bytes(), (self.header() + "body\n").encode())

    def test_partial_headers_and_all_configured_comment_styles_are_recognized(self):
        for style in self.policy["header"]["recognition"]["commentStyles"].values():
            for line in self.content_lines("Old Author"):
                with self.subTest(style=style, line=line):
                    path = self.source(content=self.comment(style, [line]) + "body\n")
                    self.run_script(path)
                    self.assertEqual(path.read_bytes(), (self.header() + "body\n").encode())

    def test_line_metadata_is_removed_without_losing_adjacent_directives(self):
        for dialect in self.dialects:
            template = dialect[1]
            for name in template["commentStyles"]:
                style = self.policy["header"]["recognition"]["commentStyles"][name]
                if "end" in style:
                    continue
                with self.subTest(dialect=dialect[0], style=name):
                    leading = self.preamble(dialect)
                    directive = self.comment(style, ["directive"])
                    description = self.comment(style, ["description"])
                    path = self.source(content=(
                        leading + directive + self.comment(style, self.content_lines("Old"))
                        + "\n" + description + "body\n"
                    ), dialect=dialect)
                    self.run_script(path)
                    expected = leading + self.header(dialect) + directive + "\n" + description + "body\n"
                    self.assertEqual(path.read_bytes(), expected.encode())

    def test_unrelated_comments_and_body_are_preserved(self):
        for name in self.default[1]["commentStyles"]:
            style = self.policy["header"]["recognition"]["commentStyles"][name]
            with self.subTest(style=name):
                body = self.comment(style, ["Unrelated documentation."]) + "\nbody\n"
                path = self.source(content=body)
                self.run_script(path)
                self.assertEqual(path.read_bytes(), (self.header() + body).encode())

    def test_unconfigured_comment_starts_are_not_scanned_as_comments(self):
        style = next(
            style for name, style in self.policy["commentStyles"]
            if name not in self.default[1]["commentStyles"]
        )
        body = self.comment(style, ["ordinary content"]) + self.header(author="Body Author") + "body\n"
        path = self.source(content=body)
        self.run_script(path)
        self.assertEqual(path.read_bytes(), (self.header() + body).encode())

    def test_bom_preamble_and_line_endings_are_preserved(self):
        for dialect in self.dialects:
            for newline in ("\n", "\r\n", "\r"):
                with self.subTest(dialect=dialect[0], newline=repr(newline)):
                    leading = "\ufeff" + self.preamble(dialect, newline)
                    path = self.source(content=leading + "body" + newline, dialect=dialect)
                    self.run_script(path)
                    self.assertEqual(
                        path.read_bytes(),
                        (leading + self.header(dialect, newline) + "body" + newline).encode(),
                    )

    def test_optional_preambles_can_be_absent(self):
        for dialect in self.dialects:
            rule = dialect[1]["placementRule"]
            if rule.get("leadingLinePrefix") and not rule.get("required"):
                path = self.source(content="body\n", dialect=dialect)
                self.run_script(path)
                self.assertEqual(path.read_bytes(), (self.header(dialect) + "body\n").encode())

    def test_empty_files_and_preamble_without_final_newline(self):
        empty = self.source("empty", "")
        leading = self.preamble(self.required)
        preamble_only = self.source("preamble-only", leading.rstrip("\n"), self.required)
        self.run_script(empty, preamble_only)
        self.assertEqual(empty.read_bytes(), self.header().encode())
        self.assertEqual(preamble_only.read_bytes(), (leading + self.header(self.required)).encode())

    def test_correct_files_are_not_rewritten(self):
        for template in self.policy["header"]["templates"]:
            dialect = (template["extensions"][0], self.policy["templatesByExtension"][template["extensions"][0]])
            for newline in ("\n", "\r\n", "\r"):
                with self.subTest(dialect=dialect[0], newline=repr(newline)):
                    content = self.preamble(dialect, newline) + self.header(dialect, newline) + "body" + newline
                    path = self.source(content=content, dialect=dialect)
                    os.utime(path, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
                    before = path.stat()
                    self.run_script(path)
                    self.assertEqual(path.read_bytes(), content.encode())
                    self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
                    self.assertEqual(path.stat().st_ino, before.st_ino)

    def test_existing_header_keeps_original_variable_values(self):
        dialect = next(dialect for dialect in self.dialects if dialect[0] == ".go")
        current_year = str(date.today().year)
        old_year = str(date.today().year - 1)
        header = self.header(dialect, author="Original Author").replace(
            f"Copyright (c) {current_year}-present",
            f"Copyright (c) {old_year}-present",
        )
        content = header + "package voedger\n"
        path = self.source("existing", content, dialect)
        self.git("config", "--unset", self.author_key)
        os.utime(path, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
        before = path.stat()
        self.run_script(path)
        self.assertEqual(path.read_bytes(), content.encode())
        self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(path.stat().st_ino, before.st_ino)

    def test_repair_is_idempotent(self):
        path = self.source(content="\n" + self.header(author="Old") + "\nbody\n")
        self.run_script(path)
        original = path.read_bytes()
        self.run_script(path)
        self.assertEqual(path.read_bytes(), original)

    def test_go_header_has_exactly_one_blank_line_before_package(self):
        dialect = next(dialect for dialect in self.dialects if dialect[0] == ".go")
        expected = self.header(dialect) + "package voedger\n"
        for name, content in (
            ("fresh", "package voedger\n"),
            ("legacy", self.header(dialect)[:-1] + "package voedger\n"),
            ("extra", self.header(dialect) + "\n\npackage voedger\n"),
        ):
            with self.subTest(content=name):
                path = self.source(name, content, dialect)
                self.run_script(path)
                self.assertEqual(path.read_bytes(), expected.encode())
                self.run_script(path)
                self.assertEqual(path.read_bytes(), expected.encode())

    def test_literal_unicode_git_value(self):
        author = "Denis Ж $& $$ $" + chr(96) + " $' {{literal}}"
        self.git("config", self.author_key, author)
        path = self.source("имя with spaces")
        self.run_script(path)
        self.assertEqual(path.read_bytes(), (self.header(author=author) + "body\n").encode())

    def test_permissions_are_preserved(self):
        path = self.source(content=self.preamble(self.required) + "body\n", dialect=self.required)
        path.chmod(0o755)
        before = path.stat().st_mode
        self.run_script(path)
        self.assertEqual(path.stat().st_mode, before)

    def test_policy_exclusions_and_unsupported_files_skip_content_validation(self):
        self.git("config", "--unset", self.author_key)
        paths = [self.write("unsupported", b"unchanged\xff\0")]
        for pattern in self.policy["excludedPathGlobs"]:
            relative = pattern.replace("**/", "")
            if relative.endswith("/**"):
                relative = relative[:-2] + "excluded" + self.default[0]
            elif relative.endswith(".*"):
                relative = relative[:-2] + self.default[0]
            relative = relative.replace("*", "sample").replace("?", "x")
            paths.append(self.write(relative, b"unchanged\xff\0"))
        self.run_script(*paths)
        self.assertTrue(all(path.read_bytes() == b"unchanged\xff\0" for path in paths))

    def test_missing_git_value_fails_without_touching_file(self):
        self.git("config", "--unset", self.author_key)
        path = self.source()
        result = self.run_script(path, expected=1)
        self.assertIn(f"Git {self.author_key} is not configured".encode(), result.stderr)
        self.assertEqual(path.read_bytes(), b"body\n")

    def test_forbidden_git_value_is_rejected(self):
        delimiter = next(style["end"] for _, style in self.policy["commentStyles"] if "end" in style)
        for value in ("Bad " + delimiter, "Bad\nValue", "Bad\tValue"):
            with self.subTest(value=value):
                self.git("config", self.author_key, value)
                path = self.source()
                self.run_script(path, expected=1)
                self.assertEqual(path.read_bytes(), b"body\n")

    def test_missing_required_preamble_fails_without_guessing(self):
        path = self.source(dialect=self.required)
        result = self.run_script(path, expected=1)
        self.assertIn(self.required[1]["placementRule"]["missingMessage"].encode(), result.stderr)
        self.assertEqual(path.read_bytes(), b"body\n")

    def test_unclosed_header_is_unchanged(self):
        style = next(style for _, style in self.policy["commentStyles"] if "end" in style)
        unclosed = style["start"] + "\n" + self.content_lines()[0] + "\nbody\n"
        path = self.source(content=unclosed)
        self.run_script(path, expected=1)
        self.assertEqual(path.read_bytes(), unclosed.encode())

    def test_stop_repairs_untracked_files_and_preserves_committed_paths(self):
        tracked = self.source("tracked")
        self.git("add", tracked.name)
        self.git("commit", "--quiet", "-m", "Existing source")
        tracked.write_bytes(b"edited\n")
        self.git("add", tracked.name)
        untracked = self.source("untracked")
        existing_header = self.header(author="Original Author") + "body\n"
        new = self.source(content=existing_header)
        self.stop()
        self.assertEqual(untracked.read_bytes(), (self.header() + "body\n").encode())
        self.assertEqual(new.read_bytes(), existing_header.encode())
        self.assertEqual(tracked.read_bytes(), b"edited\n")

    def test_stop_repairs_multiple_new_files_in_one_batch(self):
        paths = [self.source("nested/" + str(index)) for index in range(4)]
        self.stop()
        for path in paths:
            self.assertEqual(path.read_bytes(), (self.header() + "body\n").encode())

    def test_staged_creations_are_detected_without_updating_index(self):
        path = self.source()
        self.git("add", path.name)
        self.stop()
        self.assertEqual(path.read_bytes(), (self.header() + "body\n").encode())
        self.assertEqual(self.git("show", ":" + path.name).stdout, b"body\n")

    def test_intent_to_add_files_are_detected(self):
        path = self.source()
        self.git("add", "--intent-to-add", path.name)
        self.stop()
        self.assertEqual(path.read_bytes(), (self.header() + "body\n").encode())

    def test_repeated_stops_preserve_correct_files_and_find_new_ones(self):
        first = self.source("first")
        self.stop()
        before = first.stat()
        second = self.source("second")
        self.stop()
        for path in (first, second):
            self.assertEqual(path.read_bytes(), (self.header() + "body\n").encode())
        self.assertEqual(first.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(first.stat().st_ino, before.st_ino)

    def test_stop_from_subdirectory_finds_unicode_paths_in_whole_worktree(self):
        self.environment["PYTHONIOENCODING"] = "cp1251"
        subdirectory = self.repo / "subdirectory"
        subdirectory.mkdir()
        path = self.source("имя with spaces")
        self.stop(cwd=subdirectory)
        self.assertEqual(path.read_bytes(), (self.header() + "body\n").encode())

    def test_files_committed_before_stop_are_unchanged(self):
        path = self.source()
        self.git("add", path.name)
        self.git("commit", "--quiet", "-m", "Already committed")
        self.stop()
        self.assertEqual(path.read_bytes(), b"body\n")

    def test_staged_rename_repairs_destination_without_updating_index(self):
        path = self.source()
        self.git("add", path.name)
        self.git("commit", "--quiet", "-m", "Original path")
        renamed = self.repo / ("renamed" + self.default[0])
        self.git("mv", path.name, renamed.name)
        self.stop()
        self.assertEqual(renamed.read_bytes(), (self.header() + "body\n").encode())
        self.assertEqual(self.git("show", ":" + renamed.name).stdout, b"body\n")

    def test_deleted_additions_are_skipped(self):
        path = self.source()
        self.git("add", path.name)
        path.unlink()
        self.stop()
        self.assertFalse(path.exists())

    def test_gitignored_files_are_skipped(self):
        path = self.source()
        self.write(".gitignore", path.name + "\n")
        self.stop()
        self.assertEqual(path.read_bytes(), b"body\n")

    def test_stop_respects_policy_exclusions_and_unsupported_formats(self):
        self.git("config", "--unset", self.author_key)
        paths = [self.write("unsupported", b"unchanged\xff\0")]
        for pattern in self.policy["excludedPathGlobs"]:
            if pattern.endswith("/**"):
                folder = pattern.replace("**/", "")[:-3]
                paths.append(self.source(folder + "/excluded"))
        self.stop()
        self.assertEqual(paths[0].read_bytes(), b"unchanged\xff\0")
        self.assertTrue(all(path.read_bytes() == b"body\n" for path in paths[1:]))

    def test_nested_repositories_are_skipped(self):
        nested = self.repo / "nested"
        nested.mkdir()
        subprocess.run(["git", "init", "--quiet", str(nested)], check=True, capture_output=True)
        path = self.source("nested/new")
        self.stop()
        self.assertEqual(path.read_bytes(), b"body\n")

    def test_failure_processes_other_files_and_allows_retry(self):
        valid = self.source("valid")
        invalid = self.source("invalid", dialect=self.required)
        self.stop(expected=1)
        self.assertEqual(valid.read_bytes(), (self.header() + "body\n").encode())
        self.assertEqual(invalid.read_bytes(), b"body\n")
        leading = self.preamble(self.required)
        invalid.write_bytes((leading + "body\n").encode())
        self.stop()
        self.assertEqual(invalid.read_bytes(), (leading + self.header(self.required) + "body\n").encode())

    def test_outside_git_worktree_is_a_noop(self):
        path = self.base / ("outside" + self.default[0])
        path.write_bytes(b"body\n")
        self.stop(cwd=self.base)
        self.assertEqual(path.read_bytes(), b"body\n")

    def test_malformed_hook_input_is_reported(self):
        for payload in ([], {}, {"hook_event_name": "Unexpected"}, {"hook_event_name": "Stop"}):
            with self.subTest(payload=payload):
                result = self.run_script("--hook", payload=payload, expected=1)
                self.assertIn(b"source-file-headers:", result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)

    def test_new_dialects_and_variable_rules_need_only_a_policy_change(self):
        # Random tokens ensure neither format nor metadata is known to the runtime.
        for delimited in (True, False):
            with self.subTest(delimited=delimited):
                suffix = "." + uuid.uuid4().hex
                start, end, leading, marker = (uuid.uuid4().hex for _ in range(4))
                policy = {
                    "header": {
                        "encoding": "utf-8",
                        "contentLines": [marker + " {{stamp}}", marker + " {{owner}}"],
                        "recognition": {
                            "pattern": re.escape(marker),
                            "commentStyles": {"new": {"start": start, **({"end": end} if delimited else {})}},
                        },
                        "placement": "plain",
                        "placements": {
                            "plain": {},
                            "leading": {
                                "leadingLinePrefix": leading, "required": True,
                                "missingMessage": "configured leading line is required",
                            },
                        },
                        "templates": [{
                            "extensions": [suffix], "commentStyles": ["new"],
                            "openingLines": [start] if delimited else [],
                            "closingLines": [end] if delimited else [],
                            "linePrefix": "" if delimited else start + " ",
                            "placementOverrides": {suffix: "leading"},
                        }],
                    },
                    "variables": {
                        "stamp": {"source": "system-date", "format": "%Y/%m/%d"},
                        "owner": {
                            "source": "git-config", "key": "header-test.owner", "required": True,
                            "forbiddenPattern": re.escape(end),
                        },
                    },
                    "excludedPathGlobs": [],
                }
                plugin = self.base / ("configured " + uuid.uuid4().hex)
                shutil.copytree(PLUGIN_ROOT, plugin, ignore=shutil.ignore_patterns("__pycache__"))
                (plugin / "header-policy.json").write_text(json.dumps(policy), encoding="utf-8")
                script = plugin / "scripts" / SCRIPT_PATH.name
                self.git("config", "header-test.owner", "Configured Owner")
                style = policy["header"]["recognition"]["commentStyles"]["new"]
                path = self.write("configured" + suffix, leading + "\n" + self.comment(style, [marker + " old"]) + "body\n")
                self.run_script(path, script=script)
                lines = [marker + " " + date.today().strftime("%Y/%m/%d"), marker + " Configured Owner"]
                expected = (leading + "\n" + self.comment(style, lines) + "body\n").encode()
                self.assertEqual(path.read_bytes(), expected)
                self.run_script(path, script=script)
                self.assertEqual(path.read_bytes(), expected)
                unsupported = self.source()
                self.run_script(unsupported, script=script)
                self.assertEqual(unsupported.read_bytes(), b"body\n")
                self.git("config", "header-test.owner", end)
                self.run_script(path, script=script)
                self.assertEqual(path.read_bytes(), expected)

    def test_registered_command_works_from_installed_path_with_spaces(self):
        configuration = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
        self.assertEqual(set(configuration["hooks"]), {"Stop"})
        plugin = self.base / "installed plugin"
        shutil.copytree(PLUGIN_ROOT, plugin, ignore=shutil.ignore_patterns("__pycache__"))
        environment = dict(self.environment, CLAUDE_PLUGIN_ROOT=str(plugin))
        bash = shutil.which("bash")
        if os.name == "nt":
            git_bash = Path("C:/Program Files/Git/bin/bash.exe")
            bash = str(git_bash) if git_bash.is_file() else None
        if not bash:
            self.skipTest("Bash is unavailable to test the hook command")
        path = self.source("installed")
        handler = configuration["hooks"]["Stop"][0]["hooks"][0]
        self.assertEqual(handler["type"], "command")
        result = subprocess.run(
            [bash, "-c", handler["command"]],
            input=json.dumps({
                "hook_event_name": "Stop", "session_id": "installed-session",
                "stop_hook_active": False, "cwd": str(self.repo),
            }).encode(),
            env=environment, cwd=self.repo, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(path.read_bytes(), (self.header() + "body\n").encode())
        self.assertFalse((plugin / "skills").exists())


if __name__ == "__main__":
    unittest.main()
