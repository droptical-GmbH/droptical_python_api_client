#!/bin/bash

echo "======================================================="
echo "DropticalAPI GUI Build Script for macOS/Linux"
echo "======================================================="

# Exit immediately if a command exits with a non-zero status.
set -e

# Name of the virtual environment
VENV_DIR="../../.venv"

# Check if Python 3 is available
if ! command -v python3 &> /dev/null
then
    echo "Error: python3 not found. Please install Python 3."
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in '$VENV_DIR'..."
    python3 -m venv $VENV_DIR
fi

echo "Activating virtual environment..."
source $VENV_DIR/bin/activate

echo "Installing dependencies from pyproject.toml..."
pip install '../../.[gui]'

echo "Starting PyInstaller build..."
pyinstaller --noconfirm --clean dropticalGUI.spec

echo "======================================================="
echo "Build completed!"
echo "The finished application can be found in the 'dist' folder."
echo "======================================================="
