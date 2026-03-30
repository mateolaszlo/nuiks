# Repository Guidelines

## Project Structure & Module Organization

This repository is course documentation for NUIKS, not an application codebase. Keep content organized by purpose:

- `assignments/` stores assignment briefs, submissions, and project materials. Current examples include `assignments/vaja/` PDFs and `assignments/Projekt/` proposal files.
- `docs/` is for lecture, lab, and project reference documentation.
- `notes/` contains personal study notes and the ongoing journal in `notes/journal.md`.
- `README.md` explains the repository at a high level; update it when the top-level structure changes.

When adding new material, prefer creating a dedicated subfolder instead of mixing unrelated files in an existing directory.

## Build, Test, and Development Commands

There is no build pipeline or application runtime in this repository. Useful local commands are:

```bash
git status
rg --files
find assignments docs notes -maxdepth 2 -type f
```

Use these to inspect changes and verify file placement before committing. If you add automation later, document the exact command here and in the relevant `README.md`.

## Coding Style & Naming Conventions

Write documentation in Markdown with short sections, descriptive headings, and compact lists. Use UTF-8 only when needed for Slovene course names or source titles.

- Prefer lowercase directory names such as `docs/` and `notes/`.
- Name new Markdown files descriptively, for example `container-orchestration.md` or `2026-03-25-journal.md`.
- Keep related assets beside the document they support when practical.
- Use fenced code blocks for commands and paths.

## Testing Guidelines

There is no automated test suite. Review changes manually before opening a PR:

- Confirm links and paths resolve correctly.
- Check Markdown renders cleanly.
- Verify files are placed in the correct course area.
- Ensure new notes include enough context, such as date, topic, and sources where relevant.

## Commit & Pull Request Guidelines

Recent history uses short imperative messages such as `Delete assignments/vaja/.gitkeep` and `Add reference link for last year's project`. Follow that pattern.

- Keep commit subjects concise and action-focused.
- Group related documentation updates into one commit.
- In pull requests, summarize the changed area, mention any moved or renamed files, and include screenshots only if formatting or embedded images changed.
- Link the relevant assignment, lecture, or project context when it helps reviewers.
