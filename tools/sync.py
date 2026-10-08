#!/usr/bin/env python3
"""Bounded, non-executing vendoring of exact GitHub commits. Stdlib only."""
import hashlib
import gzip
import io
import json
import os
import pathlib
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "NOTICE")
MAX_DOWNLOAD = 32 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
MAX_MEMBERS = 10000
MAX_PLUGIN = 1024 * 1024
MAX_JSON_DEPTH = 64
NAME = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")
REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")
HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}|localhost")


class SyncError(ValueError):
    pass


class RollbackError(SyncError):
    """Recovery was incomplete; the generated staging path must be retained."""

    def __init__(self, recovery_path):
        self.recovery_path = recovery_path
        super().__init__("rollback incomplete; backups retained at "
                         + json.dumps(str(recovery_path)))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SyncError("duplicate JSON key")
        result[key] = value
    return result


def read_json(raw):
    if len(raw) > MAX_PLUGIN:
        raise SyncError("JSON exceeds byte budget")
    depth, quoted, escaped = 0, False, False
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise SyncError("JSON nesting exceeds 64 levels")
        elif byte in (93, 125):
            depth -= 1
            if depth < 0:
                raise SyncError("invalid JSON structure")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(SyncError("nonfinite JSON")))
    except RecursionError as error:
        raise SyncError("JSON nesting exceeds interpreter limit") from error


def safe_path(value):
    if not isinstance(value, str) or len(value) > 512:
        raise SyncError("invalid relative path")
    parts = value.split("/")
    reserved = {"con", "prn", "aux", "nul"} | {"com%d" % i for i in range(1, 10)} | {"lpt%d" % i for i in range(1, 10)}
    if any(not p or p in (".", "..") or not re.fullmatch(r"[A-Za-z0-9_.-]+", p)
           or p.endswith((".", " ")) or p.split(".")[0].lower() in reserved for p in parts):
        raise SyncError("unsafe relative path")
    return value


def declared_hosts(entry):
    services = entry["hosted_services"]
    if not isinstance(services, list):
        raise SyncError("hosted_services must be a list")
    result = set()
    for service in services:
        if not isinstance(service, str) or len(service) > 1024 or "\n" in service or "\r" in service or "|" in service:
            raise SyncError("invalid hosted service declaration")
        host = service.split(" - ", 1)[0].lower()
        if not HOST.fullmatch(host):
            raise SyncError("hosted service must start with an exact hostname")
        result.add(host)
    return result


def validate_entry(entry):
    required = {"name", "repo", "sha", "ref", "path", "skills", "description", "maintainer", "license", "hosted_services"}
    if not isinstance(entry, dict) or set(entry) != required:
        raise SyncError("registry entry fields must match the documented contract")
    if not isinstance(entry["name"], str) or not NAME.fullmatch(entry["name"]):
        raise SyncError("invalid plugin name")
    if not isinstance(entry["repo"], str) or not REPO.fullmatch(entry["repo"]) or ".." in entry["repo"]:
        raise SyncError("repo must be a GitHub owner/repository")
    if not isinstance(entry["sha"], str) or not re.fullmatch(r"[a-f0-9]{40}", entry["sha"]):
        raise SyncError("sha must be a full lowercase commit id")
    ref = entry["ref"]
    if not isinstance(ref, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", ref) or ".." in ref:
        raise SyncError("invalid source ref")
    safe_path(entry["path"])
    skills = entry["skills"]
    if not isinstance(skills, list) or not skills or len(skills) > 100:
        raise SyncError("skills must be a nonempty unique list")
    if any(not isinstance(s, str) or not NAME.fullmatch(s) for s in skills):
        raise SyncError("invalid skill name")
    if len(set(skills)) != len(skills):
        raise SyncError("duplicate skill name")
    for field in ("description", "maintainer", "license"):
        value = entry[field]
        if not isinstance(value, str) or not value.strip() or len(value) > 1024 or any(c in value for c in "\r\n|"):
            raise SyncError("invalid registry text field")
    declared_hosts(entry)


def validate_registry(registry):
    if not isinstance(registry, dict) or set(registry) != {"name", "owner", "description", "version", "plugins"}:
        raise SyncError("invalid registry fields")
    for field in ("name", "description", "version"):
        value = registry[field]
        if not isinstance(value, str) or not value.strip() or len(value) > 1024 or any(c in value for c in "\r\n|"):
            raise SyncError("invalid registry metadata")
    if not isinstance(registry["owner"], dict) or not isinstance(registry["owner"].get("name"), str):
        raise SyncError("invalid registry owner")
    plugins = registry["plugins"]
    if not isinstance(plugins, list) or not 1 <= len(plugins) <= 50:
        raise SyncError("registry must contain 1 to 50 plugins")
    names = set()
    for entry in plugins:
        validate_entry(entry)
        if entry["name"] in names:
            raise SyncError("duplicate plugin name")
        names.add(entry["name"])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        raise SyncError("redirect refused")


def bounded_get(url, limit, accept=None):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"api.github.com", "codeload.github.com"} or parsed.username or parsed.password or parsed.port:
        raise SyncError("source URL is outside the GitHub allowlist")
    headers = {"User-Agent": "ai4science-skills-sync"}
    if accept is not None:
        headers["Accept"] = accept
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and parsed.hostname == "api.github.com":
        headers["Authorization"] = "Bearer " + token
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(urllib.request.Request(url, headers=headers), timeout=30) as response:
        if response.status != 200 or response.geturl() != url:
            raise SyncError("source response did not match requested URL")
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise SyncError("source response exceeds byte budget")
    return raw


