# HToolbox

This repository provides some useful tools that fit my developing habits.

## Install

To install locally (editable mode) and get the `tmuxer` command:

```bash
pip install -e .
```

Or to install from source (non-editable):

```bash
pip install .
```

## tmuxer

Run the installed command:

```bash
tmuxer -s mysession -n 3 --layout ev
```

This will start (or attach) to a tmux session named `mysession` with 3 panes using the `even-vertical` layout (`ev`).

## codeit

This tool is a quick script for starting vscode server on a remote server, and utilizing SSH port forwarding to access it locally.

```bash
codeit <remote-host>
```


## Developer Helps


git tag -a v0.1.2 -m "Release v0.1.2"
git push origin v0.1.2