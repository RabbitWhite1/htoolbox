# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`htoolbox` is a Python 3.12+ package of loosely-related developer CLI utilities. Each subpackage under `htoolbox/` is an independent tool; there is no shared runtime beyond `htoolbox/logging.py`.

## Entry points

Two are regular Python console scripts (declared in `pyproject.toml` `[project.scripts]`):

- `tmuxer` → `htoolbox.tmuxer.tmuxer:main` — builds tmux sessions/windows/panes from CLI flags or YAML/JSON5 config (`test.yaml` is a sample config).
- `vd` → `htoolbox.downloader.vd:main` — batched video downloader.

Three are shell scripts shipped via `[tool.setuptools] script-files` (installed onto PATH as-is, not importable):

- `htoolbox/vscode/codeit` — starts VS Code server remotely + SSH forwarding.
- `htoolbox/hscan` — single-file scan helper.
- `htoolbox/singularity/smagic` — singularity workflow wrapper.

When adding a new tool, decide early: Python module (add to `[project.scripts]`) or shell script (add to `script-files`). The two paths don't mix.

## Common commands

```bash
# Install for local dev (editable)
uv pip install -e .
# or: pip install -e .

# Lint (ruff is the only dev dep; config in pyproject.toml [tool.ruff.lint])
uvx ruff check .
uvx ruff format .

# Release: bumps version in pyproject.toml and prints the git tag/push commands to run manually
./tag_version 0.9.18
```

There is no test suite.

## Release flow

`tag_version <X.Y.Z>` only edits `pyproject.toml`; it then prints (does not run) the `git commit -m "vX.Y.Z"`, `git tag -a vX.Y.Z`, and push commands. Recent commit history matches this pattern (`v0.9.17`, `v0.9.16`, …) — follow it for new releases.

## Notes

- `ruff` ignores `F401`/`F403`/`F841` project-wide — unused imports/star-imports/unused vars are intentional and should not be "cleaned up" reflexively.
- Each subpackage has its own `README.md`; consult it before changing behavior of a specific tool.