def verify_ref(entry):
    ref = urllib.parse.quote(entry["ref"], safe="")
    # GitHub's SHA media type omits the potentially large commit diff. Keep the
    # response bounded to the 40-character hash plus an optional final newline.
    resolved = bounded_get("https://api.github.com/repos/%s/commits/%s" % (entry["repo"], ref),
                           41, accept="application/vnd.github.sha")
    if not re.fullmatch(rb"[a-f0-9]{40}\n?", resolved) or resolved[:40].decode("ascii") != entry["sha"]:
        raise SyncError("source ref does not resolve to declared commit")


def fetch(repo, sha):
    return bounded_get("https://codeload.github.com/%s/tar.gz/%s" % (repo, sha), MAX_DOWNLOAD)


def prepare(entry, raw):
    """Validate all archive paths and budgets before returning selected bytes."""
    validate_entry(entry)
    if len(raw) > MAX_DOWNLOAD:
        raise SyncError("archive exceeds download budget")
    # Bound full decompression before tarfile can consume oversized PAX metadata.
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
        unpacked = compressed.read(MAX_EXPANDED + 1)
    if len(unpacked) > MAX_EXPANDED:
        raise SyncError("archive exceeds decompression budget")
    result, archive_paths, root, expanded = {}, set(), None, 0
    with tarfile.open(fileobj=io.BytesIO(unpacked), mode="r:") as archive:
        for count, member in enumerate(archive, 1):
            if count > MAX_MEMBERS:
                raise SyncError("archive exceeds member budget")
            name = member.name.rstrip("/") if member.isdir() else member.name
            safe_path(name)
            parts = name.split("/", 1)
            if root is None:
                root = parts[0]
            if root != parts[0] or name.casefold() in archive_paths:
                raise SyncError("archive has inconsistent root or duplicate paths")
            archive_paths.add(name.casefold())
            if member.isdir():
                continue
            if not member.isfile() or member.size < 0:
                raise SyncError("archive links and special files are refused")
            expanded += member.size
            if expanded > MAX_EXPANDED:
                raise SyncError("archive exceeds expanded byte budget")
            if len(parts) != 2:
                raise SyncError("archive file has no repository prefix")
            relative = parts[1]
            if relative in LICENSE_NAMES:
                target = relative
            elif relative.startswith(entry["path"] + "/"):
                sub = relative[len(entry["path"]) + 1:]
                if sub.split("/", 1)[0] not in entry["skills"]:
                    continue
                target = "skills/" + sub
            else:
                continue
            if member.size >= MAX_PLUGIN or target in result:
                raise SyncError("selected file exceeds budget or has duplicate destination")
            handle = archive.extractfile(member)
            data = handle.read(MAX_PLUGIN)
            if len(data) != member.size:
                raise SyncError("archive file was truncated")
            result[target] = data
    if sum(len(data) for data in result.values()) >= MAX_PLUGIN:
        raise SyncError("plugin exceeds byte budget")
    if not any(name in result for name in LICENSE_NAMES[:-1]):
        raise SyncError("source license is missing")
    if any("skills/%s/SKILL.md" % skill not in result for skill in entry["skills"]):
        raise SyncError("requested skill has no SKILL.md at pinned commit")
    source = {"repo": entry["repo"], "ref": entry["ref"], "sha": entry["sha"], "path": entry["path"],
              "files_sha256": {path: hashlib.sha256(data).hexdigest() for path, data in sorted(result.items())}}
    result["SOURCE.json"] = (json.dumps(source, indent=2) + "\n").encode()
    return result


