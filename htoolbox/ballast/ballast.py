#!/usr/bin/env python3
"""ballast -- adaptive CPU + memory load generator (Linux only, stdlib only).

Keeps *total system* memory usage and/or *total system* CPU utilization near a
target percentage. It only fills the gap between what other processes use and
the target: when other processes use more, the ballast shrinks (down to zero);
when they use less, it grows back. It never competes with the real workload.

Usage:
    ballast --mem 25 --cpu 25          # both
    ballast --mem 25                   # memory only
    ballast --cpu 40                   # CPU only
    python3 ballast.py --mem 25        # standalone copy of this file works too

Options:
    --mem PCT            target total system memory usage (%)
    --cpu PCT            target total system CPU utilization (%)
    --chunk-mib N        memory ballast chunk size in MiB (default 64)
    --interval S         control loop period in seconds (default 0.5)
    --max-grow N         max memory chunks added per tick (default 8)
    --ramp S             growth time constant in seconds (default 10, 0 = instant)
    --delta PCT          random fluctuation of the targets, +/- percentage points
                         (default 5, 0 = steady targets)
    --delta-period S     mean hold time of each random target (default 10)
    --lock               mlock the memory ballast (needs root or `ulimit -l`)
    --no-nice            don't renice CPU workers to 19
    --cpu-period-ms N    CPU worker duty-cycle period in ms (default 100)
    -q, --quiet          don't print the status line (every 5 s)

How it works:
    Memory: used = MemTotal - MemAvailable (page cache counts as free, like
    `free`'s "used"). The ballast is a list of anonymous mmap chunks, each
    page touched so it is resident, with half-a-chunk hysteresis.
    Shrinking is immediate (burst jobs get resources back within one tick);
    growing is gradual: each tick closes 1 - exp(-interval/ramp) of the
    remaining gap (~63% after --ramp seconds, ~95% after 3x), at least one
    chunk and at most --max-grow chunks per tick.
    CPU: system utilization comes from /proc/stat, the ballast's own share from
    /proc/<pid>/stat of its workers. One worker process per usable CPU spins for
    duty x period and sleeps for the rest. Workers run at nice 19 so real
    workloads preempt them. duty = target - others + I, where `others` is
    EMA-smoothed (jumps of more than 5% of the system are taken instantly) and
    I is a small integral term (+/-0.1) correcting steady-state error. Duty
    decreases immediately and increases with the same --ramp time constant.
    Fluctuation: with --delta D, the memory and CPU targets each get their own
    offset drawn uniformly from [-D, +D] points, held for a random
    0.5x..1.5x --delta-period seconds, then redrawn (independent piecewise-
    constant white noise; effective targets are clamped to 0..100).
    Both the parent and the workers set oom_score_adj=1000 so the OOM killer
    picks the ballast first.

Caveats:
    - Precision: memory +/-1 chunk; CPU +/-a few % (scheduler and measurement
      noise; a smaller --cpu-period-ms gives a finer but noisier duty cycle).
    - Laptops: CPU frequency scaling and thermal throttling change what "25%
      CPU" means. For repeatable tests consider the `performance` governor
      (`powerprofilesctl set performance` or
      `cpupower frequency-set -g performance`).
    - If there's swap, use --lock, or the kernel may swap the memory ballast
      out and hide the pressure.
"""

from __future__ import annotations

import argparse
import ctypes
import math
import mmap
import multiprocessing as mp
import os
import random
import signal
import sys
import time

MiB = 1 << 20
STATUS_EVERY = 5.0


def set_oom_score_adj(value: int = 1000) -> None:
    try:
        with open("/proc/self/oom_score_adj", "w") as f:
            f.write(str(value))
    except OSError:
        pass


def read_meminfo() -> dict[str, int]:
    """Return /proc/meminfo values in bytes."""
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, rest = line.split(":", 1)
            parts = rest.split()
            info[key] = int(parts[0]) * (1024 if len(parts) > 1 else 1)
    return info


