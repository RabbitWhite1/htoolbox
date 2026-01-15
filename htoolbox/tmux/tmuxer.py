import argparse
import json5
import os
import os.path as osp
import rich
import shlex
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import yaml


CommandBatch = Tuple[List[int], List[str]]
LAYOUT_ALIASES = {
    "eh": "even-horizontal",
    "ev": "even-vertical",
    "mh": "main-horizontal",
    "mv": "main-vertical",
    "t": "tiled",
}
LAYOUT_OPTIONS = set(LAYOUT_ALIASES.values()).union(set(LAYOUT_ALIASES.keys()))
CONFIG_CANDIDATES = (
    ".tmuxer.json",
    ".tmuxer.json5",
    ".tmuxer.yaml",
    ".tmuxer.yml",
)


def start_tmux_session(
    session_name,
    window_name=None,
    pane_index=None,
    new_panes=1,
    layout="even-vertical",
    command_batches=None,
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

    for pane_index in range(new_panes):
        os.system(f"tmux send-keys -t {session_name}.{pane_index} 'export IID={pane_index}' C-m")

    _send_commands_to_panes(session_name=session_name, command_batches=command_batches)

    # Select the specified pane if provided
    if pane_index is not None:
        os.system(f"tmux select-pane -t {session_name}:{pane_index}")

    # Attach to the tmux session
    os.system(f"tmux attach-session -t {session_name}")


def _normalize_layout(layout_arg: str) -> str:
    v = str(layout_arg).lower().strip()
    if v in LAYOUT_ALIASES:
        return LAYOUT_ALIASES[v]
    if v in LAYOUT_ALIASES.values():
        return v
    raise ValueError("layout must be one of: " + ", ".join(sorted(LAYOUT_OPTIONS)))


def _send_commands_to_panes(session_name: str, command_batches: Optional[Sequence[CommandBatch]]):
    """Run configured command batches sequentially across panes."""

    if not command_batches:
        return

    for pane_indices, pane_commands in command_batches:
        for pane_index in pane_indices:
            for cmd in pane_commands:
                os.system(f"tmux send-keys -t {session_name}.{pane_index} {shlex.quote(cmd)} C-m")


def _load_config(path_argument: Optional[str]) -> dict:
    if path_argument:
        cfg_path = Path(path_argument).expanduser()
        if not cfg_path.is_file():
            raise FileNotFoundError(f"Config file not found: {cfg_path}")
    else:
        cfg_path = _detect_config_path()

    if not cfg_path:
        return {}

    data = _parse_config_file(cfg_path)

    if not isinstance(data, dict):
        raise ValueError("Top-level structure in config must be an object")

    rich.print("Using tmuxer config from ", cfg_path)
    rich.print(data)

    return data


def _detect_config_path() -> Optional[Path]:
    cwd = Path.cwd()
    for filename in CONFIG_CANDIDATES:
        candidate = cwd / filename
        if candidate.is_file():
            return candidate
    return None


def _parse_config_file(cfg_path: Path):
    suffix = cfg_path.suffix.lower()
    with cfg_path.open("r", encoding="utf-8") as handle:
        if suffix in {".yaml", ".yml"}:
            return yaml.safe_load(handle)
        return json5.load(handle)


def _coalesce(value, fallback):
    return value if value is not None else fallback


def _normalize_commands(commands: Optional[Sequence[dict]]) -> List[CommandBatch]:
    if not commands:
        return []

    if not isinstance(commands, list):
        raise ValueError("commands section must be a list of command blocks")

    normalized: List[CommandBatch] = []

    for idx, block in enumerate(commands):
        if not isinstance(block, dict):
            raise ValueError(f"Command block #{idx + 1} must be a JSON object")

        pane_spec = block.get("pane_index")
        if pane_spec is None:
            raise ValueError("Each command block requires a pane_index")

        pane_indices = _parse_pane_indices(pane_spec)

        pane_commands = block.get("commands")
        if not isinstance(pane_commands, list):
            raise ValueError("commands list must be a list.")

        normalized.append((pane_indices, [str(cmd) for cmd in pane_commands]))

    return normalized


def _parse_pane_indices(pane_spec) -> List[int]:
    if isinstance(pane_spec, int):
        return [pane_spec]

    if isinstance(pane_spec, list):
        if not pane_spec:
            raise ValueError("pane_index arrays cannot be empty")
        parsed = []
        for pane_value in pane_spec:
            if not isinstance(pane_value, int):
                raise ValueError("pane_index entries must be integers")
            parsed.append(pane_value)
        return sorted(set(parsed))

    if isinstance(pane_spec, str):
        pane_spec = pane_spec.strip()
        if not pane_spec:
            raise ValueError("pane_index string cannot be empty")

        segments = [seg.strip() for seg in pane_spec.split(",") if seg.strip()]
        indices: List[int] = []
        for segment in segments:
            if "-" in segment:
                parts = segment.split("-", 1)
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    raise ValueError(f"Invalid pane range '{segment}'")
                start = int(parts[0])
                end = int(parts[1])
                if start > end:
                    raise ValueError(f"pane range start must be <= end in '{segment}'")
                indices.extend(list(range(start, end + 1)))
            else:
                indices.append(int(segment))

        if not indices:
            raise ValueError("pane_index string must resolve to at least one pane")
        return sorted(set(indices))

    raise ValueError("pane_index must be int, list of ints, or a string specification")


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
    parser.add_argument(
        "--layout",
        type=str,
        choices=sorted(LAYOUT_OPTIONS),
        help="Layout for the tmux panes",
    )
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
    command_batches = _normalize_commands(config.get("commands"))

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
        command_batches=command_batches,
    )


if __name__ == "__main__":
    main()
