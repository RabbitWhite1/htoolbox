from __future__ import annotations

import argparse
import functools
import os
import os.path as osp
import re
import shlex
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import json5
import rich
import yaml

from .config import SessionConfig

CommandBatch = Tuple[list[int], list[str], Optional[str]]
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


def tmux_run(
    tmux_args, input=None, capture_output=False, timeout=None, check=False, **kwargs
):
    return subprocess.run(
        ["tmux", *tmux_args],
        input=input,
        capture_output=capture_output,
        timeout=timeout,
        check=check,
        **kwargs,
    )


class Pane:
    def __init__(
        self, uid: int, index: int, service: Service, session: Session, window: Window
    ):
        self.uid = uid
        self.index = index
        self.service = service
        self.session = session
        self.window = window

    def __repr__(self):
        return f"{self.index}%{self.uid}"

    def __str__(self):
        return f"{self.index}%{self.uid}"

    def send_keys(self, command: str, enter: bool = True) -> None:
        """Send keys to this pane."""
        cmd = ["send-keys", "-t", f"%{self.uid}", str(command)]
        if enter:
            cmd.append("C-m")
        tmux_run(cmd)

    def select(self) -> None:
        """Select this pane as active."""
        print(f"Focus on @{self.window.name} %{self.uid}")
        tmux_run(["select-pane", "-t", f"%{self.uid}"])


class Window:
    LAST_ACTIVE = "-"
    ACTIVE = "*"

    def __init__(self, uid: int, name: str, service: Service, session: Session):
        self.uid = uid
        self.name = name
        self.service = service
        self.session = session

    def panes(self, refresh=True) -> list[Pane]:
        if refresh:
            self.service.refresh()
        return [p for p in self.service.panes.values() if p.window is self]

    def split(self, detach: bool = True) -> None:
        """Split an existing tmux window to create a new pane."""
        self.service.refresh()
        cmd = ["split-window"]
        if detach:
            cmd.append("-d")
        cmd.extend(["-t", f"@{self.uid}"])
        tmux_run(cmd)
        self.service.refresh()

    def select_layout(self, layout: str) -> None:
        """Set the layout of panes in a tmux window."""
        target = f"{self.session.name}:{self.name}"
        tmux_run(["select-layout", "-t", target, layout])

    def select(self) -> None:
        """Select this window as active."""
        print(f"Focus on @{self.name}")
        tmux_run(["select-window", "-t", f"@{self.uid}"])

    def pane_by_index(self, pane_index: int, refresh: bool = True) -> Pane:
        """Return a pane in this window by its tmux pane index."""
        for pane in self.panes(refresh=refresh):
            if pane.index == pane_index:
                return pane
        raise ValueError(f"pane index {pane_index} not found in window {self.name}")

    def kill(self, quiet: bool = True) -> None:
        """Kill this tmux window."""
        cmd = ["kill-window", "-t", f"@{self.uid}"]
        if quiet:
            tmux_run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            tmux_run(cmd)
        self.service.refresh()

    def __repr__(self):
        return f"{self.name}@{self.uid}"

    def __str__(self):
        items = []
        for pane in self.panes():
            items.append(f"{self!r} {pane!r}")
        items = sorted(items)
        return "\n".join(items)


class Session:
    SESSION_REGEX = re.compile(r"\$\d+: (\w\d_)+")

    def __init__(self, uid: int, name: str, service: Service):
        self.uid = uid
        self.name = name
        self.service = service

    def windows(self, refresh=True) -> list[Window]:
        if refresh:
            self.service.refresh()
        return [w for w in self.service.windows.values() if w.session is self]

    def new_window(self, window_name: str = None, detach: bool = True) -> Window:
        """Create a new tmux window in this session."""
        existing_window_ids = {w.uid for w in self.windows(refresh=True)}
        target = self.name
        cmd = ["new-window"]
        if detach:
            cmd.append("-d")
        cmd.extend(["-t", target])
        if window_name:
            cmd.extend(["-n", window_name])
        tmux_run(cmd)
        self.service.refresh()
        windows = self.windows(refresh=False)
        for w in windows:
            if w.uid not in existing_window_ids:
                return w
        if window_name:
            for w in windows:
                if w.name == window_name:
                    return w
        if windows:
            return sorted(windows, key=lambda w: w.uid)[-1]
        raise RuntimeError("Failed to create new window")

    def window_by_uid(self, window_uid: int, refresh: bool = True) -> Window:
        """Return a window in this session by tmux window uid."""
        for window in self.windows(refresh=refresh):
            if window.uid == window_uid:
                return window
        raise ValueError(f"window uid {window_uid} not found in session {self.name}")

    def window_by_name(
        self, window_name: str, refresh: bool = True
    ) -> Optional[Window]:
        """Return a window in this session by window name."""
        for window in self.windows(refresh=refresh):
            if window.name == window_name:
                return window
        return None

    def attach(self) -> None:
        """Attach to this tmux session."""
        tmux_run(["attach-session", "-t", self.name])

    def kill(self, quiet: bool = True) -> None:
        """Kill this tmux session."""
        cmd = ["kill-session", "-t", self.name]
        if quiet:
            tmux_run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            tmux_run(cmd)
        self.service.refresh()

    def __repr__(self):
        return f"{self.name}${self.uid}"

    def __str__(self):
        items = []
        for window in self.windows():
            for pane in window.panes():
                items.append(f"{self!r} {window!r} {pane!r}")
        items = sorted(items)
        return "\n".join(items)


