# HToolbox

HToolbox is a collection of small command-line utilities and helpers for development workflows.

## Installation

Install from PyPI:

```bash
pip install htoolbox
```

Or install from source:

```bash
git clone git@github.com:RabbitWhite1/htoolbox.git $HOME/.htoolbox
cd $HOME/.htoolbox && pip install .
```

You can also install with uv:

```bash
uv tool install .
```

## Components

### vscode (codeit)

Starts VS Code server on a remote host and helps set up SSH forwarding for local access.

- Component README: [htoolbox/vscode/README.md](htoolbox/vscode/README.md)

### docker

Provides a Docker-based development environment image and usage notes.

- Component README: [htoolbox/docker/README.md](htoolbox/docker/README.md)

### downloader

Batched video downloader with rich progress output.

- Component README: [htoolbox/downloader/README.md](htoolbox/downloader/README.md)

### tmuxer

Creates and configures tmux sessions/windows/panes from CLI flags or config files.

- Component README: [htoolbox/tmuxer/README.md](htoolbox/tmuxer/README.md)

### singularity (smagic)

Wrapper script for common singularity command workflows.

- Component README: [htoolbox/singularity/README.md](htoolbox/singularity/README.md)

### hscan

Single-file helper script in [htoolbox/hscan](htoolbox/hscan) for quick scanning tasks.

### logging.py

Shared logging utilities in [htoolbox/logging.py](htoolbox/logging.py).

### tag_version

Release helper in [tag_version](tag_version) that bumps the version in pyproject.toml and prints git tag/push commands.
