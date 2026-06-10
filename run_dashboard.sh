#!/usr/bin/env fish
set SCRIPT_DIR (dirname (status --current-filename))
source $SCRIPT_DIR/entel-dashboard/.venv/bin/activate.fish
python $SCRIPT_DIR/entel-dashboard/main.py
