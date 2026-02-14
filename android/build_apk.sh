#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-debug}"     # debug|release
DO_CLEAN="${2:-0}"     # 1 to clean

PROG_TOTAL=6
PROG_STEP=0
prog_step() {
  local label="$1"
  PROG_STEP=$((PROG_STEP + 1))
  local width=20
  local filled=$(( PROG_STEP * width / PROG_TOTAL ))
  local empty=$(( width - filled ))
  local bar
  bar="$(printf '%*s' "$filled" '' | tr ' ' '#')"
  local pad
  pad="$(printf '%*s' "$empty" '' | tr ' ' '-')"
  echo "[${PROG_STEP}/${PROG_TOTAL}] [${bar}${pad}] ${label}" >&2
}

if [[ "$MODE" == "setup" ]]; then
  cd "$(dirname "$0")"
  chmod +x ./setup_build_env.sh
  exec ./setup_build_env.sh
fi

ensure_cmd() {
  local cmd="$1"
  local pkg="$2"
  if command -v "$cmd" >/dev/null 2>&1; then
    return 0
  fi
  if [[ "${KIRO2_AUTO_SETUP:-1}" != "1" ]]; then
    echo "Missing required command: $cmd (install package: $pkg)" >&2
    return 1
  fi
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "Missing $cmd and apt-get not found. Install dependencies manually (see android/README_ANDROID.md)." >&2
    return 1
  fi
  if ! command -v sudo >/dev/null 2>&1; then
    echo "Missing $cmd and sudo not found. Install dependencies manually (see android/README_ANDROID.md)." >&2
    return 1
  fi
  echo "Installing missing dependency via apt: $pkg" >&2
  sudo apt-get update
  sudo apt-get install -y "$pkg"
  command -v "$cmd" >/dev/null 2>&1
}

ensure_apt_packages() {
  if [[ "${KIRO2_AUTO_SETUP:-1}" != "1" ]]; then
    return 0
  fi
  if ! command -v apt-get >/dev/null 2>&1 || ! command -v sudo >/dev/null 2>&1; then
    return 0
  fi
  # Only do a full install if key build tools are missing.
  if command -v javac >/dev/null 2>&1 && command -v zip >/dev/null 2>&1 && command -v autoconf >/dev/null 2>&1; then
    return 0
  fi
  echo "Installing Buildozer prerequisites via apt (may prompt for sudo password)..." >&2
  sudo apt-get update
  sudo apt-get install -y \
    python3 python3-dev python3-pip python3-venv git zip unzip openjdk-17-jdk \
    build-essential autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev \
    libtinfo6 cmake libffi-dev libssl-dev \
    libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev libavformat-dev libavcodec-dev
}

prog_step "Checking/Installing system prerequisites"
ensure_apt_packages

prog_step "Checking required commands"
ensure_cmd python3 python3
ensure_cmd pip3 python3-pip
ensure_cmd git git
ensure_cmd zip zip
ensure_cmd unzip unzip
ensure_cmd javac openjdk-17-jdk

cd "$(dirname "$0")"

VENV_DIR="${KIRO2_BUILDOZER_VENV:-.venv_buildozer}"
BUILDOZER="$VENV_DIR/bin/buildozer"
prog_step "Creating/Updating Python venv + Buildozer"
if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating buildozer venv at: $(pwd)/$VENV_DIR" >&2
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install -U pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install -U buildozer "cython<3"

if [[ "$DO_CLEAN" == "1" ]]; then
  prog_step "Cleaning previous Android build"
  "$BUILDOZER" android clean
else
  prog_step "Skipping clean"
fi

prog_step "Running Buildozer ($MODE)"

# Activate the venv to ensure buildozer and its subprocesses find all dependencies.
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Keep output log-friendly (build_apk.bat redirects stdout/stderr to a file).
export NO_COLOR=1
export CLICOLOR=0
export CLICOLOR_FORCE=0
export TERM=dumb

is_broken_hostpython_cache() {
  local pycfg
  pycfg="$(find /tmp/kiro2_buildozer -type f -path "*/other_builds/hostpython3/desktop/hostpython3/native-build/pyconfig.h" 2>/dev/null | head -n 1 || true)"
  [[ -n "$pycfg" ]] || return 1
  grep -q '^/\* #undef SIZEOF_VOID_P \*/$' "$pycfg" || return 1
  grep -q '^/\* #undef HAVE_PTHREAD_H \*/$' "$pycfg" || return 1
}

run_buildozer() {
  case "$MODE" in
    debug)   buildozer -v android debug ;;
    release) buildozer -v android release ;;
    *)
      echo "Unknown mode: $MODE (use debug|release)" >&2
      return 2
      ;;
  esac
}

set +e
run_buildozer
build_rc=$?
set -e

if [[ $build_rc -ne 0 ]] && [[ "$DO_CLEAN" != "1" ]] && is_broken_hostpython_cache; then
  echo "Detected stale hostpython cache from a previous failed configure; cleaning and retrying once..." >&2
  "$BUILDOZER" android clean
  set +e
  run_buildozer
  build_rc=$?
  set -e
fi

if [[ $build_rc -ne 0 ]]; then
  exit "$build_rc"
fi

echo "Done. APK/AAB outputs are typically in: $(pwd)/bin" >&2
