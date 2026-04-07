from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

CommandBatch = Tuple[list[int], list[str], Optional[str]]
LAYOUT_ALIASES = {
    "eh": "even-horizontal",
    "ev": "even-vertical",
    "mh": "main-horizontal",
    "mv": "main-vertical",
    "t": "tiled",
}
LAYOUT_OPTIONS = set(LAYOUT_ALIASES.values()).union(set(LAYOUT_ALIASES.keys()))

_WINDOW_CONFIG_FIELDS = {"window", "num_panes", "layout", "focus_pane", "commands", "kill", "ssh_server"}
_SESSION_CONFIG_FIELDS = {"session", "focus_window", "windows", "kill"}


@dataclass
class WindowConfig:
    num_panes: int
    window: Optional[str] = None
    layout: str = "even-vertical"
    focus_pane: int = 0
    commands: list[CommandBatch] = field(default_factory=list)
    kill: bool = False

    def __post_init__(self):
        self.num_panes = int(self.num_panes)
        if self.num_panes < 1:
            raise ValueError("Number of new panes must be at least 1")

        value = str(self.layout).lower().strip()
        if value in LAYOUT_ALIASES:
            self.layout = LAYOUT_ALIASES[value]
        elif value in LAYOUT_ALIASES.values():
            self.layout = value
        else:
            raise ValueError("layout must be one of: " + ", ".join(sorted(LAYOUT_OPTIONS)))

        if self.focus_pane is None:
            self.focus_pane = 0
        else:
            self.focus_pane = int(self.focus_pane)

        self.commands = self._validate_commands(self.commands)

        if self.focus_pane < 0 or self.focus_pane >= self.num_panes:
            raise ValueError(f"focus_pane index {self.focus_pane} is out of range")
        self._validate_command_panes()

    def _validate_commands(self, value) -> list[CommandBatch]:
        if not value:
            return []

        if not isinstance(value, list):
            raise ValueError("commands section must be a list of command blocks")

        normalized: list[CommandBatch] = []

        for idx, block in enumerate(value):
            if isinstance(block, (tuple, list)) and len(block) == 2:
                pane_spec, pane_commands = block
                pane_indices = self._parse_pane_indices(pane_spec)
                if not isinstance(pane_commands, (list, tuple)):
                    raise ValueError("commands list must be a list.")
                normalized.append(
                    (pane_indices, [str(cmd) for cmd in pane_commands], None)
                )
                continue

            if isinstance(block, (tuple, list)) and len(block) == 3:
                pane_spec, pane_commands, ssh_server = block
                pane_indices = self._parse_pane_indices(pane_spec)
                if not isinstance(pane_commands, (list, tuple)):
                    raise ValueError("commands list must be a list.")
                if ssh_server is not None and not str(ssh_server).strip():
                    raise ValueError("ssh_server cannot be empty")
                normalized.append(
                    (
                        pane_indices,
                        [str(cmd) for cmd in pane_commands],
                        None if ssh_server is None else str(ssh_server),
                    )
                )
                continue

            if not isinstance(block, dict):
                raise ValueError(
                    f"Command block #{idx + 1} must be a JSON object or a (pane_indices, commands) pair"
                )

            pane_spec = block.get("pane_index")
            if pane_spec is None:
                raise ValueError("Each command block requires a pane_index")

            pane_indices = self._parse_pane_indices(pane_spec)

            pane_commands = block.get("commands")
            if not isinstance(pane_commands, list):
                raise ValueError("commands list must be a list.")

            ssh_server = block.get("ssh_server")
            if ssh_server is not None:
                ssh_server = str(ssh_server)
                if not ssh_server.strip():
                    raise ValueError("ssh_server cannot be empty")

            normalized.append(
                (
                    pane_indices,
                    [str(cmd) for cmd in pane_commands],
                    ssh_server,
                )
            )

        return normalized

    def _validate_command_panes(self) -> None:
        for pane_indices, _, _ in self.commands:
            for pane_index in pane_indices:
                if pane_index < 0 or pane_index >= self.num_panes:
                    raise ValueError(f"command pane index {pane_index} is out of range")

    @staticmethod
    def _parse_pane_indices(pane_spec) -> list[int]:
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
            indices: list[int] = []
            for segment in segments:
                if "-" in segment:
                    parts = segment.split("-", 1)
                    if len(parts) != 2 or not parts[0] or not parts[1]:
                        raise ValueError(f"Invalid pane range '{segment}'")
                    start = int(parts[0])
                    end = int(parts[1])
                    if start > end:
                        raise ValueError(
                            f"pane range start must be <= end in '{segment}'"
                        )
                    indices.extend(list(range(start, end + 1)))
                else:
                    indices.append(int(segment))

            if not indices:
                raise ValueError("pane_index string must resolve to at least one pane")
            return sorted(set(indices))

        raise ValueError(
            "pane_index must be int, list of ints, or a string specification"
        )

    @classmethod
    def from_dict(cls, data: dict) -> "WindowConfig":
        unknown = set(data) - _WINDOW_CONFIG_FIELDS
        if unknown:
            raise ValueError(
                f"Unknown fields in window config: {', '.join(sorted(unknown))}"
            )
        return cls(
            window=data.get("window"),
            num_panes=data["num_panes"],
            layout=data.get("layout", "even-vertical"),
            focus_pane=data.get("focus_pane", 0),
            commands=data.get("commands", []),
            kill=bool(data.get("kill", False)),
        )


@dataclass
class SessionConfig:
    session: str
    windows: list[WindowConfig]
    focus_window: int = 0
    kill: bool = False

    def __post_init__(self):
        if self.session is None:
            raise ValueError("session must be a non-empty string")
        self.session = str(self.session).strip()
        if not self.session:
            raise ValueError("session must be a non-empty string")

        if self.focus_window is None:
            self.focus_window = 0
        else:
            self.focus_window = int(self.focus_window)

        if not isinstance(self.windows, list) or not self.windows:
            raise ValueError("windows must be a non-empty list")

        if self.focus_window < 0 or self.focus_window >= len(self.windows):
            raise ValueError("focus_window is out of range")

    @classmethod
    def from_dict(cls, data: dict) -> "SessionConfig":
        unknown = set(data) - _SESSION_CONFIG_FIELDS
        if unknown:
            raise ValueError(
                f"Unknown fields in session config: {', '.join(sorted(unknown))}"
            )

        raw_windows = data.get("windows")
        if not isinstance(raw_windows, list) or not raw_windows:
            raise ValueError("windows must be a non-empty list")

        windows = [
            WindowConfig.from_dict(w) if isinstance(w, dict) else w
            for w in raw_windows
        ]

        return cls(
            session=data.get("session"),
            focus_window=data.get("focus_window", 0),
            windows=windows,
            kill=bool(data.get("kill", False)),
        )
