#!/usr/bin/env bash
set -euo pipefail

echo "Setting up Buildozer prerequisites (Ubuntu/Debian)..." >&2

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo not found. Install packages manually (see android/README_ANDROID.md)." >&2
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "apt-get not found. This script supports Ubuntu/Debian. Install prerequisites manually." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y \
  python3 python3-pip python3-venv git zip unzip openjdk-17-jdk \
  build-essential autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev \
  libtinfo6 cmake libffi-dev libssl-dev

cd "$(dirname "$0")"
python3 -m venv .venv_buildozer
./.venv_buildozer/bin/python -m pip install -U pip setuptools wheel
./.venv_buildozer/bin/python -m pip install -U buildozer cython

echo "NOTE: Buildozer will download Android SDK/NDK on first build." >&2
echo "Setup complete. You can now run: ./build_apk.sh debug" >&2
