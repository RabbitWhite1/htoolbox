from __future__ import annotations

import asyncio
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional

import rich

from .config import CommandBatch, SessionConfig


@dataclass
class CommandJob:
    window_panes: dict[int, "Pane"]
    num_panes: int
    command_batches: list[CommandBatch]
    window: "Window"
    synchronized_panes: bool


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


async def tmux_run_async(tmux_args, capture_output=False, check=False):
    """Async tmux runner using asyncio subprocesses — no threads."""
    stdout = asyncio.subprocess.PIPE if capture_output else None
    stderr = asyncio.subprocess.PIPE if capture_output else None
    proc = await asyncio.create_subprocess_exec(
        "tmux", *tmux_args, stdout=stdout, stderr=stderr
    )
    stdout_data, _ = await proc.communicate()
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, ["tmux", *tmux_args])
    return subprocess.CompletedProcess(
        args=["tmux", *tmux_args],
        returncode=proc.returncode,
        stdout=stdout_data.decode() if stdout_data else None,
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
        self._send_count = 0

    def __repr__(self):
        return f"{self.index}%{self.uid}"

    def __str__(self):
        return f"{self.index}%{self.uid}"

    async def send_keys(
        self,
        command: str,
        enter: bool = True,
        timeout: float = 1800.0,
        use_sentinel: bool = True,
    ) -> None:
        """Send keys to this pane and optionally wait for completion via a sentinel echo."""
        cmd = ["send-keys", "-t", f"%{self.uid}", str(command)]
        if enter:
            cmd.append("C-m")
        await tmux_run_async(cmd)
        if not enter or not use_sentinel:
            return
        sentinel = f"__TMUXER_{self._send_count}__"
        self._send_count += 1
        await self._wait_for_sentinel(sentinel, timeout)

    async def _wait_for_sentinel(self, sentinel: str, timeout: float) -> None:
        """Periodically send a sentinel-echo until it appears in capture-pane.

        Each ping runs:
            : "${SENTINEL:=$?}"; echo "SENTINEL returncode=$SENTINEL"
        The first ping captures $? of the preceding user command into a shell
        variable named after the sentinel (tmux send-keys has no return channel,
        so echoing $? back into the pane is the only way to surface it).
        Subsequent pings re-echo the same value (the `:=` default is a no-op
        once the variable is set).

        Ping interval starts at 1s and doubles up to 16s. Sending pings on an
        interval (rather than once) handles two cases:
        - PTY C-m race: if the first ping races with the command's C-m and gets
          dropped, a later ping will succeed once the PTY has caught up.
        - Interactive commands (e.g. 'ssh <server>'): pings queue up in the PTY
          and execute once the (remote) shell becomes ready.
        """
        match_re = re.compile(rf"^{re.escape(sentinel)} returncode=\d+$")
        ping_cmd = f': "${{{sentinel}:=$?}}"; echo "{sentinel} returncode=${sentinel}"'
        deadline = asyncio.get_event_loop().time() + timeout
        last_ping = float("-inf")
        ping_interval = 1.0
        while asyncio.get_event_loop().time() < deadline:
            now = asyncio.get_event_loop().time()
            if now - last_ping >= ping_interval:
                await tmux_run_async(
                    ["send-keys", "-t", f"%{self.uid}", ping_cmd, "C-m"]
                )
                if last_ping != float("-inf"):
                    ping_interval = min(ping_interval * 2, 16.0)
                last_ping = now
            result = await tmux_run_async(
                ["capture-pane", "-t", f"%{self.uid}", "-p"],
                capture_output=True,
            )
            if any(
                match_re.match(line.strip())
                for line in (result.stdout or "").splitlines()
            ):
                return
            await asyncio.sleep(0.05)
        rich.print(
            f"[yellow]Warning:[/yellow] timed out waiting for pane %{self.uid} after {timeout}s"
        )

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

    def set_synchronize_panes(self, on: bool) -> None:
        """Enable or disable tmux synchronize-panes for this window."""
        tmux_run(
            [
                "set-window-option",
                "-t",
                f"@{self.uid}",
                "synchronize-panes",
                "on" if on else "off",
            ]
        )

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

    def create_session(self, config: SessionConfig) -> tuple[list[CommandJob], str]:
        """Synchronously create all tmux windows and panes.

        Returns (command_jobs, session_name). command_jobs is consumed by
        _dispatch_commands to send the actual keystrokes.
        """
        existing_session = self.get_session(config.session)
        if existing_session is not None:
            if config.kill:
                existing_session.kill(quiet=True)
            else:
                for window_cfg in config.windows:
                    if not window_cfg.kill or not window_cfg.window:
                        continue
                    window = existing_session.window_by_name(window_cfg.window)
                    if window is not None:
                        window.kill(quiet=True)

        session_name = config.session
        windows = config.windows
        focus_window = config.focus_window

        if not windows:
            raise ValueError("At least one window must be provided")

        created_windows: list[Window] = []
        command_jobs: list[CommandJob] = []

        for window_index, window_cfg in enumerate(windows):
            if window_index == 0:
                session = self.new_session(
                    session_name=session_name,
                    window_name=window_cfg.window,
                    detach=True,
                )
                window = sorted(session.windows(refresh=True), key=lambda w: w.uid)[0]
            else:
                session = self.get_session(session_name)
                if session is None:
                    raise RuntimeError(
                        f"Session not found after creation: {session_name}"
                    )
                window = session.new_window(window_name=window_cfg.window, detach=True)

            created_windows.append(window)

            for _ in range(1, window_cfg.num_panes):
                window.split(detach=True)
                window.select_layout(window_cfg.layout)

            window_panes = {pane.index: pane for pane in window.panes(refresh=True)}
            command_jobs.append(
                CommandJob(
                    window_panes=window_panes,
                    num_panes=window_cfg.num_panes,
                    command_batches=window_cfg.commands,
                    window=window,
                    synchronized_panes=window_cfg.synchronized_panes,
                )
            )
            window.pane_by_index(int(window_cfg.focus_pane), refresh=True).select()

        if focus_window < 0 or focus_window >= len(created_windows):
            raise ValueError("focus_window is out of range")
        created_windows[focus_window].select()

        return command_jobs, session_name

    async def _dispatch_commands(self, command_jobs: list[CommandJob]) -> None:
        """Send all command batches to their panes.

        Within each batch, all panes run their commands concurrently.
        Batches still execute in order — the next batch starts only after
        all panes in the current batch have finished.
        """

        async def _run_pane(
            pane: Pane,
            pane_commands: list,
            ssh_server: Optional[str],
            use_sentinel: bool,
            is_last_batch: bool,
        ):
            for i, cmd in enumerate(pane_commands):
                command_text = str(cmd)
                if ssh_server is not None:
                    remote_command = f"bash -ic {shlex.quote(command_text)}"
                    command_text = f"ssh -n {ssh_server} {shlex.quote(remote_command)}"
                is_last_cmd = is_last_batch and (i == len(pane_commands) - 1)
                await pane.send_keys(
                    command_text, use_sentinel=use_sentinel and not is_last_cmd
                )

        for job in command_jobs:
            await asyncio.gather(
                *[
                    job.window_panes[i].send_keys(
                        f"export IID={i} NUM_PANES={job.num_panes}"
                    )
                    for i in range(job.num_panes)
                ]
            )
            # Pre-compute the last batch index each pane appears in.
            last_batch_for_pane: dict[int, int] = {}
            for batch_idx, batch in enumerate(job.command_batches):
                for pane_index in batch.pane_indices:
                    last_batch_for_pane[pane_index] = batch_idx

            for batch_idx, batch in enumerate(job.command_batches):
                await asyncio.gather(
                    *[
                        _run_pane(
                            job.window_panes[pane_index],
                            batch.commands,
                            batch.ssh_server,
                            batch.use_sentinel,
                            last_batch_for_pane.get(pane_index) == batch_idx,
                        )
                        for pane_index in batch.pane_indices
                    ]
                )

            if job.synchronized_panes:
                job.window.set_synchronize_panes(True)

    def __str__(self):
        items = []
        for session in self.sessions.values():
            for window in session.windows():
                for pane in window.panes():
                    items.append(f"{session!r} {window!r} {pane!r}")
        items = sorted(items)
        return "\n".join(items)
