#!/usr/bin/env bash
# Export agent sessions into the local, Git-ignored transcripts/ directory.
# Codex is the default. Claude Code remains available with --claude.
# For this public Lab 1 fork, NEVER commit or push the transcripts.
#
# Usage (from anywhere inside your course repository):
#   ./tools/export-transcripts.sh --codex --session <task-id>
#   ./tools/export-transcripts.sh          # uses CODEX_THREAD_ID inside Codex
#   ./tools/export-transcripts.sh --claude
#
# Notes:
#   - Codex export requires Python 3.9+ and uses only the selected task's
#     saved session logs; it excludes the current unfinished turn.
#   - A rerun replaces the selected task's previous exported snapshot.
#   - Windows: run this from Git Bash or WSL.
#   - Sessions are stored on the machine where you ran the agent. If you
#     worked on more than one machine, run this script on each of them.
#   - Claude mode selects sessions started inside this repository.
#   - Review the exported files for accidentally personal content before
#     showing them locally to your TA.
#
# INVARIANT for anyone revising this script: it exports session logs ONLY,
# never the memory/ directory that lives alongside them (auto-memory can
# hold personal context that has no business in a graded repo). The
# top-level *.jsonl glob below guarantees this today; do not replace it
# with a recursive copy.

set -euo pipefail

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    echo "Usage: $0 [--codex] [--session TASK_ID]"
    echo "       $0 --claude"
    echo "Codex uses CODEX_THREAD_ID when --session is omitted. Requires Python 3.9+."
    echo "Transcripts stay local: do not commit or push them for Lab 1."
    exit 0
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "error: this is not a git repository. Run the script from inside your course repository." >&2
    exit 1
}

if [ "${1:-}" != "--claude" ]; then
    if [ "${1:-}" = "--codex" ]; then
        shift
    fi
    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    exec python3 "$SCRIPT_DIR/export-codex-transcripts.py" --repo-root "$REPO_ROOT" "$@"
fi
shift
if [ "$#" -ne 0 ]; then
    echo "error: --claude does not accept additional arguments." >&2
    exit 1
fi

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
PROJECTS_DIR="$CLAUDE_DIR/projects"
if [ ! -d "$PROJECTS_DIR" ]; then
    echo "error: $PROJECTS_DIR not found." >&2
    echo "Claude Code stores its sessions there. Have you run Claude Code on this machine?" >&2
    exit 1
fi

# Claude Code names each folder under projects/ after the directory the
# session started in, with every non-alphanumeric character replaced by "-".
ENCODED="$(printf '%s\n' "$REPO_ROOT" | sed 's/[^A-Za-z0-9]/-/g')"

DEST="$REPO_ROOT/transcripts"
mkdir -p "$DEST"

copied=0
skipped=0

# copy_session <session-jsonl>: copies the session file plus its companion
# directory (subagent transcripts), preserving names.
copy_session() {
    f="$1"
    cp -p "$f" "$DEST/"
    companion="${f%.jsonl}"
    if [ -d "$companion" ]; then
        # Replace any previous export of this session's directory, otherwise
        # cp would nest the new copy inside the old one on a re-run.
        companion_dest="$DEST/$(basename "$companion")"
        rm -rf "$companion_dest"
        cp -Rp "$companion" "$companion_dest"
    fi
    copied=$((copied + 1))
}

for dir in "$PROJECTS_DIR/$ENCODED" "$PROJECTS_DIR/$ENCODED"-*; do
    [ -d "$dir" ] || continue
    for f in "$dir"/*.jsonl; do
        [ -f "$f" ] || continue
        if [ "$dir" = "$PROJECTS_DIR/$ENCODED" ]; then
            # Folder name matches the repository root exactly: always ours.
            copy_session "$f"
        elif grep -q -m 1 -F -e "\"cwd\":\"$REPO_ROOT\"" -e "\"cwd\":\"$REPO_ROOT/" "$f"; then
            # Folder name only starts with our name (a session started in a
            # subdirectory), which can collide with a sibling directory like
            # repo-extra/. The recorded working directory settles it.
            copy_session "$f"
        else
            skipped=$((skipped + 1))
        fi
    done
done

if [ "$copied" -eq 0 ]; then
    echo "No Claude Code sessions found for $REPO_ROOT."
    echo "Sessions are recorded per starting directory: start Claude Code inside the repository and try again."
    if [ "$skipped" -gt 0 ]; then
        echo "(Skipped $skipped session file(s) that ran in other directories.)"
    fi
    exit 1
fi

echo "Exported $copied session(s) to transcripts/ ($(du -sh "$DEST" | cut -f1) total)."
if [ "$skipped" -gt 0 ]; then
    echo "Skipped $skipped session file(s) that ran in other directories."
fi
echo
echo "Next steps:"
echo "  1. Skim the exported files for anything accidentally personal (see policies.md)."
echo "  2. Show the local exported files to your TA at recitation."
echo "Do not commit or push transcripts for this public Lab 1 fork."
