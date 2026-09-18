#!/bin/bash
# Rebuilds the packaged FR3-Board-Control executable from source
# (fr3_gui.spec), picking up any changes to the Python code or bundled
# data files (e.g. data/lo_suppression.csv, data/am3153_sparams). Run from
# anywhere - it cd's to its own location first. For Linux ARM64
# (Jetson-class boards) - see build_windows.bat for the Windows
# equivalent, and PACKAGING.md for one-time venv/system setup.

cd "$(dirname "$0")"

./venv/bin/python3 -m PyInstaller fr3_gui.spec --noconfirm
if [ $? -ne 0 ]; then
    echo
    echo "Build FAILED."
    exit 1
fi

echo
echo "Build succeeded: dist/FR3-Board-Control/FR3-Board-Control"
