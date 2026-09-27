#!/usr/bin/env bash
# Create backend/.venv as a symlink to a folder outside iCloud-synced directories, then sync.
#
# Why: macOS "Desktop & Documents" iCloud sync marks everything inside dot-folders (like
# .venv) as hidden, and Python 3.13 skips hidden .pth files, which silently breaks the
# editable install of `signals`. Keeping the venv under ~/.cache avoids it. Safe to re-run;
# every checkout/worktree gets its own venv (keyed by its absolute path).
set -euo pipefail
cd "$(dirname "$0")/../backend"
target="${SIGNALS_VENV_HOME:-$HOME/.cache/signals-venvs}/$(pwd -P | shasum | cut -c1-12)"
if [ ! -L .venv ]; then
  rm -rf .venv
  mkdir -p "$target"
  ln -s "$target" .venv
fi
uv sync
