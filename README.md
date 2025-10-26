# HTool

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

## Usage

Run the installed command:

```bash
tmuxer -s mysession -n 3 --layout ev
```

This will start (or attach) to a tmux session named `mysession` with 3 panes using the `even-vertical` layout (`ev`).
