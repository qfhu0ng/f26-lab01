#!/usr/bin/env python3
"""Export one Codex task's completed visible history, never its private state.

Uses the local JSONL layout observed in Codex, not a documented export API.
Only session JSONL files are read: no auth, config, memory, or unrelated tasks.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


TOOL_TYPES = {
    'function_call', 'function_call_output',
    'custom_tool_call', 'custom_tool_call_output',
}
VISIBLE_FIELDS = {
    'type', 'role', 'content', 'id', 'phase', 'channel', 'call_id',
    'name', 'namespace', 'arguments', 'input', 'output', 'status',
}


def timestamp(record):
    return datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00'))


def read_records(source):
    """Read a snapshot, tolerating only an unfinished final JSONL record."""
    records, warnings = [], []
    lines = source.read_bytes().splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            if index == len(lines) - 1 and not line.endswith(b'\n'):
                warnings.append(f'{source.name}: unfinished final JSONL record omitted.')
                continue
            raise ValueError(f'{source.name}: invalid JSONL at line {index + 1}.') from error
        records.append(record)
    return records, warnings


def visible_record(record, cutoff):
    if record.get('type') != 'response_item' or timestamp(record) > cutoff:
        return None
    item = record.get('payload', {})
    if item.get('type') == 'message':
        if item.get('role') not in {'user', 'assistant'}:
            return None
        if item.get('channel') not in {None, 'commentary', 'final'}:
            return None
    elif item.get('type') not in TOOL_TYPES:
        return None
    return {
        'timestamp': record['timestamp'], 'type': 'response_item',
        'payload': {key: value for key, value in item.items() if key in VISIBLE_FIELDS},
    }


def fenced(value, language='text'):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    longest = max((len(match.group()) for match in re.finditer(r'`+', text)), default=0)
    fence = '`' * max(3, longest + 1)
    return f'{fence}{language}\n{text}\n{fence}\n'


def render_markdown(events, session_id, cutoff):
    parts = [
        '# Lab 1 — Codex conversation transcript\n',
        f'Task: `{session_id}`  \nCompleted-turn cutoff (UTC): `{cutoff}`\n',
        'Saved visible messages and tool actions, not a summary. The current unfinished '
        'turn is excluded. Internal instructions, private reasoning, and opaque metadata '
        'are omitted. Content and any truncation already in saved outputs are preserved. '
        'Non-text message parts remain represented in JSON.\n',
    ]
    for number, event in enumerate(events, 1):
        item = event['payload']
        kind = item['type']
        label = item.get('role', kind)
        parts.append(f'## {number}. {label} — {event["timestamp"]}\n')
        if channel := item.get('channel'):
            parts.append(f'Channel: `{channel}`\n')
        if kind == 'message':
            content = item.get('content', [])
            if isinstance(content, str):
                parts.append(fenced(content))
            else:
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get('text'), str):
                        parts.append(fenced(part['text']))
                    else:
                        parts.append(fenced(part, 'json'))
        elif kind in {'function_call', 'custom_tool_call'}:
            parts.append(f'Tool: `{item.get("name", "")}`  \nCall ID: `{item.get("call_id", "")}`\n')
            parts.append(fenced(item.get('arguments', item.get('input', ''))))
        else:
            parts.append(f'Call ID: `{item.get("call_id", "")}`\n')
            parts.append(fenced(item.get('output', '')))
    return '\n'.join(parts)


def export_session(repo, codex_home, session_id):
    # Validate before using the explicit task ID in filename matching.
    UUID(session_id)
    sources = sorted((codex_home / 'sessions').glob(f'**/*{session_id}*.jsonl'))
    if not sources:
        raise ValueError('No saved session JSONL files found for the selected task.')

    segments, warnings = [], []
    for source in sources:
        records, partial_warnings = read_records(source)
        meta = next((r.get('payload', {}) for r in records
                     if r.get('type') == 'session_meta'), {})
        if meta.get('id') != session_id:
            raise ValueError(f'{source.name}: session ID does not match; nothing exported.')
        segments.append((source, records))
        warnings.extend(partial_warnings)

    completed = [r for _, records in segments for r in records
                 if r.get('type') == 'event_msg'
                 and r.get('payload', {}).get('type') == 'task_complete']
    if not completed:
        raise ValueError('No completed turn found; the previous export is unchanged.')
    cutoff_record = max(completed, key=timestamp)
    cutoff = timestamp(cutoff_record)
    cutoff_text = cutoff_record['timestamp']

    files, jsonl_events, events = {}, {}, []
    for source, records in segments:
        selected = [event for record in records
                    if (event := visible_record(record, cutoff)) is not None]
        if not selected:
            continue
        name = f'{source.stem}.visible.jsonl'
        jsonl_events[name] = selected
        files[name] = ''.join(json.dumps(event, ensure_ascii=False) + '\n'
                              for event in selected)
        events.extend(selected)
    if not events:
        raise ValueError('No visible completed history found; the previous export is unchanged.')
    events.sort(key=timestamp)
    files['CODEX_TRANSCRIPT.md'] = render_markdown(events, session_id, cutoff_text)
    counts = Counter(e['payload'].get('role', e['payload']['type']) for e in events)

    notes = [
        '# Local transcript export\n',
        f'Exported at (UTC): `{datetime.now(timezone.utc).isoformat()}`  \n'
        f'Task: `{session_id}`  \nCompleted-turn cutoff (UTC): `{cutoff_text}`\n',
        '**Keep these files local. Do not commit or push Lab 1 transcripts.**\n',
        '## Files\n',
        '- `CODEX_TRANSCRIPT.md`: chronological readable transcript.\n',
    ]
    notes.extend(f'- `{name}`: {len(selected)} visible events.\n'
                 for name, selected in jsonl_events.items())
    notes.extend([
        '\n## Scope\n',
        'Includes saved user prompts, assistant replies, tool calls, and tool results '
        'through the last completed turn, across all matching session segments. '
        'Only the explicitly selected task is exported, including any earlier discussion '
        'in that task. No unrelated tasks, memory directories, config, or auth files are copied. '
        'System/developer instruction records, private reasoning, and opaque internal metadata '
        'are excluded. Visible message content is not rewritten. Images and other non-text '
        'message parts remain represented in JSON; external media files are not copied. '
        'Existing output truncation is preserved. The current unfinished turn is excluded. '
        'This is a snapshot, not a live export or a byte-for-byte copy of internal state.\n',
        '## Regenerate\n',
        f'From the repository root: `./tools/export-transcripts.sh --codex --session {session_id}`. '
        'Inside Codex, omit `--session` to use `CODEX_THREAD_ID`. '
        'The exporter replaces its existing output files and removes obsolete visible JSONL '
        'exports for this task only. Other files are left alone.\n',
        '## Format reference\n',
        '[Official OpenAI documentation](https://learn.chatgpt.com/docs/config-file/'
        'environment-variables#core-locations) documents `CODEX_HOME` (default `~/.codex`). '
        'The JSONL adapter is based on the local saved-log layout, not a documented export API.\n',
    ])
    if warnings:
        notes.append('## Read warnings\n')
        notes.extend(f'- {warning}\n' for warning in warnings)
    files['EXPORT_NOTES.md'] = '\n'.join(notes)

    dest = repo / 'transcripts'
    if dest.is_symlink():
        raise ValueError('Refusing to write through a symlinked transcripts directory.')
    dest.mkdir(exist_ok=True, mode=0o700)
    stale = [p for p in dest.glob(f'*{session_id}*.visible.jsonl') if p.name not in files]
    # Stage the new files first so parsing/writing failures do not destroy the old export.
    with tempfile.TemporaryDirectory(prefix='.codex-export-', dir=dest) as directory:
        staging = Path(directory)
        for name, content in files.items():
            path = staging / name
            path.write_text(content, encoding='utf-8')
            path.chmod(0o600)
        for name, expected in jsonl_events.items():
            actual = [json.loads(line) for line in (staging / name).read_text(encoding='utf-8').splitlines()]
            if actual != expected:
                raise ValueError('Export round-trip verification failed; previous export unchanged.')
        for name in files:
            os.replace(staging / name, dest / name)
        for path in stale:
            path.unlink()

    return {'cutoff': cutoff_text, 'counts': dict(counts), 'segments': len(jsonl_events),
            'files': sorted(files), 'warnings': warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', required=True, type=Path)
    parser.add_argument('--session', default=os.environ.get('CODEX_THREAD_ID'),
                        help='Exact Codex task ID; defaults to CODEX_THREAD_ID.')
    args = parser.parse_args()
    if not args.session:
        parser.error('Pass --session TASK_ID when running outside Codex.')
    home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser()
    try:
        result = export_session(args.repo_root, home, args.session)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'error: {error}\n')
    print(f'Exported {result["segments"]} session segment(s).')
    print(f'Completed-turn cutoff (UTC): {result["cutoff"]}')
    print('Visible-event counts:', json.dumps(result['counts'], sort_keys=True))
    for warning in result['warnings']:
        print(f'Warning: {warning}', file=sys.stderr)
    print('Transcript:', args.repo_root / 'transcripts' / 'CODEX_TRANSCRIPT.md')
    print('Replaced previous generated files; source session logs were not modified.')
    print('Keep transcripts local. Do not commit or push them for Lab 1.')


if __name__ == '__main__':
    main()
