#!/usr/bin/env fish
set SCRIPT_DIR (dirname (status --current-filename))
source $SCRIPT_DIR/scripts/.venv/bin/activate.fish
python $SCRIPT_DIR/scripts/simulate_data.py $argv
