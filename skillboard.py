#!/usr/bin/env python3
"""Skillboard: one clean page that shows what Claude Code skills, agents, plugins and tools
you have, how much you use them, what to tidy up, and popular GitHub skills worth a look.

    python skillboard.py                 build the page and open it
    python skillboard.py --demo          fake data, safe for screenshots
    python skillboard.py --no-open       build only
    python skillboard.py --offline       skip the GitHub lookup
    python skillboard.py --install-command   add the /skillboard command to Claude Code

Everything stays on your computer. The only network call is the optional GitHub lookup
for star counts (api.github.com). Your own settings live in ~/.claude/skillboard/.
"""
import argparse
import glob
import json
import os
import re
import sys
import time
import urllib.request
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()
CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR") or HOME / ".claude")
CLAUDE_JSON = CLAUDE / ".claude.json" if os.environ.get("CLAUDE_CONFIG_DIR") else HOME / ".claude.json"
DATA_DIR = CLAUDE / "skillboard"  # your settings, saved chat skills, cache and the built page
NOW_MS = int(time.time() * 1000)
DAY = 86_400_000


# ---------------------------------------------------------------- small helpers
def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def front(path):
    """Read the YAML-style header of a SKILL.md or agent file."""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    m = re.match(r"---\s*\n(.*?)\n---", text, re.S)
    data, key = {}, None
    if m:
        for line in m.group(1).splitlines():
            kv = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
            if kv:
                key = kv.group(1)
                data[key] = kv.group(2).strip().strip('"')
            elif key and line.strip():
                data[key] += " " + line.strip()
    return data


def ts_ms(s):
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return 0


def hints(desc):
    """Phrases that trigger a skill, taken from its own description."""
    say = [q.strip() for q in re.findall(r'["“]([^"”]{3,70})["”]', desc)][:6]
    m = re.search(r"(\b(?:ALWAYS |Always )?(?:[Uu]se|[Tt]rigger)\b[^.]*\.|This skill should be used[^.]*\.)", desc)
    when = (m.group(1) if m else desc.split(". ")[0])[:240]
    return say, when


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def tilde(path):
    """Show ~ instead of your home folder, so the page never carries your user name."""
    return str(path).replace(str(HOME), "~").replace("\\", "/")


def app_roots():
    """Where the Claude desktop app keeps plugins and Cowork sessions (best effort per OS)."""
    roots = [os.environ.get("LOCALAPPDATA", ""), str(HOME / "Library" / "Application Support"), str(HOME / ".config")]
    return [Path(r) / name for r in roots if r for name in ("Claude-Data",) if (Path(r) / name).exists()]


# ---------------------------------------------------------------- word maps
def word_maps(path, scope):
    """Markdown tables in CLAUDE.md headed like 'Owner says | Do this' become your word map."""
    out = []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return out
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|\s*:?-{2,}", lines[i + 1]):
            head = [c.strip().lower() for c in lines[i].strip().strip("|").split("|")]
            j, rows = i + 2, []
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                if len(cells) >= 2:
                    rows.append(cells[:2])
                j += 1
            if head and re.search(r"says|words?|trigger|phrase", head[0]) and rows:
                out += [dict(say=r[0].replace("`", ""), do=r[1].replace("`", ""), scope=scope) for r in rows]
            i = j
        else:
            i += 1
    return out


