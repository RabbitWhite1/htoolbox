import os
import argparse


parser = argparse.ArgumentParser(description="Tmux session starter")
parser.add_argument("-s", "--session", type=str, help="Name of the tmux session")
parser.add_argument("-w", "--window", type=str, help="Name of the tmux window")
parser.add_argument("-p", "--pane", type=int, help="Index of the tmux pane")
parser.add_argument("-n", type=int, default=1, help="Number of new panes to create")
"""
eh = even-horizontal - All panes are arranged side by side, with equal width
ev = even-vertical - All panes are stacked on top of each other, with equal height
mh = main-horizontal - One large pane on top, with smaller panes arranged horizontally below it
mv = main-vertical - One large pane on the left, with smaller panes arranged vertically to the right
t = tiled - All panes are arranged to use the available space as efficiently as possible, with roughly equal size
"""
parser.add_argument("--layout", type=str, default="even-vertical", help="Layout for the tmux panes")
parser.add_argument("--kill", action="store_true", help="Kill existing tmux session with the same name before starting a new one")
args = parser.parse_args()

def start_tmux_session(session_name, window_name=None, pane_index=None, new_panes=1, layout="even-vertical"):
    # Start a new tmux session
    os.system(f"tmux new-session -d -s {session_name}")

    # Create a new window if specified
    if window_name:
        os.system(f"tmux new-window -t {session_name} -n {window_name}")

    # Create new panes if specified
    for i in range(1, new_panes):
        os.system(f"tmux split-window -t {session_name}")
        os.system(f"tmux select-layout -t {session_name} {layout}")

    # Export IID
    for i in range(new_panes):
        os.system(f"tmux send-keys -t {session_name}.{i} 'export IID={i}' C-m")

    # Select the specified pane if provided
    if pane_index is not None:
        os.system(f"tmux select-pane -t {session_name}:{pane_index}")

    # Attach to the tmux session
    os.system(f"tmux attach-session -t {session_name}")

if __name__ == "__main__":
    if args.kill:
        os.system(f"tmux kill-session -t {args.session} 2>&1 >/dev/null")
    if args.n < 1:
        raise ValueError("Number of new panes must be at least 1")

    if args.layout.lower().strip() == "eh":
        layout = "even-horizontal"
    elif args.layout.lower().strip() == "ev":
        layout = "even-vertical"
    elif args.layout.lower().strip() == "mh":
        layout = "main-horizontal"
    elif args.layout.lower().strip() == "mv":
        layout = "main-vertical"
    elif args.layout.lower().strip() == "t":
        layout = "tiled"
    else:
        layout = args.layout

    start_tmux_session(
        session_name=args.session,
        window_name=args.window,
        pane_index=args.pane,
        new_panes=args.n if args.n else 0,
        layout=layout
    )
