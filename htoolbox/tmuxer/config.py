from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

_PSTRING_RE = re.compile(r'^py`(.*)`$', re.DOTALL)


def _eval_pstring(value):
    """If *value* is a p-string like py`<expr>`, evaluate and return the result.
    Otherwise return *value* unchanged."""
    if not isinstance(value, str):
        return value
    m = _PSTRING_RE.match(value.strip())
    if not m:
        return value
    expr = m.group(1)
    try:
        return eval(expr)  # noqa: S307
    except Exception as exc:
        raise ValueError(f"py-string eval failed for: {expr!r}\n  {type(exc).__name__}: {exc}") from None

@dataclass
class CommandBatch:
    pane_indices: list[int]
    commands: list[str]
    ssh_server: Optional[str]
    use_sentinel: bool

    def __post_init__(self):
        if not isinstance(self.pane_indices, list) or not all(isinstance(i, int) for i in self.pane_indices):
            raise TypeError("pane_indices must be a list of ints")
        if not isinstance(self.commands, list) or not all(isinstance(c, str) for c in self.commands):
            raise TypeError("commands must be a list of strings")
        if self.ssh_server is not None and not isinstance(self.ssh_server, str):
            raise TypeError("ssh_server must be a string or None")
        if not isinstance(self.use_sentinel, bool):
            raise TypeError("use_sentinel must be a bool")

    @classmethod
    def from_dict(cls, data: dict, idx: int = 0) -> "CommandBatch":
        if not isinstance(data, dict):
            raise ValueError(f"Command block #{idx + 1} must be a dict")

        pane_spec = data.get("pane_index")
        if pane_spec is None:
            raise ValueError("Each command block requires a pane_index")

        pane_commands = data.get("commands")
        if not isinstance(pane_commands, list):
            raise ValueError("commands list must be a list.")

        ssh_server = data.get("ssh_server")
        if ssh_server is not None:
            ssh_server = str(ssh_server)
            if not ssh_server.strip():
                raise ValueError("ssh_server cannot be empty")

        return cls(
            pane_indices=cls._parse_pane_indices(pane_spec),
            commands=[str(cmd) for cmd in pane_commands],
            ssh_server=ssh_server,
            use_sentinel=bool(data.get("sentinel", True)),
        )

    def validate_panes(self, num_panes: int) -> None:
        for pane_index in self.pane_indices:
            if pane_index < 0 or pane_index >= num_panes:
                raise ValueError(f"command pane index {pane_index} is out of range")

    @staticmethod
    def _parse_pane_indices(pane_spec) -> list[int]:
        pane_spec = _eval_pstring(pane_spec)
        if isinstance(pane_spec, int):
            return [pane_spec]

        if isinstance(pane_spec, list):
            if not pane_spec:
                raise ValueError("pane_index arrays cannot be empty")
            if not all(isinstance(v, int) for v in pane_spec):
                raise ValueError("pane_index entries must be integers")
            return sorted(set(pane_spec))

        if isinstance(pane_spec, str):
            pane_spec = pane_spec.strip()
            if not pane_spec:
                raise ValueError("pane_index string cannot be empty")
            indices: list[int] = []
            for segment in (seg.strip() for seg in pane_spec.split(",") if seg.strip()):
                if "-" in segment:
                    parts = segment.split("-", 1)
                    if len(parts) != 2 or not parts[0] or not parts[1]:
                        raise ValueError(f"Invalid pane range '{segment}'")
                    start, end = int(parts[0]), int(parts[1])
                    if start > end:
                        raise ValueError(f"pane range start must be <= end in '{segment}'")
                    indices.extend(range(start, end + 1))
                else:
                    indices.append(int(segment))
            if not indices:
                raise ValueError("pane_index string must resolve to at least one pane")
            return sorted(set(indices))

        raise ValueError("pane_index must be int, list of ints, or a string specification")


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
        self.num_panes = int(_eval_pstring(self.num_panes))
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
            self.focus_pane = int(_eval_pstring(self.focus_pane))

        self.commands = self._validate_commands(self.commands)

        if self.focus_pane < 0 or self.focus_pane >= self.num_panes:
            raise ValueError(f"focus_pane index {self.focus_pane} is out of range")

    def _validate_commands(self, value) -> list[CommandBatch]:
        if not value:
            return []
        if not isinstance(value, list):
            raise ValueError("commands section must be a list of command blocks")
        batches = [CommandBatch.from_dict(block, idx) for idx, block in enumerate(value)]
        for batch in batches:
            batch.validate_panes(self.num_panes)
        return batches

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
            self.focus_window = int(_eval_pstring(self.focus_window))

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
