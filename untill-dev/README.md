# untill-dev

`untill-dev` automates unTill development workflows in Claude Code.

## Header comment corrector

A `Stop` hook runs `scripts/fix_file_headers.py` after each agent response to insert or repair headers in new source files.
It operates only when the repository's GitHub `origin` belongs to the `untillpro` or `voedger`
organization; repositories without such an origin are left unchanged.

### Requirements

- Git and Python 3.8+ on `PATH` (`python` must select Python 3)
- A Git working tree with `user.name` configured
- A trusted plugin hook and one active agent session per codebase
- No other process modifies files during the `Stop` phase

No third-party Python packages are required.

### Operation

Git identifies untracked, staged-added, and intent-to-add files; rename destinations also count as additions. Existing committed files are skipped. All uncommitted new files are eligible, even if they predate the current response.

Repairs affect only working-tree content and are not staged automatically. Correct files are left untouched, so repeated runs are safe. The hook uses no snapshots, persistent state, or locks; avoid concurrent file changes during `Stop`.

The hook covers the Git working tree containing its current directory. Nested repositories and submodules need their own hook. Files committed before `Stop` are skipped, and writes made after the hook wait until a later run. Interrupts and API failures do not trigger `Stop`.

### Header policy

[`header-policy.json`](header-policy.json) defines templates, extension mappings, recognized comment styles, placement rules, variables, and excluded paths. Copyright begins with the current year and ends with `present`; the author is Git's effective `user.name`.

The bundled policy supports:

- `/* ... */` for C-like files.
- `--` for `.sql` and `.vsql`.
- `#` after the required shebang in `.sh` files.
- Optional leading shebangs in JavaScript and TypeScript.

The script leaves an existing canonical header untouched only when its rendered values match the current policy. Older copyright years and authors that differ from Git's effective `user.name` are repaired. It also replaces duplicate headers and partial or malformed headers carrying the unTill copyright marker. Standalone copyright, author, and SPDX comments are not treated as replaceable headers, so third-party legal attribution is retained. Other comments and file content remain intact, with exactly one blank line between the generated header and the body; UTF-8 BOMs, line endings, shebangs, and permissions are preserved. Unsupported and excluded files are skipped.

A missing Git identity, missing required shell shebang, or unterminated header reports an error without rewriting that file. Other files still run; errors go to stderr and produce exit code 1.

### Manual repair

From the plugin directory:

```shell
python scripts/fix_file_headers.py path/to/file.go path/to/script.sh
```

Named files in an allowed repository are repaired even if already committed. Success is silent;
unsupported or excluded files and repositories outside the allowed organizations remain unchanged.

## Development

Run the test suite from the repository root:

```shell
python -m unittest discover -s untill-dev/tests -v
```

Tests use temporary Git repositories and cover supported formats, repairs, preservation, errors, new-file detection, repeated runs, and policy customization.

See the [Codex hooks reference](https://learn.chatgpt.com/docs/hooks) or [Claude Code hooks reference](https://code.claude.com/docs/en/hooks) for runtime details.
