#!/bin/bash
# Install git hooks by pointing core.hooksPath at the tracked .githooks/ dir.
# Run once after cloning: bash scripts/install_git_hooks.sh
#
# Why: .git/hooks/* is not tracked by git, so any local fix (e.g. forcing
# `python` to resolve to .venv/Scripts/python.exe instead of mingw python)
# vanishes on a fresh clone. Tracking the hook in .githooks/ + setting
# core.hooksPath makes the hook portable across machines.

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

if [ ! -d ".githooks" ]; then
    echo "❌ .githooks/ not found in repo root"
    exit 1
fi

git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true

# Remove legacy .git/hooks/* that share names with .githooks/* — they would
# silently take over if someone later runs `git config --unset core.hooksPath`,
# leading to two divergent copies of the same hook on different machines.
LEGACY_REMOVED=0
for f in .githooks/*; do
    name="$(basename "$f")"
    legacy=".git/hooks/$name"
    if [ -f "$legacy" ]; then
        rm -f "$legacy"
        LEGACY_REMOVED=$((LEGACY_REMOVED + 1))
        echo "  removed legacy $legacy (now tracked in .githooks/$name)"
    fi
done

echo "✅ git hooks installed via core.hooksPath=.githooks"
if [ "$LEGACY_REMOVED" -gt 0 ]; then
    echo "   ($LEGACY_REMOVED legacy .git/hooks/* removed to avoid divergence)"
fi
echo ""
echo "Active hooks:"
ls -1 .githooks/
