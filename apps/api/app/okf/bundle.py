"""Google's Open Knowledge Format, v0.2 — the generic part: a bundle is a directory of markdown
concept files with YAML frontmatter, plus optional `index.md` (listings) and `log.md` (history)
in any directory. Spec: github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md

This module reads and writes concepts deterministically (the same content gives the same bytes,
so git diffs show only real changes), checks conformance (spec §11), regenerates indexes,
appends to the log, and commits the bundle's own git repository.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

OKF_VERSION = "0.2"
RESERVED = ("index.md", "log.md")
# Frontmatter keys in a stable order: OKF's own first (spec §4.1, §5), then producer extensions.
KEY_ORDER = ("type", "title", "description", "resource", "tags", "status", "generated", "verified", "stale_after",
             "sources", "usage_window")


@dataclass
class Concept:
    id: str  # its path in the bundle without ".md", e.g. "colleges/x/fees-2026-27"
    meta: dict
    body: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def type(self) -> str | None:
        return self.meta.get("type")


class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper, value: str):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str)


def dump_meta(meta: dict) -> str:
    ordered = {k: meta[k] for k in KEY_ORDER if k in meta}
    ordered.update({k: v for k, v in meta.items() if k not in ordered})
    return yaml.dump(ordered, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=1000,
                     default_flow_style=False)


def render(concept: Concept) -> str:
    body = concept.body.strip("\n")
    return f"---\n{dump_meta(concept.meta)}---\n\n{body}\n" if body else f"---\n{dump_meta(concept.meta)}---\n"


def parse(text: str, concept_id: str) -> Concept:
    if not text.startswith("---\n"):
        return Concept(concept_id, {}, text, ["no frontmatter"])
    end = text.find("\n---\n", 4)
    if end < 0 and text.rstrip().endswith("\n---"):
        end = len(text.rstrip()) - 4
    if end < 0:
        return Concept(concept_id, {}, text, ["frontmatter not closed"])
    try:
        meta = yaml.load(text[4:end], Loader=yaml.CSafeLoader) or {}
    except yaml.YAMLError as e:
        return Concept(concept_id, {}, text[end + 5:], [f"frontmatter isn't valid YAML: {e}"])
    if not isinstance(meta, dict):
        return Concept(concept_id, {}, text[end + 5:], ["frontmatter isn't a mapping"])
    return Concept(concept_id, meta, text[end + 5:].lstrip("\n"))


def path_of(root: Path, concept_id: str) -> Path:
    return root / f"{concept_id}.md"


def read(root: Path, concept_id: str) -> Concept | None:
    path = path_of(root, concept_id)
    return parse(path.read_text(encoding="utf-8"), concept_id) if path.is_file() else None


def write(root: Path, concept: Concept) -> bool:
    """Writes the concept; returns whether the file changed."""
    path = path_of(root, concept.id)
    text = render(concept)
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def concepts(root: Path, under: str | None = None):
    base = root / under if under else root
    for path in sorted(base.rglob("*.md")):
        if path.name in RESERVED or ".git" in path.parts:
            continue
        concept_id = path.relative_to(root).with_suffix("").as_posix()
        yield parse(path.read_text(encoding="utf-8"), concept_id)


def check(root: Path) -> list[str]:
    """OKF §11: every concept has parseable frontmatter with a non-empty `type`; a root index may
    declare okf_version; other index files carry no frontmatter."""
    problems = []
    for concept in concepts(root):
        problems += [f"{concept.id}: {p}" for p in concept.problems]
        if not concept.problems and not str(concept.type or "").strip():
            problems.append(f"{concept.id}: no type")
    for index in sorted(root.rglob("index.md")):
        if ".git" in index.parts:
            continue
        text = index.read_text(encoding="utf-8")
        if text.startswith("---\n") and index.parent != root:
            problems.append(f"{index.relative_to(root)}: only the bundle-root index may have frontmatter")
    return problems


# ---------------- indexes and the log ----------------

def write_indexes(root: Path, sections: dict[str, str] | None = None) -> None:
    """An index.md in every directory, listing its concepts (title — description) and
    subdirectories (spec §8). The root one declares okf_version. `sections` names the headings
    used for top-level directories."""
    sections = sections or {}
    root.mkdir(parents=True, exist_ok=True)
    directories = {p.parent for p in root.rglob("*.md") if ".git" not in p.parts} | {root}
    for directory in sorted(directories):
        if ".git" in directory.parts:
            continue
        lines = []
        items = []
        for path in sorted(directory.glob("*.md")):
            if path.name in RESERVED:
                continue
            c = parse(path.read_text(encoding="utf-8"), path.stem)
            title = c.meta.get("title") or path.stem
            items.append(f"* [{title}]({path.name})" + (f" - {c.meta['description']}" if c.meta.get("description") else ""))
        subdirs = sorted(d for d in directory.iterdir() if d.is_dir() and d.name != ".git" and any(d.rglob("*.md")))
        if items:
            lines += ["# Concepts", "", *items, ""]
        if subdirs:
            heading = sections.get(directory.relative_to(root).as_posix(), "Contents") if directory != root else "Contents"
            lines += [f"# {heading}", ""]
            for d in subdirs:
                note = sections.get(d.relative_to(root).as_posix())
                lines.append(f"* [{d.name}]({d.name}/)" + (f" - {note}" if note else ""))
            lines.append("")
        text = "\n".join(lines)
        if directory == root:
            text = f'---\nokf_version: "{OKF_VERSION}"\n---\n\n' + text
        target = directory / "index.md"
        if not target.is_file() or target.read_text(encoding="utf-8") != text:
            target.write_text(text, encoding="utf-8")


def append_log(root: Path, entries: list[str], day: date, directory: str = "") -> None:
    """Adds entries under today's date heading in log.md, newest first (spec §9)."""
    if not entries:
        return
    path = (root / directory / "log.md") if directory else root / "log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.is_file() else "# Update log\n"
    heading = f"## {day.isoformat()}"
    lines = text.rstrip("\n").split("\n")
    new = [f"* {e}" for e in entries]
    if heading in lines:
        at = lines.index(heading) + 1
        lines[at:at] = new
    else:
        at = 1
        while at < len(lines) and not lines[at].startswith("## "):
            at += 1
        lines[at:at] = ["", heading, *new] if lines[at - 1] != "" else [heading, *new, ""]
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")