class Service:
    def __init__(self):
        self.sessions: dict[int, Session] = {}
        self.windows: dict[int, Window] = {}
        self.panes: dict[int, Pane] = {}
        self.refresh()

    def get_session(self, session_name: str, refresh: bool = True) -> Optional[Session]:
        if refresh:
            self.refresh()
        for session in self.sessions.values():
            if session.name == session_name:
                return session
        return None

    def refresh(self):
        cmd = [
            "list-panes",
            "-a",
            "-F",
            "#{session_id} #{session_name} #{window_id} #{window_name} #{pane_id} #{pane_index}",
        ]
        try:
            result = tmux_run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError:
            self.sessions.clear()
            self.windows.clear()
            self.panes.clear()
            return
        lines = result.stdout.strip().splitlines()

        seen_session_ids: set[int] = set()
        seen_window_ids: set[int] = set()
        seen_pane_ids: set[int] = set()

        for line in lines:
            parts = line.split()
            if len(parts) != 6:
                raise ValueError(f"Unexpected list-panes output format: {line}")
            session_id, session_name, window_id, window_name, pane_id, pane_index = (
                parts
            )
            session_id = int(session_id.removeprefix("$"))
            window_id = int(window_id.removeprefix("@"))
            pane_id = int(pane_id.removeprefix("%"))
            pane_index = int(pane_index)

            seen_session_ids.add(session_id)
            seen_window_ids.add(window_id)
            seen_pane_ids.add(pane_id)

            session = self.sessions.get(session_id)
            if session is None:
                session = Session(uid=session_id, name=session_name, service=self)
                self.sessions[session_id] = session
            session.name = session_name

            window = self.windows.get(window_id)
            if window is None:
                window = Window(
                    uid=window_id, name=window_name, service=self, session=session
                )
                self.windows[window_id] = window
            window.name = window_name
            window.session = session

            pane = self.panes.get(pane_id)
            if pane is None:
                pane = Pane(
                    uid=pane_id,
                    index=pane_index,
                    service=self,
                    session=session,
                    window=window,
                )
                self.panes[pane_id] = pane
            pane.index = pane_index
            pane.session = session
            pane.window = window

        self.sessions = {
            session_id: session
            for session_id, session in self.sessions.items()
            if session_id in seen_session_ids
        }
        self.windows = {
            window_id: window
            for window_id, window in self.windows.items()
            if window_id in seen_window_ids
        }
        self.panes = {
            pane_id: pane
            for pane_id, pane in self.panes.items()
            if pane_id in seen_pane_ids
        }

    def new_session(
        self, session_name: str, window_name: str = None, detach: bool = True
    ) -> Session:
        """Create a new tmux session with an optional window name."""
        cmd = ["new-session"]
        if detach:
            cmd.append("-d")
        cmd.extend(["-s", session_name])
        if window_name:
            cmd.extend(["-n", window_name])
        tmux_run(cmd)
        self.refresh()
        for s in self.sessions.values():
            if s.name == session_name:
                return s
        raise RuntimeError("Failed to create new session")

    def start_session_from_config(
        self,
        config: SessionConfig,
        detach: bool = True,
    ):
        """Start and optionally attach to a tmux session."""
        # Try kill if required.
        existing_session = self.get_session(config.session)
        if existing_session is not None:
            if config.kill:
                existing_session.kill(quiet=True)
            else:
                for window_cfg in config.windows:
                    if not window_cfg.kill:
                        continue
                    if not window_cfg.window:
                        # window name is not specified, don't kill
                        continue
                    window = existing_session.window_by_name(window_cfg.window)
                    if window is None:
                        continue
                    window.kill(quiet=True)

        # Create the session
        session_name = config.session
        windows = config.windows
        focus_window = config.focus_window
        focus_pane = config.windows[focus_window].focus_pane

        if not windows:
            raise ValueError("At least one window must be provided")

        created_windows: list[Window] = []

        for window_index, window_cfg in enumerate(windows):
            window_name = window_cfg.window
            new_panes = window_cfg.num_panes
            layout = window_cfg.layout
            command_batches = window_cfg.commands

            if window_index == 0:
                session = self.new_session(
                    session_name=session_name,
                    window_name=window_name,
                    detach=True,
                )
                window = sorted(session.windows(refresh=True), key=lambda w: w.uid)[0]
            else:
                session = self.get_session(session_name)
                if session is None:
                    raise RuntimeError(
                        f"Session not found after creation: {session_name}"
                    )
                window = session.new_window(window_name=window_name, detach=True)

            created_windows.append(window)

            # Create new panes if specified
            for _ in range(1, new_panes):
                window.split(detach=True)
                window.select_layout(layout)

            window_panes = {pane.index: pane for pane in window.panes(refresh=True)}

            for pane_index in range(new_panes):
                pane = window_panes[pane_index]
                pane.send_keys(f"export IID={pane_index}")

            if command_batches:
                for pane_indices, pane_commands, ssh_server in command_batches:
                    for pane_index in pane_indices:
                        pane = window_panes[pane_index]
                        for cmd in pane_commands:
                            command_text = str(cmd)
                            if ssh_server is not None:
                                remote_command = f"bash -ic {shlex.quote(command_text)}"
                                command_text = (
                                    f"ssh -n {ssh_server} {shlex.quote(remote_command)}"
                                )
                            pane.send_keys(command_text)

            # Select the window's focus pane after setup
            window_focus_pane = int(window_cfg.focus_pane)
            window.pane_by_index(window_focus_pane, refresh=True).select()

        # Select the specified pane/window focus
        if focus_window < 0 or focus_window >= len(created_windows):
            raise ValueError("focus_window is out of range")
        created_windows[focus_window].select()

        if detach:
            return

        # Attach to the tmux session
        if os.environ.get("TMUX"):
            rich.print(
                "[yellow]Detected existing tmux session ($TMUX is set).[/yellow] "
                "New session was created but auto-attach is skipped to keep your current tmux context. "
                f"To force attach later, run: [bold]unset TMUX && tmux attach-session -t {session_name}[/bold]"
            )
            return
        session = self.get_session(session_name)
        if session is None:
            raise RuntimeError(f"Session not found for attach: {session_name}")
        session.attach()

    def __str__(self):
        items = []
        for session in self.sessions.values():
            for window in session.windows():
                for pane in window.panes():
                    items.append(f"{session!r} {window!r} {pane!r}")
        items = sorted(items)
        return "\n".join(items)


