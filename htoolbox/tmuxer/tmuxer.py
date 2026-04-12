from __future__ import annotations

import argparse
import asyncio
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Optional, Sequence

import json5
import rich
import yaml

from .config import LAYOUT_ALIASES, LAYOUT_OPTIONS, SessionConfig
from .service import Service

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
                  - cd @@somedir@@
          - pane_index: "1"
              commands:
                  - cd /bin
          - pane_index: "2"
              commands:
                  - htop
"""
PLACEHOLDER_TOKEN_PATTERN = re.compile(r"@@([A-Za-z_][A-Za-z0-9_]*)@@")


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

    return SessionConfig.from_dict(effective_config)


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
    rendered = text
    for name, value in placeholders.items():
        rendered = rendered.replace(f"@@{name}@@", str(value))

    unresolved = sorted(set(PLACEHOLDER_TOKEN_PATTERN.findall(rendered)))
    if unresolved:
        formatted = "; ".join(
            f"@@{name}@@ (use -P {name}=VALUE)" for name in unresolved
        )
        raise ValueError(
            f"Missing placeholder value(s): {formatted}."
        )

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
        session_config = SessionConfig.from_dict(config)
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
    """Console entry point for the `tmuxer` command."""
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

    try:
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
        command_jobs, session_name = service.create_session(config=session_config)

        if args.detach:
            # No attach — dispatch in foreground then exit.
            asyncio.run(service._dispatch_commands(command_jobs))
            return

        if os.environ.get("TMUX"):
            rich.print(
                "[yellow]Detected existing tmux session ($TMUX is set).[/yellow] "
                "New session was created but auto-attach is skipped to keep your current tmux context. "
                f"To force attach later, run: [bold]unset TMUX && tmux attach-session -t {session_name}[/bold]"
            )
            asyncio.run(service._dispatch_commands(command_jobs))
            return

        async def _attach_and_dispatch():
            task = asyncio.create_task(service._dispatch_commands(command_jobs))
            session = service.get_session(session_name)
            if session is None:
                raise RuntimeError(f"Session not found for attach: {session_name}")
            await asyncio.to_thread(session.attach)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(_attach_and_dispatch())
    except ValueError as exc:
        rich.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
