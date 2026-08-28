"""Run with: python3 -B -m unittest discover -s tools -p 'test_export_*.py' -v."""

import importlib.util
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('export_codex', TOOLS / 'export-codex-transcripts.py')
EXPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORTER)
SESSION = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'


def event(kind, payload, second=1):
    return {'timestamp': f'2026-08-28T00:00:{second:02d}.000Z',
            'type': kind, 'payload': payload}


def message(role, text, second=1, **extra):
    return event('response_item', {'type': 'message', 'role': role,
                                 'content': [{'type': 'input_text', 'text': text}], **extra}, second)


def complete(second=10):
    return event('event_msg', {'type': 'task_complete'}, second)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo with spaces'
        self.repo.mkdir()
        self.home = self.root / 'codex'
        self.logs = self.home / 'sessions' / '2026' / '08' / '28'
        self.logs.mkdir(parents=True)

    def write_session(self, records, suffix='', session=SESSION):
        path = self.logs / f'rollout-{session}{suffix}.jsonl'
        records = [event('session_meta', {'id': session, 'cwd': str(self.repo.parent)}, 0), *records]
        path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records), encoding='utf-8')
        return path

    def export(self):
        return EXPORTER.export_session(self.repo, self.home, SESSION)

    def read_events(self):
        return [json.loads(line) for path in sorted((self.repo / 'transcripts').glob('*.visible.jsonl'))
                for line in path.read_text(encoding='utf-8').splitlines()]

    def test_preserves_visible_content_and_excludes_private_records(self):
        records = [
            message('user', '请解释 ```java\nexample\n```'),
            message('assistant', 'Visible reply.', 2, channel='final', encrypted_content='OPAQUE'),
            message('system', 'SYSTEM_SECRET'),
            message('developer', 'DEVELOPER_SECRET'),
            message('assistant', 'PRIVATE_REASONING', channel='analysis'),
            event('response_item', {'type': 'reasoning', 'summary': 'HIDDEN'}),
        ]
        for kind, field in [('function_call', 'arguments'), ('custom_tool_call', 'input'),
                            ('function_call_output', 'output'), ('custom_tool_call_output', 'output')]:
            records.append(event('response_item', {'type': kind, 'name': 'example',
                                                 'call_id': kind, field: 'verbatim\ncontent'}, 3))
        self.write_session([*records, complete()])
        result = self.export()
        exported = self.read_events()
        self.assertEqual(len(exported), 6)
        self.assertEqual(exported[0]['payload']['content'], records[0]['payload']['content'])
        self.assertEqual(result['counts']['user'], 1)
        text = (self.repo / 'transcripts' / 'CODEX_TRANSCRIPT.md').read_text(encoding='utf-8')
        for hidden in ['SYSTEM_SECRET', 'DEVELOPER_SECRET', 'PRIVATE_REASONING', 'HIDDEN', 'OPAQUE']:
            self.assertNotIn(hidden, text + json.dumps(exported))
        self.assertIn('````text\n请解释 ```java', text)
        self.assertIn('verbatim\ncontent', text)

    def test_combines_segments_in_chronological_order_and_omits_active_turn(self):
        self.write_session([message('assistant', 'SECOND', 5), complete(),
                            message('user', 'ACTIVE', 11)], suffix='-a')
        self.write_session([message('user', 'FIRST', 1)], suffix='-z')
        self.assertEqual(self.export()['segments'], 2)
        text = (self.repo / 'transcripts' / 'CODEX_TRANSCRIPT.md').read_text()
        self.assertLess(text.index('FIRST'), text.index('SECOND'))
        self.assertNotIn('ACTIVE', text)

    def test_ignores_unrelated_tasks_and_memory(self):
        self.write_session([message('user', 'selected'), complete()])
        self.write_session([message('user', 'UNRELATED'), complete()], session=OTHER)
        memory = self.home / 'memory'
        memory.mkdir()
        (memory / f'{SESSION}.jsonl').write_text('PERSONAL_MEMORY')
        self.assertEqual(self.export()['segments'], 1)
        text = (self.repo / 'transcripts' / 'CODEX_TRANSCRIPT.md').read_text()
        self.assertNotIn('UNRELATED', text)
        self.assertNotIn('PERSONAL_MEMORY', text)

    def test_replaces_old_export_and_removes_only_selected_task_stale_files(self):
        source = self.write_session([message('user', 'old'), complete()])
        self.export()
        dest = self.repo / 'transcripts'
        stale = dest / f'rollout-old-{SESSION}.visible.jsonl'
        stale.write_text('old export')
        unrelated = dest / f'rollout-{OTHER}.visible.jsonl'
        unrelated.write_text('other task')
        note = dest / 'personal-note.md'
        note.write_text('keep')
        self.write_session([message('user', 'updated'), complete()])
        before = source.read_bytes()
        self.export()
        self.assertFalse(stale.exists())
        self.assertEqual(unrelated.read_text(), 'other task')
        self.assertEqual(note.read_text(), 'keep')
        self.assertEqual(source.read_bytes(), before)
        self.assertIn('updated', (dest / 'CODEX_TRANSCRIPT.md').read_text())
        self.assertFalse(list(dest.glob('.codex-export-*')))

    def test_incomplete_tail_is_reported_but_completed_history_exports(self):
        source = self.write_session([message('user', 'saved'), complete()])
        with source.open('ab') as stream:
            stream.write(b'{"partial":')
        result = self.export()
        self.assertEqual(len(result['warnings']), 1)
        self.assertIn('unfinished final JSONL', (self.repo / 'transcripts' / 'EXPORT_NOTES.md').read_text())

    def test_malformed_complete_line_keeps_previous_export(self):
        source = self.write_session([message('user', 'saved'), complete()])
        self.export()
        old = (self.repo / 'transcripts' / 'CODEX_TRANSCRIPT.md').read_bytes()
        with source.open('a') as stream:
            stream.write('not json\n')
        with self.assertRaisesRegex(ValueError, 'invalid JSONL'):
            self.export()
        self.assertEqual((self.repo / 'transcripts' / 'CODEX_TRANSCRIPT.md').read_bytes(), old)

    def test_missing_or_unfinished_task_does_not_create_export(self):
        with self.assertRaisesRegex(ValueError, 'No saved session'):
            self.export()
        self.write_session([message('user', 'unfinished')])
        with self.assertRaisesRegex(ValueError, 'No completed turn'):
            self.export()
        self.assertFalse((self.repo / 'transcripts').exists())

    def test_mismatched_session_metadata_is_rejected(self):
        path = self.write_session([message('user', 'wrong session'), complete()], session=OTHER)
        path.rename(path.with_name(f'rollout-{SESSION}.jsonl'))
        with self.assertRaisesRegex(ValueError, 'session ID does not match'):
            self.export()
        self.assertFalse((self.repo / 'transcripts').exists())

    def test_non_text_message_parts_are_preserved(self):
        image = {'type': 'input_image', 'image_url': 'data:image/png;base64,example'}
        self.write_session([event('response_item', {'type': 'message', 'role': 'user',
                                                  'content': [image]}), complete()])
        self.export()
        self.assertEqual(self.read_events()[0]['payload']['content'], [image])
        self.assertIn('data:image/png;base64,example', (self.repo / 'transcripts' / 'CODEX_TRANSCRIPT.md').read_text())

    def test_symlink_destination_cannot_modify_external_directory(self):
        self.write_session([message('user', 'saved'), complete()])
        external = self.root / 'external'
        external.mkdir()
        (self.repo / 'transcripts').symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlinked'):
            self.export()
        self.assertEqual(list(external.iterdir()), [])

    def test_shell_entrypoint_supports_codex_env_and_explicit_session(self):
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        self.write_session([message('user', 'shell test'), complete()])
        env = {**os.environ, 'CODEX_HOME': str(self.home), 'CODEX_THREAD_ID': SESSION}
        for args in [[], ['--codex', '--session', SESSION]]:
            result = subprocess.run(['bash', str(TOOLS / 'export-transcripts.sh'), *args],
                                    cwd=self.repo, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Do not commit or push', result.stdout)
        env.pop('CODEX_THREAD_ID')
        result = subprocess.run(['bash', str(TOOLS / 'export-transcripts.sh')],
                                cwd=self.repo, env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--session TASK_ID', result.stderr)

    def test_claude_mode_still_exports_sessions_but_not_project_memory(self):
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        claude = self.root / 'claude'
        # Git may canonicalize /var to /private/var on macOS.
        root = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'],
                                       cwd=self.repo, text=True).strip()
        project = claude / 'projects' / re.sub(r'[^A-Za-z0-9]', '-', root)
        project.mkdir(parents=True)
        (project / 'session.jsonl').write_text('{"message":"visible"}\n')
        (project / 'memory').mkdir()
        (project / 'memory' / 'MEMORY.md').write_text('must remain private')
        companion = project / 'session' / 'subagents'
        companion.mkdir(parents=True)
        (companion / 'agent.jsonl').write_text('{"message":"subagent"}\n')
        env = {**os.environ, 'CLAUDE_CONFIG_DIR': str(claude)}
        for _ in range(2):
            result = subprocess.run(['bash', str(TOOLS / 'export-transcripts.sh'), '--claude'],
                                    cwd=self.repo, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        dest = self.repo / 'transcripts'
        self.assertEqual((dest / 'session.jsonl').read_text(), '{"message":"visible"}\n')
        self.assertTrue((dest / 'session' / 'subagents' / 'agent.jsonl').is_file())
        self.assertFalse((dest / 'memory').exists())
        self.assertFalse((dest / 'session' / 'session').exists())
        self.assertNotIn('git add transcripts', result.stdout)


if __name__ == '__main__':
    unittest.main()