# ---------------------------------------------------------------- collect
class Sources:
    """Where each skill came from: install record, built-in list, your config, or its own files."""

    def __init__(self, cfg):
        self.lock = load_json(HOME / ".agents" / ".skill-lock.json", {}).get("skills", {})
        known = load_json(HERE / "known_sources.json", {})
        # the built-in list matches by skill name only, so it is a good guess, not proof
        self.known = {n: (v[0] + " (likely)", v[1]) for n, v in known.items() if not n.startswith("_")}
        self.known.update({n: tuple(v) for n, v in cfg.get("sources", {}).items()})
        self.mine = set(cfg.get("mine", []))

    def detect(self, path):
        try:
            d = front(path)
            for key in ("repository", "source", "homepage", "url"):
                m = re.search(r"github\.com/([\w.-]+/[\w.-]+)", d.get(key, ""))
                if m:
                    repo = m.group(1).removesuffix(".git")
                    return repo, "https://github.com/" + repo
            git_config = Path(path).parent / ".git" / "config"
            if git_config.exists():
                m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?\s", git_config.read_text(errors="ignore") + " ")
                if m:
                    return m.group(1), "https://github.com/" + m.group(1)
        except Exception:
            pass
        return None

    def of(self, name, kind, path=""):
        if kind == "agent":
            return "You", ""
        if name in self.lock:
            s = self.lock[name]
            return s.get("source", "GitHub"), (s.get("sourceUrl") or "").removesuffix(".git")
        if name in self.known:
            return self.known[name]
        if name in self.mine:
            return "You", ""
        found = self.detect(path) if path else None
        return found or ("Not recorded", "")


