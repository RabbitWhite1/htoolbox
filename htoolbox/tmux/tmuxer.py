import argparse
import json5
import os
import os.path as osp
import rich
import shlex
from pathlib import Path
from typing import Dict, List, Optional


def start_tmux_session(
    session_name,
    window_name=None,
    pane_index=None,
    new_panes=1,
    layout="even-vertical",
    commands=None,
):
    """Start and attach to a tmux session.

    This function uses the `tmux` command-line tool. It is designed to be
    called from the CLI entry point `main()` below, but can also be imported
    and used programmatically.
    """
    # Start a new tmux session detached
    os.system(f"tmux new-session -d -s {session_name}")

    # Create a new window if specified
    if window_name:
        os.system(f"tmux new-window -t {session_name} -n {window_name}")

    # Create new panes if specified
    for i in range(1, new_panes):
        os.system(f"tmux split-window -t {session_name}")
        os.system(f"tmux select-layout -t {session_name} {layout}")

    commands = commands or {}

    for pane_index in range(new_panes):
        os.system(f"tmux send-keys -t {session_name}.{pane_index} 'export IID={pane_index}' C-m")

    _send_commands_to_panes(session_name=session_name, commands=commands)

    # Select the specified pane if provided
    if pane_index is not None:
        os.system(f"tmux select-pane -t {session_name}:{pane_index}")

    # Attach to the tmux session
    os.system(f"tmux attach-session -t {session_name}")


def _normalize_layout(layout_arg: str) -> str:
    v = layout_arg.lower().strip()
    if v == "eh":
        return "even-horizontal"
    if v == "ev":
        return "even-vertical"
    if v == "mh":
        return "main-horizontal"
    if v == "mv":
        return "main-vertical"
    if v == "t":
        return "tiled"
    return layout_arg


def _send_commands_to_panes(session_name: str, commands: Optional[Dict[int, List[str]]]):
    if not commands:
        return

    for pane_index, pane_commands in commands.items():
        for cmd in pane_commands:
            os.system(f"tmux send-keys -t {session_name}.{pane_index} {shlex.quote(cmd)} C-m")


def _load_config(path_argument: Optional[str]) -> dict:
    if path_argument:
        cfg_path = Path(path_argument).expanduser()
        if not cfg_path.is_file():
            raise FileNotFoundError(f"Config file not found: {cfg_path}")
    else:
        default_path = Path.cwd() / ".tmuxer.json5"
        cfg_path = default_path if default_path.is_file() else None

    if not cfg_path:
        return {}

    with cfg_path.open("r", encoding="utf-8") as handle:
        data = json5.load(handle)

    if not isinstance(data, dict):
        raise ValueError("Top-level JSON structure in config must be an object")

    rich.print("Using tmuxer config from ", cfg_path)
    rich.print(data)

    return data


def _coalesce(value, fallback):
    return value if value is not None else fallback


def _normalize_commands(commands: Optional[dict]) -> Dict[int, List[str]]:
    if not commands:
        return {}
    if not isinstance(commands, dict):
        raise ValueError("commands section must be a JSON object keyed by pane index")
    normalized: Dict[int, List[str]] = {}
    for pane_key, pane_commands in commands.items():
        try:
            pane_index = int(pane_key)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError(f"Pane key '{pane_key}' must be an integer") from exc

        if not isinstance(pane_commands, list):
            raise ValueError(f"Commands for pane {pane_index} must be a list of strings")

        normalized[pane_index] = [str(cmd) for cmd in pane_commands]
    return normalized


def main():
    """Console entry point for the `tmuxer` command.

    Accepts an optional argv list (for testing). Returns 0 on success, may
    raise exceptions for misuse.
    """
    parser = argparse.ArgumentParser(description="Tmux session starter")
    parser.add_argument("-n", "--num_panes", type=int, help="Number of new panes to create")
    parser.add_argument("-s", "--session", type=str, help="Name of the tmux session")
    parser.add_argument("-w", "--window", type=str, help="Name of the tmux window")
    parser.add_argument("-p", "--pane", type=int, help="Index of the tmux pane")
    parser.add_argument("--layout", type=str, help="Layout for the tmux panes")
    parser.add_argument(
        "--kill", action="store_true", help="Kill existing tmux session with the same name before starting a new one"
    )
    parser.add_argument("-c", "--config", type=str, help="Path to tmuxer JSON config file")

    args = parser.parse_args()

    config = _load_config(args.config)

    num_panes = _coalesce(args.num_panes, config.get("num_panes"))
    session = _coalesce(args.session, config.get("session"))
    window = _coalesce(args.window, config.get("window"))
    pane = _coalesce(args.pane, config.get("pane"))
    layout_arg = _coalesce(args.layout, config.get("layout", "even-vertical"))
    kill_existing = args.kill or bool(config.get("kill"))
    commands = _normalize_commands(config.get("commands"))

    if num_panes is None:
        raise ValueError("num_panes must be provided via CLI or config")
    if session is None:
        raise ValueError("session must be provided via CLI or config")

    num_panes = int(num_panes)
    if num_panes < 1:
        raise ValueError("Number of new panes must be at least 1")

    pane_index = int(pane) if pane is not None else None
    layout = _normalize_layout(layout_arg)

    if kill_existing and session:
        # Prefer to silence output from tmux kill-session so CLI stays quiet
        os.system(f"tmux kill-session -t {session} >/dev/null 2>&1")

    start_tmux_session(
        session_name=session,
        window_name=window,
        pane_index=pane_index,
        new_panes=num_panes,
        layout=layout,
        commands=commands,
    )


if __name__ == "__main__":
    main()
