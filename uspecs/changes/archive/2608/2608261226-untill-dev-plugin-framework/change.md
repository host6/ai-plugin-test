---
change_id: 2608071145-untill-dev-plugin-framework
type: feat
issue_url: https://untill.atlassian.net/browse/AIR-4088
---

# Change request: untill-dev development plugin with deterministic header correction

Refs:

- [AIR-4088: implement an AI plugin that will force to create the correct header comment for new files](./issue-AIR-4088.md)

## Why

The shared `untill-dev` Claude Code plugin provides development automation. Source file header correction is one of its features: new files can contain incorrect copyright and author comments, so this feature must enforce the required header through deterministic code, without depending on a model to invoke a skill or apply a helper's output.

## What

- Distribute the single `untill-dev` development plugin through the existing Claude Code marketplace, with header comment correction documented as one feature.
- Remove the source-file header skill and replace it with command hooks that invoke Python.
- Detect new source paths through Git when the agent finishes responding and repair them in one batch.
- Insert missing headers and replace recognizable incorrect or duplicate copyright/author headers directly in the file.
- Use C-style block comments for C-like formats, `--` comments for SQL and Vertica SQL, and `#` comments after the existing shell shebang. Preserve an optional leading JavaScript or TypeScript shebang.
- Derive the copyright period from the current year through `present` and the author from the effective Git `user.name`.
- Retain the supported extension groups and generated/dependency/build exclusions.
- Keep the existing installation and automatic-update workflow.

## How

Decisions:

- Retain the repository-relative marketplace entry and authoritative plugin manifest. The manifest describes the general development plugin and has no explicit version field.
- Put the shared policy at the plugin root, runtime Python modules under `scripts/`, tests under `tests/`, and hooks in Claude Code's automatically discovered `hooks/hooks.json`.
- Keep extension mappings, rendering prefixes and delimiters, recognized comment syntax and metadata patterns, leading-line placement rules, and variable validation in `header-policy.json`. Python interprets these declarations without language-specific branches or concrete source-format constants.
- Assume the bundled policy is correct. Load its declarations directly and retain runtime checks for Git values and source content.
- Register one synchronous `Stop` command handler with a 60-second timeout, invoking `scripts/fix_file_headers.py --hook` through `python` from `CLAUDE_PLUGIN_ROOT`. Do not use per-tool hooks, session cleanup, snapshots, persistent state, or locks.
- At `Stop`, locate the Git root from the hook's current directory and select untracked files that are not ignored, staged additions, and intent-to-add paths. Treat rename destinations as additions.
- Require only the hook event name and current directory; no session or tool-call identifier is needed. Outside a Git working tree, return successfully without changing files.
- Process all currently uncommitted new paths, including those present before the response. Git cannot identify their creation time or creator.
- Keep committed paths unchanged automatically. Detect staged additions and leave the Git index unchanged.
- Replace recognizable copyright/author comments only in the leading comment region. Preserve unrelated comments, source content, BOMs, shebangs, line endings, and file permissions. Leave correct files untouched.
- Use temporary files and atomic replacement without re-reading the original file before replacement.
- Omit special link checks and encoding/binary-content validation. Read and write source content using the policy's configured encoding.
- Report missing identity, missing required shebangs, and unsafe header content. Do not guess missing context. Process other new files even when one repair fails. Successful runs are silent; runtime errors use stderr and exit code 1 so `Stop` does not force the agent to continue. Invalid command-line usage returns exit code 2.
- Provide a direct Python command for explicit repair of named files, including existing files.

Assumptions:

- Target projects are Git working trees with Git and Python 3.8 or newer available on `PATH`; `python` selects Python 3.
- Claude Code command hooks are enabled and allowed to run.
- Only one agent session works in the codebase at a time.
- No other process modifies target files during the `Stop` phase.
- Consuming environments can authenticate to the marketplace repository for updates.

Out of scope:

