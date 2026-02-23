from __future__ import annotations

from typing import Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CommandBatch = Tuple[list[int], list[str]]
LAYOUT_ALIASES = {
    "eh": "even-horizontal",
    "ev": "even-vertical",
    "mh": "main-horizontal",
    "mv": "main-vertical",
    "t": "tiled",
}
LAYOUT_OPTIONS = set(LAYOUT_ALIASES.values()).union(set(LAYOUT_ALIASES.keys()))


class WindowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window: Optional[str] = None
    num_panes: int
    layout: str = "even-vertical"
    focus_pane: int = 0
    commands: list[CommandBatch] = Field(default_factory=list)
    kill: bool = False

    @field_validator("num_panes", mode="before")
    @classmethod
    def validate_num_panes(cls, value):
        value = int(value)
        if value < 1:
            raise ValueError("Number of new panes must be at least 1")
        return value

    @field_validator("layout", mode="before")
    @classmethod
    def validate_layout(cls, value):
        value = str(value).lower().strip()
        if value in LAYOUT_ALIASES:
            return LAYOUT_ALIASES[value]
        if value in LAYOUT_ALIASES.values():
            return value
        raise ValueError("layout must be one of: " + ", ".join(sorted(LAYOUT_OPTIONS)))

    @field_validator("focus_pane", mode="before")
    @classmethod
    def validate_focus_pane(cls, value):
        if value is None:
            return 0
        return int(value)

    @field_validator("commands", mode="before")
    @classmethod
    def validate_commands(cls, value):
        if not value:
            return []

        if not isinstance(value, list):
            raise ValueError("commands section must be a list of command blocks")

        normalized: list[CommandBatch] = []

        for idx, block in enumerate(value):
            if not isinstance(block, dict):
                raise ValueError(f"Command block #{idx + 1} must be a JSON object")

            pane_spec = block.get("pane_index")
            if pane_spec is None:
                raise ValueError("Each command block requires a pane_index")

            pane_indices = cls._parse_pane_indices(pane_spec)

            pane_commands = block.get("commands")
            if not isinstance(pane_commands, list):
                raise ValueError("commands list must be a list.")

            normalized.append((pane_indices, [str(cmd) for cmd in pane_commands]))

        return normalized

    @model_validator(mode="after")
    def validate_window_ranges(self):
        if self.focus_pane < 0 or self.focus_pane >= self.num_panes:
            raise ValueError(f"focus_pane index {self.focus_pane} is out of range")
        self._validate_command_panes()
        return self

    def _validate_command_panes(self) -> None:
        for pane_indices, _ in self.commands:
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
                        raise ValueError(f"pane range start must be <= end in '{segment}'")
                    indices.extend(list(range(start, end + 1)))
                else:
                    indices.append(int(segment))

            if not indices:
                raise ValueError("pane_index string must resolve to at least one pane")
            return sorted(set(indices))

        raise ValueError("pane_index must be int, list of ints, or a string specification")


class SessionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: str
    focus_window: int = 0
    windows: list[WindowConfig]
    kill: bool = False

    @field_validator("session", mode="before")
    @classmethod
    def validate_session(cls, value):
        if value is None:
            raise ValueError("session must be a non-empty string")
        value = str(value).strip()
        if not value:
            raise ValueError("session must be a non-empty string")
        return value

    @field_validator("focus_window", mode="before")
    @classmethod
    def validate_focus_window(cls, value):
        if value is None:
            return 0
        return int(value)

    @field_validator("windows", mode="before")
    @classmethod
    def validate_windows(cls, value):
        if not isinstance(value, list) or not value:
            raise ValueError("windows must be a non-empty list")
        return value

    @model_validator(mode="after")
    def validate_focus_window_range(self):
        if self.focus_window < 0 or self.focus_window >= len(self.windows):
            raise ValueError("focus_window is out of range")
        return self
