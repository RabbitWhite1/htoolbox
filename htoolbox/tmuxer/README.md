# HToolBox - tmux

## Usage

```sh
usage: tmuxer [-h] [-n NUM_PANES] [-s SESSION] [-w WINDOW] [-p PANE] [--layout LAYOUT] [--kill] [-c CONFIG] [-P NAME=VALUE] [--dry] [-d]

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
  -c, --config CONFIG   Path to tmuxer config file
  -P, --placeholder NAME=VALUE
                        Define placeholder substitutions for config files; repeatable
  --dry                 Load and print config, then exit without starting tmux
  -d, --detach          Create and configure tmux session in detached mode without attaching
```

### Using a Config File

Both JSON/JSON5 and YAML config files are supported.

If `--config` is not provided, `tmuxer` auto-detects the first existing file in the current directory from:

- `.tmuxer.json`
- `.tmuxer.json5`
- `.tmuxer.yaml`
- `.tmuxer.yml`

If `--config` is provided but the file does not exist, `tmuxer` asks whether to create a placeholder YAML file at that path, then exits so you can edit it.

Check [.tmuxer.yaml](.tmuxer.yaml) for an example. Try it out by just running:

```sh
cd htoolbox/tmux
tmuxer  # The `.tmuxer.yaml` in the current directory will be auto-loaded
```

## YAML Config Reference

`tmuxer` reads a top-level session object. Minimal shape:

```yaml
session: my-session
focus_window: 0
kill: false
windows:
  - window: editor
    num_panes: 2
    layout: even-vertical
    focus_pane: 0
    kill: false
    commands:
      - pane_indices: "0"
        commands:
          - cd ~/work
          - nvim
```

### Top-Level Fields

- `session` (string, required)
  Name of the tmux session to create or reuse.

- `focus_window` (integer or py-string, optional, default `0`)
  Index in the `windows` list to focus after setup finishes.

- `kill` (boolean, optional, default `false`)
  If `true`, kill an existing session with the same name before recreating.
  If `false`, the existing session is kept, but per-window `kill` rules can still apply.

- `windows` (list, required)
  Ordered list of window definitions. Must contain at least one entry.

### Window Fields

- `window` (string, optional)
  Window name. If omitted, tmux chooses a default name.

- `num_panes` (integer or py-string, optional, default `1`)
  Number of panes to create in this window.

- `layout` (string, optional, default `even-vertical`)
  Layout applied when panes are split.
  Valid values:
  - Full names: `even-horizontal`, `even-vertical`, `main-horizontal`, `main-vertical`, `tiled`
  - Aliases: `eh`, `ev`, `mh`, `mv`, `t`

- `focus_pane` (integer or py-string, optional, default `0`)
  Pane index to focus inside this window after configuration.

- `kill` (boolean, optional, default `false`)
  When session-level `kill: false`, this can still kill an existing window with the same name before creating/reusing.
  Note: this only works when `window` is set, because matching is by window name.

- `commands` (list, optional)
  Command batches to run in one or multiple panes. See the next section.

- `synchronized_panes` (boolean, optional, default `false`)
  If `true`, `tmuxer` enables tmux `synchronize-panes` for this window **after** all command
  batches in the window have finished. It does not affect how the configured commands are
  dispatched — only subsequent keystrokes you type yourself are broadcast to every pane.

### Command Batch Format

Each item in `commands` targets one or more panes and runs command lines in sequence.

```yaml
commands:
  - pane_indices: "0-2"
    commands:
      - source ~/.zshrc
      - echo ready

  - pane_indices: "1"
    ssh_server: user@my-host
    commands:
      - cd /srv/app
      - docker compose logs -f
```

Fields:

- `pane_indices` (string, integer, or py-string, required)
  Pane selector.
  Common forms:
  - single pane: `"0"`
  - range: `"0-2"`
  - comma-separated: `"0,2"`
  - py-string returning a list: `py`list(range(4))``

- `commands` (list of strings, required)
  Commands sent via tmux `send-keys` (each command is followed by Enter).

- `ssh_server` (string, optional)
  If set, each command is wrapped and executed remotely:

  ```text
  ssh -n <ssh_server> 'bash -ic <command>'
  ```