def read_logs():
    """Count agent, tool and skill use from Claude Code chat logs and Cowork sessions."""
    agent_uses, agent_last, tool_uses, tool_last = Counter(), {}, Counter(), {}
    tx_skill, tx_last = Counter(), {}
    cmd = re.compile(r"<command-name>/?([\w:.-]+)</command-name>")
    skill_call = re.compile(r'"name":\s*"Skill",\s*"input":\s*\{[^}]*?"skill":\s*"([^"]+)"')
    logs = glob.glob(str(CLAUDE / "projects" / "*" / "*.jsonl")) + glob.glob(str(CLAUDE / "projects" / "*" / "*" / "subagents" / "*.jsonl"))
    for root in app_roots():
        for f in glob.glob(str(root / "*" / "local-agent-mode-sessions" / "*" / "*" / "local_*" / "audit.jsonl")):
            try:
                for line in open(f, encoding="utf-8", errors="ignore"):
                    for m in skill_call.finditer(line):
                        tx_skill[m.group(1)] += 1
            except OSError:
                pass
    for f in logs:
        try:
            fh = open(f, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"tool_use"' not in line and "<command-name>" not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                msg = d.get("message", {})
                content = msg.get("content")
                t = ts_ms(d.get("timestamp", ""))
                if msg.get("role") == "user":
                    texts = [content] if isinstance(content, str) else [b.get("text", "") for b in (content or []) if isinstance(b, dict) and b.get("type") == "text"]
                    for tx in texts:
                        if tx.lstrip().startswith("<command-name>") or "<command-message>" in tx[:80]:
                            for nm in cmd.findall(tx)[:1]:
                                tx_skill[nm] += 1
                                tx_last[nm] = max(tx_last.get(nm, 0), t)
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    nm = b.get("name", "")
                    if nm in ("Agent", "Task"):
                        a = b.get("input", {}).get("subagent_type") or "general-purpose"
                        agent_uses[a] += 1
                        agent_last[a] = max(agent_last.get(a, 0), t)
                    elif nm == "Skill":
                        sk = b.get("input", {}).get("skill")
                        if sk:
                            tx_skill[sk] += 1
                            tx_last[sk] = max(tx_last.get(sk, 0), t)
                    else:
                        key = nm
                        if nm.startswith("mcp__"):
                            parts = nm.split("__")
                            key = "mcp:" + (parts[1] if len(parts) > 1 else nm)
                        tool_uses[key] += 1
                        tool_last[key] = max(tool_last.get(key, 0), t)
    return dict(agent_uses=agent_uses, agent_last=agent_last, tool_uses=tool_uses, tool_last=tool_last,
                tx_skill=tx_skill, tx_last=tx_last, n_logs=len(logs))


def collect(cfg):
    claude_json = load_json(CLAUDE_JSON, {})
    settings = load_json(CLAUDE / "settings.json", {})
    skill_usage = claude_json.get("skillUsage", {})
    plugin_usage = claude_json.get("pluginUsage", {})
    enabled_plugins = settings.get("enabledPlugins", {})
    src = Sources(cfg)
    logs = read_logs()
    keep = set(cfg.get("keep", []))

    projects = []
    for p in claude_json.get("projects", {}):
        pp = Path(p)
        try:
            if pp.resolve() == HOME.resolve():
                continue
        except OSError:
            continue
        if (pp / ".claude" / "skills").exists() or (pp / ".claude" / "agents").exists():
            projects.append(pp)

    def skill_stat(name):
        c = skill_usage.get(name, {})
        return (max(c.get("usageCount", 0), logs["tx_skill"].get(name, 0)),
                max(c.get("lastUsedAt", 0), logs["tx_last"].get(name, 0)))

    items = []

    def add(kind, name, desc, scope, project, path, uses=0, last=0, source=None):
        if source is not None:
            s, url = source
        elif kind in ("skill", "agent"):
            s, url = src.of(name, kind, path)
        else:
            s, url = "", ""
        items.append(dict(kind=kind, name=name, desc=desc, scope=scope, project=project, path=str(path),
                          uses=uses, last=last, source=s, url=url))

    for p in sorted((CLAUDE / "skills").glob("*/SKILL.md")):
        d = front(p)
        n = d.get("name") or p.parent.name
        add("skill", n, d.get("description", ""), "global", "", p, *skill_stat(n))
    for pr in projects:
        for p in sorted((pr / ".claude" / "skills").glob("*/SKILL.md")):
            d = front(p)
            n = d.get("name") or p.parent.name
            add("skill", n, d.get("description", ""), "project", pr.name, p, *skill_stat(n))
        for p in sorted((pr / ".claude" / "agents").glob("*.md")):
            d = front(p)
            n = d.get("name") or p.stem
            add("agent", n, d.get("description", ""), "project", pr.name, p, logs["agent_uses"].get(n, 0), logs["agent_last"].get(n, 0))
    for p in sorted((CLAUDE / "agents").glob("*.md")):
        d = front(p)
        n = d.get("name") or p.stem
        add("agent", n, d.get("description", ""), "global", "", p, logs["agent_uses"].get(n, 0), logs["agent_last"].get(n, 0))

    # plugins installed through the Claude desktop app
    app_plugins = []
    for root in app_roots():
        for mf in glob.glob(str(root / "*" / "rpm" / "*" / "*" / "manifest.json")):
            base = Path(mf).parent
            for pl in load_json(mf, {}).get("plugins", []):
                name = (pl.get("displayName") or pl.get("name") or "").strip()
                slug = name.lower().replace(" ", "-")
                app_plugins.append(dict(slug=slug, market=pl.get("marketplaceName", "Claude app"), dir=base / pl["id"]))
    plugin_skill_uses = defaultdict(list)
    for n, u in skill_usage.items():
        if ":" in n:
            plugin_skill_uses[n.split(":")[0]].append((u.get("usageCount", 0), u.get("lastUsedAt", 0)))
    listed = set()
    for ap in app_plugins:
        for sp in sorted((ap["dir"] / "skills").glob("*/SKILL.md")):
            d = front(sp)
            key = ap["slug"] + ":" + (d.get("name") or sp.parent.name)
            listed.add(key)
            add("skill", key, d.get("description", ""), "plugin", "", sp, *skill_stat(key),
                source=(ap["slug"] + " plugin (" + ap["market"] + ")", ""))
    for n in skill_usage:
        if ":" in n and n not in listed:
            add("skill", n, "Comes with the " + n.split(":")[0] + " plugin.", "plugin", "", "", *skill_stat(n),
                source=(n.split(":")[0] + " plugin", ""))

    # the same skill or agent copied into several projects shows once
    merged, order = {}, []
    for i in items:
        k = (i["kind"], i["name"])
        if k not in merged:
            merged[k] = i
            order.append(k)
        else:
            m = merged[k]
            if i["scope"] == "global":
                m["scope"] = "global"
            if i["project"] and i["project"] not in m["project"].split(", "):
                m["project"] = (m["project"] + ", " + i["project"]) if m["project"] else i["project"]
    items[:] = [merged[k] for k in order]

    for i in items:
        try:
            st = Path(i["path"]).stat()
            i["new"] = bool(i["path"]) and (time.time() - max(st.st_mtime, st.st_ctime)) < setting(cfg, "newDays") * 86400
        except OSError:
            i["new"] = False

    def same(a, b):
        return a == b or a.endswith(b) or b.endswith(a)

    plugins = {ap["slug"]: dict(source=ap["market"], keys=[]) for ap in app_plugins}
    origins = DEFAULTS.get("pluginOrigins", {})
    for key in sorted(set(plugin_usage) | set(enabled_plugins)):
        base = key.split("@")[0]
        origin = key.split("@")[1] if "@" in key else ""
        hit = next((s for s in plugins if same(s, base)), None)
        if hit is None:
            hit = base
            plugins[hit] = dict(source=origins.get(origin, origin or "Claude app"), keys=[])
        plugins[hit]["keys"].append(key)
    for slug, pl in sorted(plugins.items()):
        uses = max([plugin_usage.get(k, {}).get("usageCount", 0) for k in pl["keys"]] + [sum(c for c, _ in plugin_skill_uses.get(slug, []))])
        last = max([plugin_usage.get(k, {}).get("lastUsedAt", 0) for k in pl["keys"]] + [l for _, l in plugin_skill_uses.get(slug, [])]) if uses else 0
        flags = [enabled_plugins[k] for k in pl["keys"] if k in enabled_plugins]
        add("plugin", slug, "A bundle of skills, agents or tools.", "global", "", "", uses, last, source=(pl["source"], ""))
        items[-1]["state"] = "off" if flags and not any(flags) else "on"

    for k, c in logs["tool_uses"].most_common():
        is_mcp = k.startswith("mcp:")
        nm = k[4:] if is_mcp else k
        add("tool", nm.replace("_", " "), "Connected app (MCP server)." if is_mcp else "Built-in Claude Code tool.",
            "global", "", "", c, logs["tool_last"].get(k, 0), source=("Connected app" if is_mcp else "Built in", ""))

    # skills on your claude.ai account are not on this computer; a saved copy is read if you made one
    chat = load_json(DATA_DIR / "chat-skills.json", {})
    by_name = {i["name"]: i for i in items if i["kind"] == "skill"}
    for cs in chat.get("skills", []):
        if cs["name"] in by_name:
            by_name[cs["name"]]["chat"] = True
        else:
            add("skill", cs["name"], cs.get("desc", ""), "chat", "", "", *skill_stat(cs["name"]),
                source=("You (uploaded in Claude chat)" if cs.get("own") else "Claude app", ""))
            items[-1]["chat"] = True

    for i in items:
        i["keep"] = i["name"] in keep
        i["say"], i["when"] = hints(i["desc"])
        i["call"] = ("/" + i["name"]) if i["kind"] == "skill" else ("Use the " + i["name"] + " agent to ...") if i["kind"] == "agent" else ""

    wordmap = word_maps(CLAUDE / "CLAUDE.md", "Every project")
    seen = {(w["say"], w["do"]) for w in wordmap}
    for pr in projects:
        for w in word_maps(pr / "CLAUDE.md", "Only in " + pr.name):
            if (w["say"], w["do"]) not in seen:
                wordmap.append(w)

    first = [v["lastUsedAt"] for v in skill_usage.values() if v.get("lastUsedAt")]
    meta = dict(since=datetime.fromtimestamp(min(first or [NOW_MS]) / 1000).strftime("%b %Y"),
                sessions=logs["n_logs"], chatAsOf=chat.get("asOf", ""), projects=[p.name for p in projects])
    return items, wordmap, meta


# ---------------------------------------------------------------- demo data
def demo():
    def it(kind, name, desc, uses, days, scope="global", source="You", url="", **kw):
        d = dict(kind=kind, name=name, desc=desc, scope=scope, project=kw.get("project", ""), path="",
                 uses=uses, last=NOW_MS - days * DAY if uses else 0, source=source, url=url,
                 new=kw.get("new", False), keep=kw.get("keep", False))
        d["say"], d["when"] = hints(desc)
        d["call"] = ("/" + name) if kind == "skill" else ("Use the " + name + " agent to ...") if kind == "agent" else ""
        if "state" in kw:
            d["state"] = kw["state"]
        if kw.get("chat"):
            d["chat"] = True
        return d

    gh = "https://github.com/"
    items = [
        it("skill", "release-notes", 'Write release notes from merged PRs. Use when you say "write release notes" or "what shipped".', 41, 1, source="You"),
        it("skill", "brainstorming", "Explore intent before building. Use when starting any creative work.", 28, 0, "plugin", "superpowers plugin (demo)"),
        it("skill", "interviewing", "Interview the user about a plan. Use when you say \"interview me\" or want to stress-test an idea.", 17, 2, source="example/skills", url=gh + "example/skills"),
        it("skill", "debugging", 'Find the root cause first. Use when you say "bug", "broken" or "fix this".', 12, 4, source="example/skills", url=gh + "example/skills"),
        it("skill", "pdf-tools", "Merge, split and fill PDFs. Use when a .pdf file is involved.", 9, 12, source="example/office-skills", url=gh + "example/office-skills"),
        it("skill", "design-rules", "Anti-generic design rules. Use when a page looks templated.", 5, 9, source="example/design-skill", url=gh + "example/design-skill", keep=True),
        it("skill", "slides", "Build HTML slide decks. Use when you say \"make a deck\".", 3, 140, source="example/design-skill", url=gh + "example/design-skill"),
        it("skill", "brand-kit", "Brand voice and assets.", 0, 0, source="example/design-skill", url=gh + "example/design-skill"),
        it("skill", "banner-maker", "Make banners for social media.", 0, 0, source="example/design-skill", url=gh + "example/design-skill"),
        it("skill", "old-notes-helper", "Tidy meeting notes.", 0, 0, source="Not recorded"),
        it("skill", "travel-planner", "Plan a trip. Use when you say \"plan my trip\".", 0, 0, "chat", "You (uploaded in Claude chat)", chat=True),
        it("skill", "budget-coach", "Monthly budget check. Use when you say \"run my budget\".", 0, 0, "chat", "You (uploaded in Claude chat)", chat=True),
        it("agent", "code-reviewer", "Reviews one diff for bugs. Report only.", 33, 0, "project", project="demo-app"),
        it("agent", "ui-reviewer", "Scores a screen from screenshots.", 21, 1, "project", project="demo-app"),
        it("agent", "test-writer", "Writes tests first.", 8, 6, "project", project="demo-app"),
        it("agent", "release-checker", "Go or no-go before a release.", 0, 0, "project", project="demo-app"),
        it("plugin", "superpowers", "A bundle of skills, agents or tools.", 44, 0, source="demo-marketplace", state="on"),
        it("plugin", "finance", "A bundle of skills, agents or tools.", 0, 0, source="demo-marketplace", state="off"),
        it("plugin", "design", "A bundle of skills, agents or tools.", 0, 0, source="demo-marketplace", state="off"),
        it("tool", "Bash", "Built-in Claude Code tool.", 4210, 0, source="Built in"),
        it("tool", "Read", "Built-in Claude Code tool.", 3120, 0, source="Built in"),
        it("tool", "Edit", "Built-in Claude Code tool.", 980, 0, source="Built in"),
        it("tool", "Browser", "Connected app (MCP server).", 640, 1, source="Connected app"),
    ]
    wordmap = [
        dict(say='"brainstorm"', do="brainstorming, before any creative work", scope="Every project"),
        dict(say='"interview me"', do="interviewing", scope="Every project"),
        dict(say='"bug", "broken", "fix this"', do="debugging first", scope="Every project"),
        dict(say='"release notes"', do="release-notes", scope="Only in demo-app"),
    ]
    return items, wordmap, dict(since="Jan 2026", sessions=312, chatAsOf="", projects=["demo-app"])


# ---------------------------------------------------------------- tips
DEFAULTS = load_json(HERE / "defaults.json", {})
MESSAGES = load_json(HERE / "messages.json", {})


def setting(cfg, key):
    """A number from your config.json, or the built-in default from defaults.json."""
    return cfg.get("thresholds", {}).get(key, DEFAULTS.get("thresholds", {}).get(key))


def tip(key, n=0, **kw):
    """Build one Tidy up card from messages.json."""
    m = MESSAGES[key]
    title = m["title"]
    if "|" in title:
        one, many = title.split("|", 1)
        title = one if n == 1 else many
    return dict(level=m["level"], title=title.format(n=n, **kw), why=m["why"].format(**kw))


def names(rows, limit):
    out = ", ".join(r["name"] for r in rows[:limit])
    return out + (" ..." if len(rows) > limit else "")


def analyze(items, cfg):
    recs = []
    groups = dict(DEFAULTS.get("overlapGroups", {}))
    groups.update(cfg.get("overlapGroups", {}))
    limit = setting(cfg, "listNames")
    used = lambda i: i["uses"] > 0
    real = [i for i in items if i["kind"] == "skill" and i["scope"] in ("global", "project")]
    agents = [i for i in items if i["kind"] == "agent"]
    for label, group in groups.items():
        have = sorted([i for i in real if i["name"] in group], key=lambda i: -i["uses"])
        if len(have) >= setting(cfg, "overlapMin"):
            recs.append(tip("overlap", len(have), label=label, list=", ".join(f"{i['name']} ({i['uses']})" for i in have)))
    unused = [i for i in real if not used(i) and not i["new"] and not i["keep"]]
    if unused:
        recs.append(tip("unused", len(unused), list=names(unused, limit)))
    days = setting(cfg, "staleDays")
    stale = [i for i in real if used(i) and i["last"] and NOW_MS - i["last"] > days * DAY]
    if stale:
        recs.append(tip("stale", len(stale), days=days, list=names(stale, limit)))
    dead = [i for i in agents if not used(i)]
    if dead:
        recs.append(tip("deadAgents", len(dead), list=names(dead, limit)))
    off = [i for i in items if i["kind"] == "plugin" and i.get("state") == "off" and not used(i)]
    if off:
        recs.append(tip("pluginsOff", len(off), list=names(off, limit)))
    twins = [i for i in real if i["scope"] == "global" and i["project"]]
    if twins:
        recs.append(tip("twins", len(twins), list=", ".join(f"{i['name']} (also in {i['project']})" for i in twins[:limit])))
    unknown = [i for i in real if i["source"] == "Not recorded"]
    if unknown:
        recs.append(tip("unknown", len(unknown), list=names(unknown, limit), config=tilde(DATA_DIR / "config.json")))
    chars = sum(len(i["desc"]) + len(i["name"]) for i in real + agents)
    if chars > setting(cfg, "longListChars"):
        recs.append(tip("longList", tokens=f"{chars // 4:,}"))
    top = sorted([i for i in items if i["kind"] in ("skill", "agent") and used(i)], key=lambda i: -i["uses"])[:1]
    if top:
        recs.append(tip("workhorse", name=top[0]["name"], uses=top[0]["uses"]))
    return recs


# ---------------------------------------------------------------- popular on GitHub
def popular(items, cfg, offline, use_cache=True):
    cache_file = DATA_DIR / ("github-cache.json" if use_cache else "github-cache-demo.json")
    cache = load_json(cache_file, {})
    if offline:
        return cache.get("picks", []), "Offline: showing the last saved list." if cache.get("picks") else ""
    if cache.get("at") and time.time() - cache["at"] < setting(cfg, "githubCacheHours") * 3600:
        return cache["picks"], ""
    candidates = load_json(HERE / "github_candidates.json", [])
    candidates = cfg.get("githubPicks", candidates)
    lock = load_json(HOME / ".agents" / ".skill-lock.json", {}).get("skills", {})
    known = load_json(HERE / "known_sources.json", {})
    have = {s.get("source", "").lower() for s in lock.values()} | {v[0].lower() for n, v in known.items() if not n.startswith("_")}
    have |= {i["source"].lower() for i in items}
    bag = " ".join((i["name"] + " " + i["desc"]).lower() for i in items)
    picks = []
    for c in candidates:
        repo = c["repo"]
        if repo.lower() in have:
            continue
        try:
            req = urllib.request.Request("https://api.github.com/repos/" + repo,
                                         headers={"User-Agent": "skillboard", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=12) as r:
                info = json.load(r)
        except Exception:
            continue
        if info.get("archived"):
            continue
        fit = sum(1 for t in c.get("tags", []) if t in bag)
        picks.append(dict(name=info["full_name"], url=info["html_url"], stars=info["stargazers_count"],
                          desc=(info.get("description") or "")[:140], why=c.get("why", ""), fit=fit))
    if not picks:
        return cache.get("picks", []), "Could not reach GitHub." + (" Showing the last saved list." if cache.get("picks") else "")
    picks.sort(key=lambda p: (-p["fit"], -p["stars"]))
    picks = picks[:setting(cfg, "githubPicks")]
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"at": time.time(), "picks": picks}), encoding="utf-8")
    except OSError:
        pass
    return picks, ""


