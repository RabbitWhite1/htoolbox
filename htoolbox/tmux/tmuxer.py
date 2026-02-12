import argparse
import os
import os.path as osp
import shlex
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import json5
import rich
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
PLACEHOLDER_CONFIG_YAML = """# An example tmuxer config file.
session: tmuxer-session
focus_window: 0
windows:
    - window: workspace
      num_panes: 3
      layout: even-vertical
      focus_pane: 0
      kill: true
      commands:
          - pane_index: "0-1"
              commands:
                  - bash
          - pane_index: "0"
              commands:
                  - bash
                  - cd <somedir>
          - pane_index: "1"
              commands:
                  - cd /bin
          - pane_index: "2"
              commands:
                  - htop
"""


def start_tmux_session(
    session_name,
    windows,
    focus_window=0,
    focus_pane=0,
):
    """Start and attach to a tmux session.

    This function uses the `tmux` command-line tool. It is designed to be
    called from the CLI entry point `main()` below, but can also be imported
    and used programmatically.
    """
    if not windows:
        raise ValueError("At least one window must be provided")

    for window_index, window_cfg in enumerate(windows):
        window_name = window_cfg.get("window")
        new_panes = window_cfg["num_panes"]
        layout = window_cfg["layout"]
        command_batches = window_cfg.get("commands")

        if window_index == 0:
            if window_name:
                os.system(f"tmux new-session -d -s {session_name} -n {window_name}")
            else:
                os.system(f"tmux new-session -d -s {session_name}")
        else:
            if window_name:
                os.system(f"tmux new-window -t {session_name} -n {window_name}")
            else:
                os.system(f"tmux new-window -t {session_name}")

        window_target = f"{session_name}:{window_index}"

        # Create new panes if specified
        for _ in range(1, new_panes):
            os.system(f"tmux split-window -t {window_target}")
            os.system(f"tmux select-layout -t {window_target} {layout}")

        for pane_index in range(new_panes):
            os.system(
                f"tmux send-keys -t {window_target}.{pane_index} 'export IID={pane_index}' C-m"
            )

        _send_commands_to_panes(
            session_name=session_name,
            window_index=window_index,
            command_batches=command_batches,
        )

        # Select the window's focus pane after setup
        window_focus_pane = int(window_cfg.get("focus_pane", 0))
        os.system(f"tmux select-pane -t {window_target}.{window_focus_pane}")

    # Select the specified pane/window focus
    os.system(f"tmux select-pane -t {session_name}:{focus_window}.{focus_pane}")

    # Attach to the tmux session
    if os.environ.get("TMUX"):
        rich.print(
            "[yellow]Detected existing tmux session ($TMUX is set).[/yellow] "
            "New session was created but auto-attach is skipped to keep your current tmux context. "
            f"To force attach later, run: [bold]unset TMUX && tmux attach-session -t {session_name}[/bold]"
        )
        return
    os.system(f"tmux attach-session -t {session_name}")


def _prepare_session_from_config(
    config: dict,
    *,
    session_override: Optional[str] = None,
    kill_override: bool = False,
) -> tuple[str, List[dict], bool, int, int]:
    if not isinstance(config, dict):
        raise ValueError("config must be a dict")

    session = _coalesce(session_override, config.get("session"))
    if not session or not isinstance(session, str):
        raise ValueError("session must be a non-empty string")

    raw_windows = config.get("windows")
    if not isinstance(raw_windows, list) or not raw_windows:
        raise ValueError("windows must be a non-empty list")

    window_configs = _normalize_window_configs(raw_windows)

    kill_existing = (
        bool(kill_override)
        or bool(config.get("kill"))
        or any(bool(cfg.get("kill")) for cfg in window_configs)
    )

    focus_window = int(config.get("focus_window", 0))
    if focus_window < 0 or focus_window >= len(window_configs):
        raise ValueError("focus_window is out of range")

    focus_pane = int(window_configs[focus_window].get("focus_pane", 0))

    return session, window_configs, kill_existing, focus_window, focus_pane


def run_with_config(config: dict) -> None:
    """Run tmuxer with a config dict.

    Expected schema (same as file config):
    {
        "session": "name",                       # required
        "focus_window": 0,                        # optional
        "kill": true|false,                      # optional
        "windows": [                             # required
            {
                "window": "optional window name",
                "num_panes": 3,                  # required
                "layout": "even-vertical",      # optional (default: even-vertical)
                "focus_pane": 0,                 # optional focus pane within this window
                "kill": true|false,              # optional, contributes to kill behavior
                "commands": [                    # optional
                    {"pane_index": "0-1", "commands": ["bash"]},
                ],
            }
        ],
    }
    """

    session, window_configs, kill_existing, focus_window, focus_pane = (
        _prepare_session_from_config(config)
    )

    if kill_existing:
        os.system(f"tmux kill-session -t {session} >/dev/null 2>&1")

    start_tmux_session(
        session_name=session,
        windows=window_configs,
        focus_window=focus_window,
        focus_pane=focus_pane,
    )


def _normalize_layout(layout_arg: str) -> str:
    v = str(layout_arg).lower().strip()
    if v in LAYOUT_ALIASES:
        return LAYOUT_ALIASES[v]
    if v in LAYOUT_ALIASES.values():
        return v
    raise ValueError("layout must be one of: " + ", ".join(sorted(LAYOUT_OPTIONS)))


