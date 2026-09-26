#!/usr/bin/env python3
"""Checks every vendored plugin. Exit 1 on any failure. Stdlib only.
Usage: python tools/check.py"""
import json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_BYTES = 1024 * 1024
TEXT_EXT = {".md", ".py", ".sh", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".txt", ".cfg", ".ini", ""}
CODE_EXT = {".py", ".sh", ".js", ".ts"}
ALLOWED_HOSTS = {"github.com", "raw.githubusercontent.com", "example.com", "localhost", "127.0.0.1"}
SECRETS = {
    "hf_token": r"hf_[A-Za-z0-9]{30,}",
    "github_token": r"(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}",
    "openai_like": r"sk-[A-Za-z0-9_\-]{32,}",
    "aws_key": r"AKIA[0-9A-Z]{16}",
    "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "assigned_secret": r"(?i)(?:secret|password|api[_-]?key|token)\s*[:=]\s*['\"][^'\"\s]{16,}['\"]",
    "windows_user_path": r"(?i)C:\\Users\\[A-Za-z0-9._-]+",
    "home_path": r"/home/[a-z][a-z0-9_-]+/",
    "tailscale_ip": r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
}
LIMITS = r"(?i)\b(do not use|don't use|not for|does not|do not|never|when not to|out of scope|limitations?)\b"

def spdx_of(text):
    if "Apache License" in text and "Version 2.0" in text: return "Apache-2.0"
    if "Permission is hereby granted, free of charge" in text: return "MIT"
    if "GNU GENERAL PUBLIC LICENSE" in text and "Version 3" in text: return "GPL-3.0"
    if "Redistribution and use in source and binary forms" in text: return "BSD"
    return None

def main():
    reg = json.loads((ROOT / "registry.json").read_text("utf-8"))
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text("utf-8"))
    fails, warns, skill_owner = [], [], {}
    names = [e.get("name") for e in reg["plugins"]]
    for n in {n for n in names if names.count(n) > 1}:
        fails.append(f"duplicate plugin name: {n}")
    if sorted(names) != sorted(p["name"] for p in market["plugins"]):
        fails.append("marketplace.json is out of date: run python tools/sync.py")
    for e in reg["plugins"]:
        name = e.get("name", "?")
        for k in ("name", "repo", "sha", "description", "maintainer", "license", "hosted_services"):
            if k not in e: fails.append(f"{name}: registry entry missing '{k}'")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", name): fails.append(f"{name}: plugin name must be lowercase letters, digits, hyphens")
        if not re.fullmatch(r"[a-f0-9]{40}", e.get("sha", "")): fails.append(f"{name}: sha must be a full 40-character commit id (not a branch or short sha)")
        d = ROOT / "plugins" / name
        if not d.is_dir():
            fails.append(f"{name}: not vendored; run python tools/sync.py"); continue
        files = [f for f in d.rglob("*") if f.is_file()]
        size = sum(f.stat().st_size for f in files)
        if size >= MAX_BYTES: fails.append(f"{name}: {size:,} bytes; limit is {MAX_BYTES:,}")
        lic = next((d / x for x in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING") if (d / x).exists()), None)
        if not lic:
            fails.append(f"{name}: no LICENSE file at the pinned commit")
        else:
            detected = spdx_of(lic.read_text("utf-8", "replace"))
            if detected and detected != e.get("license"):
                fails.append(f"{name}: LICENSE file looks like {detected} but registry says {e.get('license')}")
            if not detected: warns.append(f"{name}: could not detect license type automatically; confirm by hand")
        declared = " ".join(e.get("hosted_services") or []).lower()
        skills_dir = d / "skills"
        for sd in sorted(p for p in skills_dir.iterdir() if p.is_dir()) if skills_dir.is_dir() else []:
            md = sd / "SKILL.md"
            tag = f"{name}/{sd.name}"
            if not md.exists():
                fails.append(f"{tag}: missing SKILL.md"); continue
            t = md.read_text("utf-8", "replace")
            fm = re.match(r"^\ufeff?---\s*\r?\n(.*?)\r?\n---", t, re.S)
            if not fm:
                fails.append(f"{tag}: SKILL.md has no YAML frontmatter"); continue
            front = fm.group(1)
            mname = re.search(r"(?m)^name:\s*['\"]?([^'\"\s]+)", front)
            if not mname:
                fails.append(f"{tag}: frontmatter has no name")
            else:
                sn = mname.group(1)
                if sn in skill_owner: fails.append(f"{tag}: skill name '{sn}' already used by {skill_owner[sn]}")
                skill_owner[sn] = name
                if sn != sd.name: warns.append(f"{tag}: frontmatter name '{sn}' differs from folder name")
            if not re.search(r"(?m)^description:", front): fails.append(f"{tag}: frontmatter has no description")
            if not re.search(LIMITS, t): fails.append(f"{tag}: SKILL.md never says what the skill does NOT do")
            ml = re.search(r"(?m)^license:\s*['\"]?([^'\"\s]+)", front)
            if ml and ml.group(1) != e.get("license"): fails.append(f"{tag}: SKILL.md license '{ml.group(1)}' != registry '{e.get('license')}'")
            for ref in sorted(set(re.findall(r"`((?:scripts|references|assets)/[\w./-]+|[\w-]+\.(?:py|sh))`", t))):
                if not (sd / ref).exists(): fails.append(f"{tag}: SKILL.md references {ref}, which is not in the skill folder")
        for f in files:
            if f.suffix.lower() not in TEXT_EXT: continue
            txt = f.read_text("utf-8", "replace")
            rel = f.relative_to(ROOT).as_posix()
            for k, pat in SECRETS.items():
                if re.search(pat, txt): fails.append(f"{rel}: possible {k} (value not shown)")
            hosts = set(re.findall(r"\b(api\.[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)", txt))
            if f.suffix.lower() in CODE_EXT:
                hosts |= set(re.findall(r"https?://([A-Za-z0-9.-]+)", txt))
            for h in sorted(hosts):
                h = h.lower().rstrip(".")
                if h in ALLOWED_HOSTS: continue
                if h not in declared: fails.append(f"{rel}: contacts or names '{h}' but hosted_services does not declare it")
    for w in warns: print("WARN ", w)
    for f in fails: print("FAIL ", f)
    print(f"{len(reg['plugins'])} plugin(s), {len(skill_owner)} skill(s): {'PASS' if not fails else 'FAIL'} ({len(fails)} failure(s), {len(warns)} warning(s))")
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()