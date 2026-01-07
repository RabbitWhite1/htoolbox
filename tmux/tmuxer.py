import os
import argparse
import sys


def start_tmux_session(session_name, window_name=None, pane_index=None, new_panes=1, layout="even-vertical"):
    """Start and attach to a tmux session.

    This function uses the `tmux` command-line tool. It is designed to be
    called from the CLI entry point `main()` below, but can also be imported
    and used programmatically.
    """
    # Start a new tmux session detached
    os.system(f"tmux new-session -d -s {session_name}")

    # Create a new window if specified
    if window_name:
        os.system(f"tmux new-window -t {session_name} -n {window_name}")

    # Create new panes if specified
    for i in range(1, new_panes):
        os.system(f"tmux split-window -t {session_name}")
        os.system(f"tmux select-layout -t {session_name} {layout}")

    # Export IID environment variable into each pane
    for i in range(new_panes):
        os.system(f"tmux send-keys -t {session_name}.{i} 'export IID={i}' C-m")

    # Select the specified pane if provided
    if pane_index is not None:
        os.system(f"tmux select-pane -t {session_name}:{pane_index}")

    # Attach to the tmux session
    os.system(f"tmux attach-session -t {session_name}")


def _normalize_layout(layout_arg: str) -> str:
    v = layout_arg.lower().strip()
    if v == "eh":
        return "even-horizontal"
    if v == "ev":
        return "even-vertical"
    if v == "mh":
        return "main-horizontal"
    if v == "mv":
        return "main-vertical"
    if v == "t":
        return "tiled"
    return layout_arg


def main():
    """Console entry point for the `tmuxer` command.

    Accepts an optional argv list (for testing). Returns 0 on success, may
    raise exceptions for misuse.
    """
    parser = argparse.ArgumentParser(description="Tmux session starter")
    parser.add_argument("-n", "--num_panes", type=int, required=True, help="Number of new panes to create")
    parser.add_argument("-s", "--session", type=str, required=True, help="Name of the tmux session")
    parser.add_argument("-w", "--window", type=str, help="Name of the tmux window")
    parser.add_argument("-p", "--pane", type=int, help="Index of the tmux pane")
    parser.add_argument("--layout", type=str, default="even-vertical", help="Layout for the tmux panes")
    parser.add_argument(
        "--kill", action="store_true", help="Kill existing tmux session with the same name before starting a new one"
    )

    args = parser.parse_args()

    if args.kill and args.session:
        # Prefer to silence output from tmux kill-session
        os.system(f"tmux kill-session -t {args.session} >/dev/null 2>&1")

    if args.num_panes < 1:
        raise ValueError("Number of new panes must be at least 1")

    layout = _normalize_layout(args.layout)

    # If session name is not provided, let tmux create a session with default name
    start_tmux_session(
        session_name=args.session,
        window_name=args.window,
        pane_index=args.pane,
        new_panes=args.num_panes,
        layout=layout,
    )


if __name__ == "__main__":
    main()
