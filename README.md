# Skillboard

One clean page that shows what you have in Claude Code, how you use it, and what to tidy up.

![Skillboard with demo data](docs/screenshot.png)

Claude Code does not show your skills, agents and plugins in one place. It does not show how often you use them, or where they came from. Skillboard reads the files already on your computer and builds a single web page from them.

## What you get

- **A plain headline.** For example: "You can reach 119 skills and 17 agents. 3 of your own skills are unused."
- **How you use it.** All-time uses of every skill, agent, plugin and tool, with bars. Last used dates too.
- **Tidy up.** Skills that overlap, skills never used, agents never called, plugins switched off, skills that exist twice, skills with no known source.
- **Everything you have.** A searchable list. Filter by type, where it works, source and use. Click a row to see what to say to trigger it, the slash command, its source and its file.
- **Your word map.** The tables in your `CLAUDE.md` files that map your words to skills.
- **Worth a look on GitHub.** Up to 5 popular repos that fit what you already use, with live star counts.

## Install

You need Python 3.9 or newer. There is nothing to `pip install`.

```bash
git clone https://github.com/jasonlohyp/skillboard.git
cd skillboard
python skillboard.py --demo      # try it with fake data first
python skillboard.py             # your real data
```

Use the `/skillboard` command inside Claude Code:

```bash
python skillboard.py --install-command
```

Pin it on Windows: run `powershell -ExecutionPolicy Bypass -File install-shortcut.ps1`. It adds **Skillboard** to the Start Menu with an icon. Right-click it and choose **Pin to taskbar**.

## Always fresh

Skillboard rebuilds the page every time you run it. Open it from the shortcut, the command or `python skillboard.py`. Opening the saved HTML file by hand shows old numbers.

## What it reads

Everything stays on your computer. Skillboard only reads. It never changes your Claude files.

| File | Used for |
|---|---|
| `~/.claude/skills/`, `~/.claude/agents/`, and `.claude/` folders in your projects | The list of skills and agents |
| `~/.claude.json` | Claude Code's own all-time use counters |
| `~/.claude/projects/**/*.jsonl` | Chat logs: agent, tool and slash command use |
| `~/.claude/settings.json` | Which plugins are switched on |
| `~/.agents/.skill-lock.json` | Where skills installed with `npx skills add` came from |
| `CLAUDE.md` files | Your word map |
| The Claude desktop app's plugin folder (Windows) | Plugins and Cowork sessions |

The only network call is the GitHub lookup, `api.github.com/repos/...`, for star counts. It is cached for 12 hours. Skip it with `--offline`.

## Your settings

Skillboard keeps your own files in `~/.claude/skillboard/`. They never go in this repo. Everything is optional: with no files at all, it still works.

Copy `config.example.json` to `~/.claude/skillboard/config.json` and edit it:

```json
{
  "sources": { "release-notes": ["example/team-skills", "https://github.com/example/team-skills"] },
  "keep": ["design-rules"],
  "mine": ["release-notes", "weekly-report"],
  "overlapGroups": { "Design skills": ["design-rules", "slides", "brand-kit"] },
  "thresholds": { "staleDays": 60, "newDays": 7 },
  "githubPicks": [{ "repo": "example/cool-skills", "why": "Fits my React work", "tags": ["react", "frontend"] }]
}
```

| Key | What it does | Example |
|---|---|---|
| `sources` | Says where a skill came from. Use it when the page shows "Not recorded". The first value is `owner/repo`, the second is the link. | `"my-skill": ["owner/repo", "https://github.com/owner/repo"]` |
| `keep` | Skills you keep on purpose. They never show as "never used". | `["design-rules"]` |
| `mine` | Skills you wrote. Their source shows "You". | `["weekly-report"]` |
| `overlapGroups` | Sets of skills that do the same job. You get a warning when you have 3 or more from one set. | `{"Design skills": ["a", "b", "c"]}` |
| `thresholds` | Your own numbers. See `defaults.json` for every name. | `{"staleDays": 60}` |
| `githubPicks` | Your own list for "Worth a look". It replaces the built-in list. `tags` are words; repos whose tags appear in your skills rank first. | `[{"repo": "owner/repo", "why": "...", "tags": ["react"]}]` |

### The files that come with Skillboard

You do not need to edit these. They are plain lists that anyone can improve with a pull request.

| File | What is in it | Format |
|---|---|---|
| `known_sources.json` | Well-known skill names and their repos, shared with everyone. It starts empty. Matches show as `owner/repo (likely)`, because names can clash. | `{"skill-name": ["owner/repo", "https://github.com/owner/repo"]}` |
| `github_candidates.json` | The repos checked for the "Worth a look" panel. | `[{"repo": "owner/repo", "why": "short reason", "tags": ["word"]}]` |
| `defaults.json` | The built-in numbers and plugin origin names. Your `config.json` wins. | `{"thresholds": {"staleDays": 90}}` |
| `messages.json` | The words on every Tidy up card. | `{"unused": {"level": "trim", "title": "{n} skill never used\|{n} skills never used", "why": "{list}."}}` |

### Claude chat skills

Skills on your claude.ai account are not on your computer, so Skillboard cannot read them. Save a copy once in `~/.claude/skillboard/chat-skills.json`:

```json
{
  "asOf": "2026-10-24",
  "skills": [
    { "name": "travel-planner", "own": true, "desc": "Plan a trip. Use when you say \"plan my trip\"." },
    { "name": "pdf", "own": false, "desc": "Read, merge and fill PDFs." }
  ]
}
```

`own: true` marks skills you uploaded. The `/skillboard` command writes this file for you when Claude has the `ListSkills` tool.

## Change the words and numbers

Nothing about the tips is buried in the code:

- `defaults.json` holds the numbers (days before a skill counts as quiet, how long the skill list may be) and the built-in overlap groups. Override any of them in `config.json` under `"thresholds"` and `"overlapGroups"`.
- `messages.json` holds the text of every Tidy up card. Edit the words, or translate them.
- `known_sources.json` and `github_candidates.json` are plain lists you can edit.

## Good to know

- **Use counts cover Claude Code only.** Claude chat on the web is not counted.
- **Chat logs are cleaned up by Claude Code after some weeks.** The all-time counter in `~/.claude.json` is the longer record. Skillboard shows the larger of the two.
- **It reads files Claude Code does not document.** `~/.claude.json` and the log format can change in an update. If a number looks wrong after an update, open an issue.
- **Windows is tested. macOS and Linux are best effort.** The core files use `~/.claude`, which is the same everywhere. The desktop app plugin folder is only searched where it is known.
- **Source "(likely)"** means the name matched a skill in `known_sources.json`. Names can clash, so check it. Add the exact source to `config.json` to remove the word.
- **Source "Not recorded"** means no install record exists. That happens when you copy a folder or download a ZIP. Add the source to `config.json`.

## Tests

```bash
python -m unittest discover tests
```

## License

MIT. See `LICENSE`.