# ---------------------------------------------------------------- command + main
def install_command():
    target = CLAUDE / "commands" / "skillboard.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    script = str(Path(__file__).resolve()).replace("\\", "/")
    target.write_text(
        "---\n"
        "description: Open my Skillboard (skills, agents, plugins and tools, how I use them, what to tidy)\n"
        "allowed-tools: Bash(python:*), Bash(python3:*), Write\n"
        "---\n"
        "1. If you have the ListSkills tool, call it once. Save the result to "
        f"`{(DATA_DIR / 'chat-skills.json').as_posix()}` as "
        '`{"asOf": "<today>", "skills": [{"name": "...", "own": true|false, "desc": "<full description>"}]}`. '
        "Set `own` to true only for skills whose id starts with `skill_`. Skip this step without ListSkills.\n"
        f"2. Run `python \"{script}\"` with Bash. It rebuilds the page with fresh data and opens it.\n"
        "3. For each skill the page marks \"Not recorded\", look for its GitHub source. If you are sure, add it under "
        f"`sources` in `{(DATA_DIR / 'config.json').as_posix()}`. If not, ask me.\n"
        "4. Reply in two short lines: how many skills are never used, and the top tip. Do not paste the page.\n",
        encoding="utf-8")
    print("Added /skillboard to", target)


