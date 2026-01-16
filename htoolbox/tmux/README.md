# HToolBox - tmux

## Usage

```sh
usage: tmuxer [-h] [-n NUM_PANES] [-s SESSION] [-w WINDOW] [-p PANE] [--layout LAYOUT] [--kill] [-c CONFIG]

Tmux session starter

options:
  -h, --help            show this help message and exit
  -n, --num_panes NUM_PANES
                        Number of new panes to create
  -s, --session SESSION
                        Name of the tmux session
  -w, --window WINDOW   Name of the tmux window
  -p, --pane PANE       Index of the tmux pane
  --layout LAYOUT       Layout for the tmux panes
  --kill                Kill existing tmux session with the same name before starting a new one
  -c, --config CONFIG   Path to tmuxer JSON config file
  -P, --placeholder NAME=VALUE
                        Define placeholder substitutions for config files; can be repeated
```

### Using a Config File

Both JSON and YAML config files are supported.

Check [.tmuxer.yaml](.tmuxer.yaml) for an example. Try it out by just running:

```sh
cd htoolbox/tmux
tmuxer  # The `.tmuxer.yaml` in the current directory will be auto-loaded
```

### Placeholders

Configs may contain placeholder tokens such as `<project_root>`. Provide values with one or more
`--placeholder project_root=/tmp/foo` flags. Each token is replaced via string substitution before the
config is parsed, and placeholders can be used in both YAML and JSON configs.

You can try:

```sh
cd htoolbox/tmux
tmuxer -c .tmuxer.placeholder.yaml -P somedir=/usr
```
