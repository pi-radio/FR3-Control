#!/bin/bash
# Runs the GUI directly from source (main.py) via the venv's Python,
# rather than the packaged executable - for quick testing without a full
# PyInstaller build. Run from anywhere - it cd's to its own location
# first. For Linux ARM64 (Jetson-class boards).

cd "$(dirname "$0")"

./venv/bin/python3 main.py
