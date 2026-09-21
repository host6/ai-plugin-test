# ai-plugins

`untill-dev` automates unTill development workflows.

## Header comment corrector

After each agent response, a `Stop` hook inserts or repairs headers in untracked and newly added source files. It leaves committed files unchanged and does not stage repairs.

It requires Git, Python 3.8+, and a configured Git `user.name`.

See the [full documentation](untill-dev/README.md#header-comment-corrector) for supported formats, exclusions, and manual repair. Run its tests with `python -m unittest discover -s untill-dev/tests -v`.

## Installation

Failed to implement per-repo installation (`failed to load plugin: plugin is not installed` error reported)

1. Install the plugin globally:

```shell
codex plugin marketplace add https://github.com/untillpro/ai-plugins.git
codex plugin add untill-dev@untill-ai-plugins
```

2. Disable the plugin globally:

`~/.codex/config.toml`:

```toml
[plugins."untill-dev@untill-ai-plugins"]
enabled = false
```

3. Trust the plugin hook:

codex settings -> Hooks -> From Plugins -> untill-dev -> enable Stop hook

![alt text](image.png)

4. Enable the plugin in each repo where it is needed:

`<repoRoot>/.codex/config.toml`:

```toml
[plugins."untill-dev@untill-ai-plugins"]
enabled = true
```

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

## Deinstallation

```shell
codex plugin remove untill-dev@untill-ai-plugins
codex plugin marketplace remove untill-ai-plugins
```
