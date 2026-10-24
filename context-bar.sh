#!/usr/bin/env bash
# Compatibility entry point. Keep context_statusline.py beside this script.
set -eu
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$script_dir/context_statusline.py" "$@"
