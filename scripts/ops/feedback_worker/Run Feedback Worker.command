#!/bin/bash
# Double-click to run the nightly feedback worker now (same as the 00:30 job).
cd "$(dirname "$0")" && /usr/bin/python3 worker.py
echo; read -n 1 -s -r -p "Done. Press any key to close."
