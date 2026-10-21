#!/usr/bin/env bash
# Converts the guide(s) in docs/ to docs/md/*.md + docs/md/INDEX.txt
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/.venv/bin/activate" ] && source "$ROOT/.venv/bin/activate"
python3 "$ROOT/tools/docx_to_md.py"