# ---------------- one writer at a time ----------------

class locked:
    """Held around every write to the bundle (write, commit, load), so jobs running side by side
    never interleave their changes or trip over git's own lock."""

    def __init__(self, root: Path):
        self.path = Path(root).parent / f".{Path(root).name}.lock"

    def __enter__(self):
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "w")
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        import fcntl

        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()


# ---------------- git ----------------

GIT_IDENTITY = ("-c", "user.name=MAYA knowledge pipeline", "-c", "user.email=maya-pipeline@localhost")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *GIT_IDENTITY, *args], cwd=root, capture_output=True, text=True, check=False)


def ensure_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    if not (root / ".git").exists():
        _git(root, "init", "-q", "-b", "main")


def head(root: Path) -> str | None:
    result = _git(root, "rev-parse", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def commit(root: Path, message: str) -> str | None:
    """Commits everything that changed; returns the new commit, or None when nothing did."""
    ensure_repo(root)
    _git(root, "add", "-A")
    if _git(root, "diff", "--cached", "--quiet").returncode == 0:
        return None
    result = _git(root, "commit", "-q", "-m", message)
    if result.returncode != 0:
        raise RuntimeError(f"git commit failed: {result.stderr.strip()}")
    return head(root)


def changed_since(root: Path, since: str | None) -> list[str] | None:
    """Concept ids changed (added, modified or deleted) since a commit; None means "everything"
    (no commit to compare with, or it isn't in the history any more)."""
    if not since or _git(root, "cat-file", "-e", f"{since}^{{commit}}").returncode != 0:
        return None
    result = _git(root, "diff", "--name-only", since, "HEAD")
    return sorted({p[:-3] for p in result.stdout.split() if p.endswith(".md") and Path(p).name not in RESERVED})