- `use_sentinel` (boolean, optional, default `true`)
  When `true`, `tmuxer` waits for each command to finish before sending the next batch.
  Set to `false` for fire-and-forget commands that block indefinitely (e.g. `ssh <server>`, `htop`).
  The very last command a pane will run never sends a sentinel regardless of this flag.

  The sentinel ping runs in the pane as
  `: "${__TMUXER_N__:=$?}"; echo "__TMUXER_N__ returncode=$__TMUXER_N__"`, which captures the
  preceding command's exit status into a uniquely-named shell variable on the first ping and
  re-echoes it on subsequent pings. Pings retry on a 1s → 16s (capped) exponential backoff.
  Because tmux `send-keys` has no return channel, echoing `$?` back into the pane is the only
  way to surface the exit code; it appears on-screen alongside the sentinel line.

## Extended Runtime Behavior Notes

1. Load + prepare config.
  1. Load file: auto or `--config`.
  2. Apply placeholders: `@@name@@` from `--placeholder name=value` (see [Placeholders](#placeholders)).
  3. Missing placeholder: stop, error, no tmux changes.
  4. Eval py-strings (see [Py-Strings](#py-strings)).

2. Build session, windows, panes.
  1. Session step: check `session`; if `kill: true`, kill old session first.
  2. Window spawn: process `windows` top to bottom; apply window `kill` if set.
  3. Pane spawn: use `num_panes`; apply `layout`; send `export IID=<pane_indices>` to each pane.

3. Run commands.
  1. Command run: batches in order; target panes from `pane_indices`; send via tmux `send-keys`.
  2. SSH mode (when `ssh_server` set): wrap each command with `ssh -n <ssh_server> 'bash -ic "<command>"'` (see [Work with SSH](#work-with-ssh)).
  3. Sync mode: `use_sentinel: true` wait; `use_sentinel: false` no wait, continue.

4. Set final focus.
  1. Per-window `focus_pane` during setup.
  2. Top-level `focus_window` at end.

## Special Usage

### Py-Strings

Most config fields accept a **py-string**: an expression wrapped in `` py`...` ``.
Evaluation runs after placeholder substitution.

```yaml
num_panes: py`2 + 2`
focus_window: py`int(os.environ.get("WIN", 0))`
kill: py`True`
layout: py`"ev"`

commands:
  - pane_indices: py`list(range(4))`
    ssh_server: py`"user@host"`
    commands:
      - py`"echo hello"`
```

Common fields with py-string support:
- session/window fields: `session`, `window`, `num_panes`, `layout`, `focus_pane`, `focus_window`, `kill`
- command block fields: `pane_indices`, `commands`, `commands[]`, `ssh_server`, `use_sentinel`

Notes:
- py-string result type must match field type (e.g. `kill` -> bool, `num_panes` -> int).
- `pane_indices` py-strings may return `int`, `str`, or `list[int]`.


### Placeholders

Configs may contain placeholder tokens such as `@@workdir@@`. Provide values with one or more
`--placeholder workdir=/tmp/foo` flags. Each token is replaced via string substitution before the
config is parsed, and placeholders can be used in both YAML and JSON configs.
If any placeholder token remains unresolved, `tmuxer` prints an error and exits.

You can try:

```sh
cd htoolbox/tmux
tmuxer -c .tmuxer.placeholder.yaml -P somedir=/usr
```

### Work with SSH

When specifying `ssh_server` in the item of the list of commands for a window, the command will be automatically wrapped like
```
ssh -n <ssh_server> 'bash -ic "<command>"'
```

You don't need to worry about quotes, because `shlex.quote` handles the nested quotes.


## Full Example

```yaml
session: devbox
focus_window: 1
kill: true
windows:
  - window: workspace
    num_panes: py`2 + 1`   # evaluated to 3
    layout: ev
    focus_pane: 0
    kill: true
    commands:
      - pane_indices: "0-1"
        commands:
          - echo "workspace panes ready"
      - pane_indices: "0"
        commands:
          - cd @@workdir@@
          - bash
      - pane_indices: "1"
        commands:
          - cd @@workdir@@
          - ls -la
      # use_sentinel: false — send the command and move on without waiting
      - pane_indices: "2"
        use_sentinel: false
        commands:
          - top
  - window: monitoring
    num_panes: 2
    layout: tiled
    focus_pane: 0
    kill: true
    synchronized_panes: true
    commands:
      - pane_indices: "0"
        commands:
          - tail -f /var/log/system.log
      - pane_indices: "1"
        commands:
          - ping -c 5 8.8.8.8
```

Run with placeholders:

```sh
tmuxer -c .tmuxer.yaml -P workdir=$HOME
```

## Known issues
