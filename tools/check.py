#!/usr/bin/env python3
"""Static checks for vendored skills. No plugin code is executed."""
import hashlib
import pathlib
import re
import sys
import sync

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_BYTES = sync.MAX_PLUGIN
TEXT_EXT = {".md", ".py", ".sh", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".txt", ".cfg", ".ini", ""}
ALLOWED_HOSTS = {"github.com", "raw.githubusercontent.com", "example.com", "localhost", "127.0.0.1", "www.apache.org"}
SECRETS = {
    "hf_token": r"hf_[A-Za-z0-9]{30,}",
    "github_token": r"(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}",
    "openai_like": r"sk-[A-Za-z0-9_\-]{32,}",
    "aws_key": r"AKIA[0-9A-Z]{16}",
    "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "assigned_secret": r"(?i)(?:secret|password|api[_-]?key|token)\s*[:=]\s*['\"][^'\"\s]{16,}['\"]",
    "windows_user_path": r"(?i)C:\\Users\\[A-Za-z0-9._-]+",
    "home_path": r"/(?:home|Users)/[a-zA-Z][a-zA-Z0-9_-]+/",
    "tailscale_ip": r"\b100\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.\d{1,3}\.\d{1,3}\b",
}
LIMITS = r"(?i)\b(do not use|don't use|not for|does not|do not|never|when not to|out of scope|limitations?)\b"


def spdx_of(text):
    if "Apache License" in text and "Version 2.0" in text:
        return "Apache-2.0"
    if "Permission is hereby granted, free of charge" in text:
        return "MIT"
    if "GNU GENERAL PUBLIC LICENSE" in text and "Version 3" in text:
        return "GPL-3.0"
    if "Redistribution and use in source and binary forms" in text:
        return "BSD"
    return None


def named_hosts(text):
    """Literal URL hosts and api.* names; dynamic destinations need manual review."""
    result = set(re.findall(r"\b(api\.[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)", text))
    for url in re.findall(r"https?://[^\s<>\"'\x60)\]]+", text):
        parsed = sync.urllib.parse.urlsplit(url)
        if parsed.hostname:
            result.add(parsed.hostname)
    return {host.lower().rstrip(".") for host in result}


def audit(root):
    fails, warns, skill_owner = [], [], {}
    try:
        reg = sync.read_json((root / "registry.json").read_bytes())
        sync.validate_registry(reg)
        market = sync.read_json((root / ".claude-plugin/marketplace.json").read_bytes())
    except (ValueError, OSError):
        return ["registry/marketplace invalid"], [], 0
    if market != sync.marketplace(reg):
        fails.append("marketplace.json differs from complete registry-derived metadata")
    actual_plugins = {p.name for p in (root / "plugins").iterdir()} if (root / "plugins").is_dir() else set()
    if actual_plugins != {e["name"] for e in reg["plugins"]}:
        fails.append("vendored plugin membership differs from registry")
    for entry in reg["plugins"]:
        name = entry["name"]
        folder = root / "plugins" / name
        if not folder.is_dir():
            fails.append(name + ": not vendored")
            continue
        try:
            sync.reject_links(folder)
        except sync.SyncError:
            fails.append(name + ": symbolic link refused")
            continue
        files = [p for p in folder.rglob("*") if p.is_file()]
        if sum(p.stat().st_size for p in files) >= MAX_BYTES:
            fails.append(name + ": plugin byte budget exceeded")
            continue
        try:
            source = sync.read_json((folder / "SOURCE.json").read_bytes())
            expected_identity = {key: entry[key] for key in ("repo", "ref", "sha", "path")}
            if {key: source.get(key) for key in expected_identity} != expected_identity:
                fails.append(name + ": SOURCE identity differs from registry")
            hashes = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in files if p.name != "SOURCE.json" or p.parent != folder}
            if set(source) != set(expected_identity) | {"files_sha256"} or source.get("files_sha256") != hashes:
                fails.append(name + ": SOURCE file hashes or membership differ from actual bytes")
        except (ValueError, OSError, AttributeError):
            fails.append(name + ": SOURCE manifest invalid")
        license_file = next((folder / p for p in sync.LICENSE_NAMES[:-1] if (folder / p).is_file()), None)
        if not license_file:
            fails.append(name + ": source LICENSE missing")
        else:
            detected = spdx_of(license_file.read_text("utf-8", "replace"))
            if detected and detected != entry["license"]:
                fails.append(name + ": license differs from registry")
            if not detected:
                fails.append(name + ": license requires review; unsupported automatic detection")
        declared = sync.declared_hosts(entry)
        skills = folder / "skills"
        present = {p.name for p in skills.iterdir() if p.is_dir()} if skills.is_dir() else set()
        if present != set(entry["skills"]):
            fails.append(name + ": skill membership differs from registry")
        for skill in sorted(present):
            directory = skills / skill
            md = directory / "SKILL.md"
            tag = name + "/" + skill
            if not md.is_file():
                fails.append(tag + ": SKILL.md missing")
                continue
            try:
                text = md.read_text("utf-8")
            except UnicodeError:
                fails.append(tag + ": invalid UTF-8")
                continue
            front = re.match(r"^\ufeff?---\s*\r?\n(.*?)\r?\n---", text, re.S)
            if not front:
                fails.append(tag + ": frontmatter missing")
                continue
            name_match = re.search(r"(?m)^name:\s*['\"]?([^'\"\s]+)", front.group(1))
            if not name_match or name_match.group(1) != skill:
                fails.append(tag + ": frontmatter name must match folder")
            if skill in skill_owner:
                fails.append(tag + ": duplicate skill name")
            skill_owner[skill] = name
            if not re.search(r"(?m)^description:", front.group(1)):
                fails.append(tag + ": description missing")
            if not re.search(LIMITS, text):
                fails.append(tag + ": scope limitations missing")
            license_match = re.search(r"(?m)^license:\s*['\"]?([^'\"\s]+)", front.group(1))
            if license_match and license_match.group(1) != entry["license"]:
                fails.append(tag + ": frontmatter license differs")
            refs = set(re.findall(r"\x60((?:scripts|references|assets)/[\w./-]+|[\w-]+\.(?:py|sh))\x60", text))
            for ref in refs:
                try:
                    sync.safe_path(ref)
                except sync.SyncError:
                    fails.append(tag + ": unsafe reference")
                    continue
                target = directory / ref
                resource_directory = "/" in ref and not pathlib.PurePosixPath(ref).suffix and target.is_dir()
                if not target.is_file() and not resource_directory:
                    fails.append(tag + ": referenced file missing")
        for path in files:
            relative = path.relative_to(root).as_posix()
            # Scan recognizable credentials even in non-text assets; never print values.
            raw = path.read_bytes()
            text = raw.decode("utf-8", "replace")
            for label, pattern in SECRETS.items():
                if re.search(pattern, text):
                    fails.append(relative + ": possible " + label + " (value withheld)")
            if path.suffix.lower() in TEXT_EXT:
                try:
                    raw.decode("utf-8")
                except UnicodeError:
                    fails.append(relative + ": invalid UTF-8 text")
                for host in sorted(named_hosts(text) - ALLOWED_HOSTS - declared):
                    fails.append(relative + ": undeclared literal host " + host)
    return fails, warns, len(skill_owner)


def main():
    fails, warns, count = audit(ROOT)
    for warning in warns:
        print("WARN ", warning)
    for failure in fails:
        print("FAIL ", failure)
    print("static check: %s (%d skills, %d failures); scientific correctness and dynamic destinations unverified" %
          ("PASS" if not fails else "FAIL", count, len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