def marketplace(registry):
    return {"name": registry["name"], "owner": registry["owner"],
            "metadata": {"description": registry["description"], "version": registry["version"]},
            "plugins": [{"name": e["name"], "description": e["description"], "source": "./plugins/" + e["name"],
                         "strict": False, "skills": ["./skills/" + s for s in sorted(e["skills"])],
                         "author": {"name": e["maintainer"]}, "license": e["license"],
                         "homepage": "https://github.com/%s/tree/%s" % (e["repo"], e["sha"])} for e in registry["plugins"]]}


def reject_links(root):
    if root.is_symlink() or any(p.is_symlink() for p in root.rglob("*")):
        raise SyncError("existing output contains a symlink")


def main():
    registry = read_json((ROOT / "registry.json").read_bytes())
    validate_registry(registry)
    for path in (ROOT / "plugins", ROOT / ".claude-plugin", ROOT / "CATALOG.md"):
        if path.exists() or path.is_symlink():
            reject_links(path)
    # Prepare and audit a complete generation before touching previous output.
    staged = pathlib.Path(tempfile.mkdtemp(prefix=".sync-stage-", dir=ROOT))
    preserve_stage = False
    try:
        for entry in registry["plugins"]:
            verify_ref(entry)
            files = prepare(entry, fetch(entry["repo"], entry["sha"]))
            for path, data in files.items():
                target = staged / "plugins" / entry["name"] / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        (staged / "registry.json").write_bytes((ROOT / "registry.json").read_bytes())
        market = staged / ".claude-plugin/marketplace.json"
        market.parent.mkdir()
        market.write_text(json.dumps(marketplace(registry), indent=2) + "\n", encoding="utf-8")
        rows = ["| %s | %s | %s | %s | [%s@%s](https://github.com/%s/tree/%s) | %s |" %
                (e["name"], ", ".join(sorted(e["skills"])), e["maintainer"], e["license"], e["repo"], e["sha"][:12], e["repo"], e["sha"], "; ".join(e["hosted_services"]) or "none") for e in registry["plugins"]]
        (staged / "CATALOG.md").write_text("# Catalog\n\nGenerated by tools/sync.py from registry.json. Do not edit by hand.\n\n| Plugin | Skills | Maintainer | License | Pinned source | External services |\n|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n", encoding="utf-8")
        import check
        failures, warnings, count = check.audit(staged)
        if failures:
            raise SyncError("staged plugin checks failed: " + "; ".join(failures))
        moved = []
        try:
            for relative in ("plugins", ".claude-plugin/marketplace.json", "CATALOG.md"):
                destination = ROOT / relative
                backup = staged / "backup" / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    os.replace(destination, backup)
                moved.append((destination, backup))
                os.replace(staged / relative, destination)
        except BaseException as original:
            # Preserve every remaining backup if recovery is interrupted or any
            # destination cannot be restored. Never auto-clean an incomplete rollback.
            preserve_stage = True
            rollback_failed = False
            for destination, backup in reversed(moved):
                try:
                    if destination.is_dir():
                        shutil.rmtree(destination)
                    elif destination.exists():
                        destination.unlink()
                    if backup.exists():
                        os.replace(backup, destination)
                except BaseException:
                    rollback_failed = True
            if rollback_failed:
                raise RollbackError(staged) from original
            preserve_stage = False
            raise
    finally:
        if not preserve_stage:
            shutil.rmtree(staged)
    print("synced %d plugin(s), %d skill(s); static checks only" % (len(registry["plugins"]), count))


if __name__ == "__main__":
    try:
        main()
    except RollbackError as error:
        # Only the generated recovery path is reported, with controls escaped.
        print("sync failed: " + str(error), file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError, tarfile.TarError) as error:
        # Never include request headers, credentials, or untrusted content.
        print("sync failed: " + type(error).__name__, file=sys.stderr)
        sys.exit(1)