- Retrofitting committed paths automatically.
- Unsupported formats and policy-excluded files, and nested repositories or submodules belonging to a different worktree.
- Continuous filesystem monitoring, writes outside the current Git root, and background writes occurring after `Stop`.
- Affecting commands that consume or commit a newly created file before the response ends; files committed before `Stop` are skipped.
- Running on user interrupts or API failures, which do not emit `Stop`.
- Supporting AI clients or plugin formats other than Claude Code.

References:

- [Claude Code plugin packaging](https://code.claude.com/docs/en/plugins-reference)
- [Claude Code hooks and event payloads](https://code.claude.com/docs/en/hooks)
- [Git configuration resolution](https://git-scm.com/docs/git-config)

## Provisioning and configuration

### Plugin registration

- [x] create: [.claude-plugin/marketplace.json](../../../../../.claude-plugin/marketplace.json): register the single repository-relative `untill-dev` plugin
- [x] create: [.claude-plugin/plugin.json](../../../../../untill-dev/.claude-plugin/plugin.json): define the general development plugin's identity, description, ownership, and repository without an explicit version field
- [x] create: [hooks/hooks.json](../../../../../untill-dev/hooks/hooks.json): register the synchronous Python command for batch header repair at `Stop` with a 60-second timeout

### Header policy

- [x] create: [untill-dev/header-policy.json](../../../../../untill-dev/header-policy.json): define shared content, all 25 supported extension mappings, output and recognition syntax, metadata patterns, placement rules, dynamic variable sources and validation, and exclusions

### Repository tooling

- [x] create: [.gitignore](../../../../../.gitignore): ignore Python bytecode, caches, and native extension artifacts

## Construction

### Tests

- [x] create: [tests/test_fix_file_headers.py](../../../../../untill-dev/tests/test_fix_file_headers.py)
  - exercise real temporary Git repositories and all supported source extensions
  - verify missing, incorrect, duplicate, and incorrectly styled header repair
  - derive source-format examples from the policy and verify new extensions, delimiters, placement rules, and variable definitions through temporary policy changes alone
  - verify idempotence, literal Git-author substitution, BOMs, line endings, shebangs, permissions, and unrelated source preservation
  - verify exclusions, nested repositories, and errors without unsafe writes
  - verify `Stop` handling, untracked/staged/intent-to-add paths, committed and ignored files, renamed and deleted additions, repeated runs, non-blocking errors, and the installed hook command
  - verify malformed hook input, no-op behavior outside Git, and retry after a partial batch failure
  - run with `python -m unittest discover -s untill-dev/tests -v`

### Runtime

- [x] create: [scripts/build_header_from_policy.py](../../../../../untill-dev/scripts/build_header_from_policy.py)
  - load the trusted policy and prepare template and placement lookups
  - compile exclusion, metadata, and variable-value patterns directly
  - resolve declared date and Git variables, interpret placement rules, and render the required prefix without source-format constants
- [x] create: [scripts/fix_file_headers.py](../../../../../untill-dev/scripts/fix_file_headers.py)
  - handle `Stop` JSON input using the event name and current directory, and accept direct file arguments for manual repair
  - identify untracked, staged, and intent-to-add Git paths through `new_files` without persistent state or locks
  - insert or repair headers directly with atomic replacement and preserve permissions
  - process all eligible new paths despite individual failures and report runtime errors through stderr with exit code 1
- [x] delete: former `untill-dev/skills/source-file-headers` package
  - remove `SKILL.md` and the read-only `get_header.py` workflow
  - relocate the retained policy and replace the former tests and documentation

### Documentation

- [x] update: [README.md](../../../../../README.md)
  - present `untill-dev` as a development automation plugin and header comment correction as one feature
  - describe automatic Python header repair and its feature-specific runtime prerequisites
  - retain marketplace installation and automatic-update guidance
  - link plugin behavior and provide the current test command
- [x] create: [untill-dev/README.md](../../../../../untill-dev/README.md)
  - organize header comment correction under Features, with plugin development documented separately
  - document `Stop`, Git-based new-file detection, declarative policy fields, repair rules, and scope
  - explain the single-session assumption, absence of locks and snapshots, inclusion of earlier uncommitted files, unchanged index content, and non-blocking error handling
  - provide manual repair, local plugin loading, and test commands
