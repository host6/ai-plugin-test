# ai-plugins

`untill-dev` automates unTill development workflows.

## Header comment corrector

After each agent response, a `Stop` hook inserts or repairs headers in untracked and newly added source files. It leaves committed files unchanged and does not stage repairs.

It requires Git, Python 3.8+, and a configured Git `user.name`.

See the [full documentation](untill-dev/README.md#header-comment-corrector) for supported formats, exclusions, and manual repair. Run its tests with `python -m unittest discover -s untill-dev/tests -v`.

## Codex setup (recommended)

Enable the plugin only where needed by creating `.codex/agents/untill-dev.toml` in each repository:

```toml
name = "untill-dev"
description = "Implementation helper with the unTill development safeguards enabled."

[plugins."untillpro@untill-dev"]
enabled = true
```

To route relevant work through the agent, add this to `AGENTS.md`:

```markdown
For every implementation task that may create source files, delegate the file changes to the project-scoped `untill-dev` agent. Do not create source files through another agent.
```

Start a new session, use the agent, and approve the hook when prompted. See the Codex docs for [custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents), [plugin configuration](https://learn.chatgpt.com/docs/config-file/config-reference), and [hook trust](https://learn.chatgpt.com/docs/hooks).

## Global installation (optional)

For Codex CLI:

```shell
codex plugin marketplace add untillpro/ai-plugins
codex plugin add untill-dev@untill-dev-plugins-claude
```

In Claude Code, enable marketplace auto-updates under `/plugin` and run `/reload-plugins` after an update.