def _build_session_config(
    config: dict,
    *,
    session_override: Optional[str] = None,
    kill_override: bool = False,
) -> SessionConfig:
    if not isinstance(config, dict):
        raise ValueError("config must be a dict")

    effective_config = dict(config)
    if session_override is not None:
        effective_config["session"] = session_override
    if kill_override:
        effective_config["kill"] = True

    return SessionConfig.model_validate(effective_config)


def _write_placeholder_config(cfg_path: Path) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(PLACEHOLDER_CONFIG_YAML, encoding="utf-8")


def _detect_config_path() -> Optional[Path]:
    cwd = Path.cwd()
    for filename in CONFIG_CANDIDATES:
        candidate = cwd / filename
        if candidate.is_file():
            return candidate
    return None


def _load_config(config: Path, placeholders: Dict[str, str]):
    suffix = config.suffix.lower()
    with config.open("r", encoding="utf-8") as handle:
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


def session_config_from_args(args: argparse.Namespace) -> SessionConfig:
    if args.config is None:
        if not args.session:
            raise ValueError("--session is required when --config is not provided")

        config = {
            "session": args.session,
            "focus_window": 0,
            "kill": bool(args.kill),
            "windows": [
                {
                    "window": args.window,
                    "num_panes": args.num_panes if args.num_panes is not None else 1,
                    "layout": (
                        args.layout if args.layout is not None else "even-vertical"
                    ),
                    "focus_pane": args.pane if args.pane is not None else 0,
                    "commands": [],
                    "kill": bool(args.kill),
                }
            ],
        }
        session_config = SessionConfig.model_validate(config)
    else:
        placeholder_values = _parse_placeholder_args(args.placeholder)
        config = _load_config(args.config, placeholder_values)

        session_config = _build_session_config(
            config,
            session_override=args.session,
            kill_override=bool(args.kill),
        )

        rich.print("Using tmuxer config from ", Path(args.config).expanduser())

    rich.print(session_config)

    return session_config


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
    parser.add_argument(
        "-d",
        "--detach",
        action="store_true",
        help="Create and configure tmux session in detached mode without attaching",
    )

    args = parser.parse_args()

    if args.config is None:
        args.config = _detect_config_path()
    else:
        args.config = Path(args.config).expanduser()
        if not args.config.is_file():
            _write_placeholder_config(args.config)
            raise FileNotFoundError(
                f"Config file not found. Placeholder created at: {args.config}"
            )

    session_config = session_config_from_args(args)

    if args.dry:
        rich.print("Exiting since --dry specified.")
        return

    service = Service()
    service.start_session_from_config(config=session_config, detach=bool(args.detach))


if __name__ == "__main__":
    main()
