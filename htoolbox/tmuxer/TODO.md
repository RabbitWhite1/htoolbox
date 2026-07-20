# tmuxer TODO

## Decouple layout from commands in the config

Consider splitting the config into a structural section (windows/panes/layout) and a
behavioral section (commands to run), instead of nesting commands inside the pane/window
declaration.

### Rationale

- **The runtime already does this.** Execution is already two passes: phase 2 "Build
  session, windows, panes", phase 3 "Run commands". Nesting commands into the pane
  declaration hides a separation the engine already makes; decoupling makes the config
  mirror execution.
- **Global execution ordering.** Today command order is scoped per-window (windows
  top-to-bottom, batches within each). Lifting commands into a flat, ordered top-level
  `run` list keyed by `(window, pane)` makes that ordering *global*. Combined with the
  existing `use_sentinel` wait mechanism, this unlocks **cross-window sequencing** —
  e.g. "wait for the DB in window B before starting the app in window A" — which the
  nested form cannot express (ordering can't cross a window boundary). This is the
  natural completion of the sentinel idea.
- **Reuse.** A layout could be reused with different `run` scripts, or vice versa.
- Structural block stays small and scannable.

### Sketch

```yaml
session: devbox
kill: true
focus_window: 0

# --- structure: scannable skeleton ---
windows:
  - window: workspace
    num_panes: 3
    layout: ev
    focus_pane: 0
  - window: monitoring
    num_panes: 2
    layout: tiled

# --- behavior: one ordered script across the whole session ---
run:
  - { window: workspace,  pane_indices: "0", commands: [ssh omen-ubuntu, exit] }
  - { window: monitoring, pane_indices: "1", commands: [wait-for-db] }   # blocks via sentinel
  - { window: workspace,  pane_indices: "2", commands: [start-app] }     # runs after db is up
```

### Costs / open questions

- **Locality.** For the common case (one window, panes each running a couple lines),
  nesting is more readable — everything about a pane sits in one place. Decoupling forces
  looking in two sections.
- **Dangling references.** `run` entries reference windows by name/index → new error class
  (referencing a window that doesn't exist). Pane-index ranges are already validated; add
  window-existence checks.
- **Addressability.** Windows must be nameable, or referenced by list index if unnamed.
- **Do NOT support both nested and top-level `run`.** Two ways to express the same thing is
  the kind of mess this is trying to escape.

### Decision gate

Worth doing *if* cross-window/global sequencing or layout reuse is actually reached for in
practice. If configs are mostly single-window or per-window-independent, the locality cost
outweighs it — keep nesting.

## Notes (not pursuing)

- `pane_indices` being specifiable in multiple batches is **intentional** — it maintains
  per-pane execution order via ordered batches. Not a wart.
