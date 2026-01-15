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
```

### Using a Config File

Check [.tmuxer.json5](.tmuxer.json5) for an example.
