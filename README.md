# Lab 1 Starter: Booking Service

A small room-booking service. Users book rooms for time intervals, and if a room is
taken they land on a waitlist. It is the codebase you work in for Lab 1.

AI assistance: OpenAI Codex desktop app (model: `gpt-5.6-sol`).

**Read `ARCHITECTURE.md` first.** It maps the three layers (domain / service / repo)
so you do not have to cold-read every file.

## Build and test

```
mvn test
```

One test fails on purpose. Diagnosing and fixing it is Milestone 1.
By the way: the fix may not be where the failing test first points you. :-)

## Where things are

- Source: `src/main/java/edu/cmu/cs214/booking/` (`domain/`, `service/`, `repo/`)
- Tests: `src/test/java/edu/cmu/cs214/booking/`
- Setup: `SETUP.md`
- Your Milestone 2 task: `TASK.md`
- A proposed change you will review in Milestone 3: `changes/agent-attempt.patch` (the handout tells you how to apply it)
- Transcript export script (Codex by default; `--claude` for Claude Code): `tools/export-transcripts.sh`

See the Lab 1 handout on the course page for the three milestones you show a TA.

## Export a Codex transcript locally

From inside this repository, run:

```sh
./tools/export-transcripts.sh --codex --session YOUR_CODEX_TASK_ID
```

When an agent runs the command inside the selected Codex task, `./tools/export-transcripts.sh`
can use the `CODEX_THREAD_ID` environment variable instead. The exporter requires Python 3.9+
and reads the selected task's JSONL session segments under `$CODEX_HOME/sessions`
(default `~/.codex/sessions`). It does not select every task from the same parent folder.

The export contains the saved prompts, replies, and tool actions through the last completed
turn. It excludes internal instructions, private reasoning, and the current unfinished turn.
Rerunning replaces the generated Markdown/JSONL snapshot and removes obsolete exported JSONL
files for that task; source logs and unrelated files are not deleted. See the generated
`transcripts/EXPORT_NOTES.md` for the exact cutoff and scope. External image files are not
copied; their saved message representations are retained.

**For this public Lab 1 fork, keep transcripts local. Do not commit or push them.**
Show the exported files to your TA. For Claude Code, use `./tools/export-transcripts.sh --claude`.

Exporter regression tests (separate from the Java lab tests):

```sh
python3 -B -m unittest discover -s tools -p 'test_export_*.py' -v
```
