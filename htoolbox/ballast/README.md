# HToolBox - ballast

Adaptive CPU + memory load generator. Keeps **total system** memory usage and/or
CPU utilization near a target percentage by filling only the gap left by other
processes: the ballast shrinks (down to zero) when the real workload grows, and
grows back when it shrinks.

`ballast.py` is stdlib-only, so it also runs as a standalone file
(`python3 ballast.py ...`), e.g. copied to `/opt/ballast.py` for the systemd unit.

## Usage

```sh
ballast --mem 25 --cpu 25          # both
ballast --mem 25                   # memory only
ballast --cpu 40                   # CPU only
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--mem PCT` | | target system memory usage (`MemTotal - MemAvailable`) |
| `--cpu PCT` | | target system CPU utilization (`/proc/stat`) |
| `--chunk-mib N` | 64 | memory ballast chunk size |
| `--interval S` | 0.5 | control loop period |
| `--max-grow N` | 8 | max memory chunks added per tick (shrinking is unlimited) |
| `--ramp S` | 10 | growth time constant; `0` = instant |
| `--delta PCT` | 5 | random target fluctuation, ± percentage points; `0` = steady |
| `--delta-period S` | 10 | mean hold time of each random target |
| `--lock` | off | `mlock` the memory ballast (needs root or `ulimit -l`) |
| `--no-nice` | off | don't renice CPU workers to 19 |
| `--cpu-period-ms N` | 100 | CPU worker duty-cycle period |
| `-q, --quiet` | off | no status line (printed every 5 s otherwise) |

Status line: `mem <system%> (target <current%>) others <MiB> ballast <MiB> | cpu <system%> (target <current%>) others <%> duty <%>`.

## Shrink fast, grow gently

Shrinking is immediate: memory chunks are freed and the CPU duty drops within one
tick (0.5 s) when other processes need more. Growing is gradual: each tick closes
`1 - exp(-interval/ramp)` of the remaining gap, so with the default `--ramp 10`
the ballast refills about 63% of the gap in 10 s and about 95% in 30 s. This
leaves headroom for burst jobs that come back soon after they finish. Use
`--ramp 0` for the old instant behaviour.

## Fluctuation

By default the targets wander: memory and CPU each get an independent offset drawn
uniformly from `[-delta, +delta]` points, held for a random 0.5–1.5 × `--delta-period`
seconds, then redrawn. `--mem 25 --cpu 25` therefore moves irregularly within
20–30%. Steps up follow `--ramp`; steps down apply immediately. Use `--delta 0`
for steady targets.

With several instances running, each one draws its own targets, so the combined
total follows whichever instance currently has the highest target.

## As a service

See [`mem-ballast.service`](mem-ballast.service):

```sh
sudo cp ballast.py /opt/ballast.py
sudo cp mem-ballast.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now mem-ballast
```

## Caveats

- Precision: memory ±1 chunk; CPU ±a few % (a smaller `--cpu-period-ms` gives a
  finer but noisier duty cycle).
- Laptops: frequency scaling and thermal throttling change what "25% CPU" means.
  For repeatable tests use the `performance` governor
  (`powerprofilesctl set performance` or `cpupower frequency-set -g performance`).
- With swap enabled, use `--lock`, or the kernel may swap the ballast out and hide
  the pressure.
- The ballast sets `oom_score_adj=1000`, so the OOM killer picks it first.