def read_proc_stat() -> tuple[int, int, int]:
    """Return (busy_ticks, total_ticks, n_online_cpus) from /proc/stat."""
    busy = total = 0
    ncpu = 0
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu "):
                v = [int(x) for x in line.split()[1:9]]
                # user nice system idle iowait irq softirq steal
                # (guest/guest_nice are already included in user/nice)
                total = sum(v)
                busy = total - (v[3] + v[4])
            elif line.startswith("cpu"):
                ncpu += 1
    return busy, total, max(ncpu, 1)


def read_pid_cpu_ticks(pid: int) -> int:
    """utime + stime of a process in clock ticks (0 if it's gone)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            data = f.read()
    except OSError:
        return 0
    # comm may contain spaces/parens; fields after the last ')' start at field 3
    fields = data[data.rfind(")") + 2 :].split()
    return int(fields[11]) + int(fields[12])  # fields 14, 15


class Jitter:
    """Target that jumps to base + uniform(-delta, delta) at random intervals."""

    def __init__(self, base: float, delta: float, period: float):
        self.base, self.delta, self.period = base, delta, period
        self.value = base
        self.next_change = 0.0

    def get(self, now: float) -> float:
        if self.delta > 0 and now >= self.next_change:
            offset = random.uniform(-self.delta, self.delta)
            self.value = min(100.0, max(0.0, self.base + offset))
            self.next_change = now + self.period * random.uniform(0.5, 1.5)
        return self.value


class MemBallast:
    def __init__(self, chunk: int, lock: bool = False):
        self.chunk = chunk
        self.lock = lock
        self.chunks: list[tuple[mmap.mmap, object]] = []
        self._libc = ctypes.CDLL("libc.so.6", use_errno=True) if lock else None

    @property
    def size(self) -> int:
        return len(self.chunks) * self.chunk

    def _alloc(self) -> None:
        m = mmap.mmap(-1, self.chunk, mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS)
        buf = None
        if self.lock:
            buf = (ctypes.c_char * self.chunk).from_buffer(m)
            if self._libc.mlock(buf, ctypes.c_size_t(self.chunk)) != 0:
                err = ctypes.get_errno()
                del buf
                m.close()
                sys.exit(
                    f"ballast: mlock failed: {os.strerror(err)}. "
                    "Run as root or raise the locked-memory limit (ulimit -l)."
                )
        for off in range(0, self.chunk, mmap.PAGESIZE):
            m[off] = 1
        self.chunks.append((m, buf))

    def _free(self) -> None:
        m, buf = self.chunks.pop()
        del buf  # drop the exported buffer, otherwise close() raises BufferError
        m.close()

    def update(self, pct: float, max_grow: int, frac: float) -> tuple[int, int]:
        """Adjust toward pct of MemTotal. Returns (MemTotal, others) in bytes."""
        info = read_meminfo()
        mem_total = info["MemTotal"]
        used = mem_total - info["MemAvailable"]
        others = max(0, used - self.size)
        want = max(0, pct / 100 * mem_total - others)
        half = self.chunk / 2
        while self.chunks and self.size > want + half:
            self._free()
        # grow a fraction of the gap per tick: at least 1, at most max_grow chunks
        n = min(max_grow, max(1, int((want - self.size) * frac / self.chunk)))
        grown = 0
        while grown < n and self.size + self.chunk <= want + half:
            self._alloc()
            grown += 1
        return mem_total, others

    def release(self) -> None:
        while self.chunks:
            self._free()


def _cpu_worker(duty, stop, period: float, nice: bool) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    set_oom_score_adj()
    if nice:
        try:
            os.nice(19)
        except OSError:
            pass
    clock = time.perf_counter
    while not stop.is_set():
        d = duty.value
        start = clock()
        if d > 0.001:
            end = start + d * period
            while clock() < end:
                pass
        rest = start + period - clock()
        if rest > 0:
            time.sleep(rest)


class CpuBallast:
    def __init__(self, period: float, nice: bool = True):
        self.ncpu = len(os.sched_getaffinity(0))
        self.duty = mp.Value("d", 0.0, lock=False)
        self.stop_event = mp.Event()
        self.workers = [
            mp.Process(
                target=_cpu_worker,
                args=(self.duty, self.stop_event, period, nice),
                name=f"ballast-cpu-{i}",
                daemon=True,
            )
            for i in range(self.ncpu)
        ]

    def start(self) -> None:
        for w in self.workers:
            w.start()

    def set_duty(self, d: float) -> None:
        self.duty.value = d

    def cpu_seconds(self) -> float:
        ticks = sum(read_pid_cpu_ticks(w.pid) for w in self.workers if w.pid)
        return ticks / os.sysconf("SC_CLK_TCK")

    def stop(self) -> None:
        self.duty.value = 0.0
        self.stop_event.set()
        for w in self.workers:
            w.join(timeout=2)
            if w.is_alive():
                w.terminate()
                w.join()


class CpuController:
    """Measures system/ballast CPU and computes the worker duty."""

    EMA_ALPHA = 0.5
    BURST = 0.05  # a rise in others above this skips the EMA
    RAMPING = 0.02  # duty this far below the goal counts as ramping up
    KI = 0.1
    I_MAX = 0.1

    def __init__(self, ballast: CpuBallast, frac: float):
        self.ballast = ballast
        self.target = 0.0
        self.frac = frac
        self.prev_busy, self.prev_total, self.sys_ncpu = read_proc_stat()
        self.prev_ballast = ballast.cpu_seconds()
        self.prev_wall = time.monotonic()
        self.others_ema: float | None = None
        self.integral = 0.0
        self.duty = 0.0
        self.sys_util = 0.0
        self.ballast_util = 0.0

    def update(self, pct: float) -> None:
        self.target = pct / 100
        busy, total, self.sys_ncpu = read_proc_stat()
        bsec = self.ballast.cpu_seconds()
        wall = time.monotonic()
        dtotal, dwall = total - self.prev_total, wall - self.prev_wall
        if dtotal <= 0 or dwall <= 0:
            return
        self.sys_util = (busy - self.prev_busy) / dtotal
        self.ballast_util = (bsec - self.prev_ballast) / (dwall * self.sys_ncpu)
        self.prev_busy, self.prev_total = busy, total
        self.prev_ballast, self.prev_wall = bsec, wall

        others = min(1.0, max(0.0, self.sys_util - self.ballast_util))
        if self.others_ema is None or others > self.others_ema + self.BURST:
            self.others_ema = others  # first sample or burst: react at once
        else:
            a = self.EMA_ALPHA
            self.others_ema = a * others + (1 - a) * self.others_ema

        gap = self.target - self.others_ema
        # workers may only cover a subset of CPUs (affinity); scale accordingly
        scale = self.sys_ncpu / self.ballast.ncpu
        goal = max(0.0, min(1.0, (gap + self.integral) * scale))
        ramping = goal - self.duty > self.RAMPING
        # integral term corrects steady-state error; frozen while saturated or
        # ramping up so it doesn't wind up and overshoot
        if gap <= 0:
            self.integral = min(self.integral, 0.0)
        elif 0.0 < self.duty < 1.0 and not ramping:
            err = self.target - self.sys_util
            self.integral = max(
                -self.I_MAX, min(self.I_MAX, self.integral + self.KI * err)
            )
        # decrease immediately, increase gradually
        if goal <= self.duty:
            self.duty = goal
        else:
            self.duty += (goal - self.duty) * self.frac
        self.ballast.set_duty(self.duty)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="ballast",
        description="Adaptive CPU + memory ballast: keeps total system usage "
        "near a target by filling only the gap left by other processes.",
    )
    p.add_argument(
        "--mem", type=float, metavar="PCT", help="target system memory usage %%"
    )
    p.add_argument(
        "--cpu", type=float, metavar="PCT", help="target system CPU utilization %%"
    )
    p.add_argument(
        "--chunk-mib",
        type=int,
        default=64,
        help="memory chunk size in MiB (default 64)",
    )
    p.add_argument(
        "--interval", type=float, default=0.5, help="control loop seconds (default 0.5)"
    )
    p.add_argument(
        "--max-grow",
        type=int,
        default=8,
        help="max memory chunks added per tick (default 8)",
    )
    p.add_argument(
        "--ramp",
        type=float,
        default=10,
        metavar="S",
        help="growth time constant in seconds; shrinking is always immediate "
        "(default 10, 0 = instant)",
    )
    p.add_argument(
        "--delta",
        type=float,
        default=5,
        metavar="PCT",
        help="random fluctuation of the targets in +/- percentage points "
        "(default 5, 0 = steady)",
    )
    p.add_argument(
        "--delta-period",
        type=float,
        default=10,
        metavar="S",
        help="mean hold time of each random target in seconds (default 10)",
    )
    p.add_argument(
        "--lock",
        action="store_true",
        help="mlock memory ballast (needs root or ulimit -l)",
    )
    p.add_argument(
        "--no-nice", action="store_true", help="don't renice CPU workers to 19"
    )
    p.add_argument(
        "--cpu-period-ms",
        type=float,
        default=100,
        help="CPU duty-cycle period in ms (default 100)",
    )
    p.add_argument("-q", "--quiet", action="store_true", help="no periodic status line")
    args = p.parse_args(argv)
    if args.mem is None and args.cpu is None:
        p.error("at least one of --mem / --cpu is required")
    for name in ("mem", "cpu"):
        v = getattr(args, name)
        if v is not None and not 0 <= v <= 100:
            p.error(f"--{name} must be within 0..100")
    if args.ramp < 0 or args.delta < 0:
        p.error("--ramp and --delta must be >= 0")
    if args.delta_period <= 0:
        p.error("--delta-period must be positive")
    if (
        args.chunk_mib <= 0
        or args.interval <= 0
        or args.max_grow <= 0
        or args.cpu_period_ms <= 0
    ):
        p.error(
            "--chunk-mib, --interval, --max-grow and --cpu-period-ms must be positive"
        )
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    if not (os.path.exists("/proc/meminfo") and os.path.exists("/proc/stat")):
        sys.exit("ballast: /proc not available (Linux only)")

    stopping = False

    def on_signal(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    set_oom_score_adj()
    # fraction of the remaining gap closed per tick when growing
    frac = 1 - math.exp(-args.interval / args.ramp) if args.ramp > 0 else 1.0

    mem = MemBallast(args.chunk_mib * MiB, args.lock) if args.mem is not None else None
    cpu = ctl = None
    if args.cpu is not None:
        cpu = CpuBallast(args.cpu_period_ms / 1000, nice=not args.no_nice)
        cpu.start()
        ctl = CpuController(cpu, frac)
    mem_target = Jitter(args.mem or 0.0, args.delta, args.delta_period)
    cpu_target = Jitter(args.cpu or 0.0, args.delta, args.delta_period)

    if not args.quiet:
        parts = []
        if mem:
            parts.append(
                f"mem target {args.mem:g}% (chunk {args.chunk_mib} MiB{', locked' if args.lock else ''})"
            )
        if cpu:
            parts.append(f"cpu target {args.cpu:g}% ({cpu.ncpu} workers)")
        if args.delta > 0:
            parts.append(f"delta +/-{args.delta:g} every ~{args.delta_period:g}s")
        print(f"ballast: {', '.join(parts)}; Ctrl-C to stop", flush=True)

    next_status = time.monotonic() + STATUS_EVERY
    try:
        while not stopping:
            tick = time.monotonic()
            status = []
            if mem:
                target = mem_target.get(tick)
                total, others = mem.update(target, args.max_grow, frac)
                status.append(
                    f"mem {100 * (others + mem.size) / total:5.1f}% (target {target:4.1f}%) "
                    f"others {others / MiB:7.0f} MiB ballast {mem.size / MiB:6.0f} MiB"
                )
            if ctl:
                ctl.update(cpu_target.get(tick))
                status.append(
                    f"cpu {100 * ctl.sys_util:5.1f}% (target {100 * ctl.target:4.1f}%) "
                    f"others {100 * (ctl.others_ema or 0):5.1f}% duty {100 * ctl.duty:5.1f}%"
                )
            if not args.quiet and tick >= next_status:
                print(time.strftime("%H:%M:%S ") + " | ".join(status), flush=True)
                next_status = tick + STATUS_EVERY
            remaining = args.interval - (time.monotonic() - tick)
            if remaining > 0 and not stopping:
                time.sleep(remaining)
    finally:
        if cpu:
            cpu.stop()
        if mem:
            mem.release()
        if not args.quiet:
            print("ballast: released", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