def main():
    ap = argparse.ArgumentParser(description="One clean page for your Claude Code skills, agents, plugins and tools.")
    ap.add_argument("--demo", action="store_true", help="use fake data (safe for screenshots)")
    ap.add_argument("--no-open", action="store_true", help="build the page but do not open it")
    ap.add_argument("--offline", action="store_true", help="skip the GitHub lookup")
    ap.add_argument("--out", help="write the page here instead of ~/.claude/skillboard/skillboard.html")
    ap.add_argument("--install-command", action="store_true", help="add the /skillboard command to Claude Code")
    args = ap.parse_args()
    if args.install_command:
        return install_command()

    cfg = {"overlapGroups": {"Design skills": ["design-rules", "slides", "brand-kit", "banner-maker"]}} if args.demo \
        else load_json(DATA_DIR / "config.json", {})
    items, wordmap, meta = demo() if args.demo else collect(cfg)
    recs = analyze(items, cfg)
    github, note = popular(items, cfg, args.offline, not args.demo)
    data = dict(made=datetime.now().strftime("%d %b %Y, %H:%M"), madeMs=NOW_MS, now=NOW_MS, items=items, recs=recs,
                wordmap=wordmap, github=github, ghNote=note, demo=args.demo, **meta)
    template = (HERE / "template.html").read_text(encoding="utf-8")
    page = template.replace("/*DATA*/null", json.dumps(data).replace("</", "<\\/"))
    out = Path(args.out) if args.out else DATA_DIR / "skillboard.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Skillboard: {len(items)} items, {len(recs)} tips, {len(github)} GitHub picks -> {out}")
    if not args.no_open:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    sys.exit(main())
