# HToolbox

This repository provides some useful tools that fit my developing habits.

The package is available on PyPI, so you can directly install this package via `pip`:

```bash
pip install htoolbox
```

Alternatively, you can install it with a cloned repository:

```bash
git clone git@github.com:RabbitWhite1/htoolbox.git $HOME/.htoolbox
cd $HOME/.htoolbox && pip install .
```

`uv` is also recommended to use this package because you can easily install it to your user environment via:

```bash
uv tool install .
```

## codeit

This tool is a quick script for starting vscode server on a remote server, and utilizing SSH port forwarding to access it locally.

```bash
codeit <remote-host>
```

## docker

A Dockerfile providing my preferred development environment.

## downloader

A simple batched video downloader script with `rich` progress bars.

## tmuxer

A helper script `tmuxer` to create multiple tmux panes easily.

Run the installed command:

```bash
tmuxer -s mysession -n 3 --layout ev
```

This will start (or attach) to a tmux session named `mysession` with 3 panes using the `even-vertical` layout (`ev`).

## singularity

A helper script `smagic` that wraps singularity commands for easier usage.

## Release Workflow

Use the helper script `./tag_version <new_version>` to bump the version stored in `pyproject.toml`. The script will print the git commands needed to create and push the release tag so you can copy and run them manually.
