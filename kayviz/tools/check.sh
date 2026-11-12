#!/usr/bin/env bash
# Run kayviz's checks against THIS checkout (works from a git worktree too: the
# editable install in the Lproj env points at the main checkout, PYTHONPATH wins).
#
#   tools/check.sh                 # pytest + npm test
#   tools/check.sh py [pytest args] # only pytest, e.g. tools/check.sh py -k callback -q
#   tools/check.sh js              # only npm test
#   tools/check.sh run file.py ... # run a Python file with this checkout's kayviz
set -euo pipefail
KV="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate Lproj
export PYTHONPATH="$KV/src${PYTHONPATH:+:$PYTHONPATH}"
# own test ports per checkout (tests/test_runtime.py), 300 apart from 20000 on
: "${KAYVIZ_TEST_PORT_BASE:=$(( 20000 + $(printf %s "$KV" | cksum | cut -d" " -f1) % 40 * 300 ))}"
export KAYVIZ_TEST_PORT_BASE

what="${1:-all}"; shift || true
case "$what" in
  py)  (cd "$KV" && python -m pytest "$@") ;;
  js)  (cd "$KV" && npm test --silent) ;;
  run) python "$@" ;;
  all) (cd "$KV" && python -m pytest -q && npm test --silent) ;;
  *)   echo "usage: tools/check.sh [all|py|js|run] [args]" >&2; exit 2 ;;
esac