def _send_commands_to_panes(
    session_name: str,
    window_index: int,
    command_batches: Optional[Sequence[CommandBatch]],
):
    """Run configured command batches sequentially across panes."""

    if not command_batches:
        return

    window_target = f"{session_name}:{window_index}"
    for pane_indices, pane_commands in command_batches:
        for pane_index in pane_indices:
            for cmd in pane_commands:
                os.system(
                    f"tmux send-keys -t {window_target}.{pane_index} {shlex.quote(cmd)} C-m"
                )


def _write_placeholder_config(cfg_path: Path) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(PLACEHOLDER_CONFIG_YAML, encoding="utf-8")


def _load_config(
    path_argument: Optional[str], placeholders: Optional[Dict[str, str]] = None
) -> dict:
    if path_argument:
        cfg_path = Path(path_argument).expanduser()
        if not cfg_path.is_file():
            _write_placeholder_config(cfg_path)
            raise FileNotFoundError(
                f"Config file not found. Placeholder created at: {cfg_path}"
            )
    else:
        cfg_path = _detect_config_path()

    if not cfg_path:
        return {}

    data = _parse_config_file(cfg_path, placeholders or {})

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


def _parse_config_file(cfg_path: Path, placeholders: Dict[str, str]):
    suffix = cfg_path.suffix.lower()
    with cfg_path.open("r", encoding="utf-8") as handle:
        contents = handle.read()

    rendered = _apply_placeholders(contents, placeholders)

    if suffix in {".yaml", ".yml"}:
        return yaml.safe_load(rendered)
    return json5.loads(rendered)


def _apply_placeholders(text: str, placeholders: Dict[str, str]) -> str:
    if not placeholders:
        return text

    rendered = text
    for name, value in placeholders.items():
        rendered = rendered.replace(f"<{name}>", str(value))
    return rendered


def _parse_placeholder_args(raw_values: Optional[Sequence[str]]) -> Dict[str, str]:
    if not raw_values:
        return {}

    placeholders: Dict[str, str] = {}
    for raw in raw_values:
        if "=" not in raw:
            raise ValueError("Placeholder definitions must be in NAME=VALUE format")
        name, value = raw.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError("Placeholder names cannot be empty")
        placeholders[name] = value

    return placeholders


def _coalesce(value, fallback):
    return value if value is not None else fallback


def _normalize_window_configs(raw_windows: Sequence[dict]) -> List[dict]:
    if not isinstance(raw_windows, list) or not raw_windows:
        raise ValueError("windows must be a non-empty list")

    normalized: List[dict] = []

    for idx, window_cfg in enumerate(raw_windows):
        if not isinstance(window_cfg, dict):
            raise ValueError(f"window entry #{idx + 1} must be an object")

        num_panes = window_cfg.get("num_panes")
        if num_panes is None:
            raise ValueError(f"window entry #{idx + 1} must define num_panes")
        num_panes = int(num_panes)
        if num_panes < 1:
            raise ValueError("Number of new panes must be at least 1")

        focus_pane = window_cfg.get("focus_pane")
        focus_pane_index = int(focus_pane) if focus_pane is not None else 0
        if focus_pane_index < 0 or focus_pane_index >= num_panes:
            raise ValueError(
                f"focus_pane index {focus_pane_index} is out of range for window #{idx + 1}"
            )

        layout_arg = window_cfg.get("layout", "even-vertical")
        layout = _normalize_layout(layout_arg)

        command_batches = _normalize_commands(window_cfg.get("commands"))
        _validate_command_panes(command_batches, num_panes, idx + 1)

        normalized.append(
            {
                "window": window_cfg.get("window"),
                "num_panes": num_panes,
                "layout": layout,
                "focus_pane": focus_pane_index,
                "commands": command_batches,
                "kill": window_cfg.get("kill"),
            }
        )

    return normalized


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


def _validate_command_panes(
    command_batches: List[CommandBatch], num_panes: int, window_number: int
) -> None:
    for pane_indices, _ in command_batches:
        for pane_index in pane_indices:
            if pane_index < 0 or pane_index >= num_panes:
                raise ValueError(
                    f"command pane index {pane_index} is out of range for window #{window_number}"
                )


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
    parser.add_argument(
        "-n", "--num_panes", type=int, help="Number of new panes to create"
    )
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
        "--kill",
        action="store_true",
        help="Kill existing tmux session with the same name before starting a new one",
    )
    parser.add_argument("-c", "--config", type=str, help="Path to tmuxer config file")
    parser.add_argument(
        "-P",
        "--placeholder",
        metavar="NAME=VALUE",
        action="append",
        default=[],
        help="Define placeholder substitutions for config files; repeatable",
    )
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Load and print config, then exit without starting tmux",
    )

    args = parser.parse_args()

    placeholder_values = _parse_placeholder_args(args.placeholder)
    config = _load_config(args.config, placeholder_values)

    if args.dry:
        return

    session, window_configs, kill_existing, focus_window, focus_pane = (
        _prepare_session_from_config(
            config,
            session_override=args.session,
            kill_override=bool(args.kill),
        )
    )

    if kill_existing:
        # Prefer to silence output from tmux kill-session so CLI stays quiet
        os.system(f"tmux kill-session -t {session} >/dev/null 2>&1")

    start_tmux_session(
        session_name=session,
        windows=window_configs,
        focus_window=focus_window,
        focus_pane=focus_pane,
    )


if __name__ == "__main__":
    main()
