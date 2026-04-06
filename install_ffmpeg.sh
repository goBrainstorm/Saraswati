#!/usr/bin/env bash
set -euo pipefail

if command -v ffmpeg &>/dev/null; then
    echo "ffmpeg is already installed: $(ffmpeg -version 2>&1 | head -1)"
    exit 0
fi

if command -v apt-get &>/dev/null; then
    sudo apt-get update && sudo apt-get install -y ffmpeg
elif command -v pacman &>/dev/null; then
    sudo pacman -S --noconfirm ffmpeg
elif command -v brew &>/dev/null; then
    brew install ffmpeg
elif command -v dnf &>/dev/null; then
    sudo dnf install -y ffmpeg
else
    echo "No supported package manager found. Install ffmpeg manually: https://ffmpeg.org/download.html"
    exit 1
fi

echo "ffmpeg installed: $(ffmpeg -version 2>&1 | head -1)"
