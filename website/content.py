"""Content layer for the Doctor Who fan-episode reader.

Chapters live in this repository as plain-text files, one file per chapter,
grouped into one folder per language edition, e.g.

    Doctor Who : The Time Parallax/Chapter I - Familiar Face
    Doctor Who : The Time Parallax Turkish/Bolum I - Tanidik Bir Yuz

Nothing here is hard-coded to those names: folders are discovered at runtime,
the language is inferred from the folder name suffix, and the chapter number
and title are parsed from the file name. Dropping a new chapter file (or a new
language folder) into the repository is all it takes for it to appear on the
site.

Two sources are supported:

  * ``local``  - read from a checkout on disk (fast, works offline)
  * ``github`` - read from the GitHub API / raw.githubusercontent.com, so a
                 deployed site picks up new chapters without a redeploy

``auto`` (the default) uses GitHub when it is reachable and falls back to the
local checkout otherwise.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Iterable

USER_AGENT = "doctor-who-fan-episodes-reader/1.0 (+https://github.com/MelihAydinYanibol/Doctor-Who-Fan-Episodes)"

# Folder-name suffixes that mark a translated edition. Anything not listed here
# is assumed to be the original English text. Add a line to support a new
# language; nothing else needs to change.
LANGUAGE_SUFFIXES: dict[str, str] = {
    "turkish": "tr",
    "turkce": "tr",
    "türkçe": "tr",
    "german": "de",
    "deutsch": "de",
    "french": "fr",
    "francais": "fr",
    "français": "fr",
    "spanish": "es",
    "espanol": "es",
    "español": "es",
    "italian": "it",
    "italiano": "it",
    "portuguese": "pt",
    "portugues": "pt",
    "português": "pt",
    "dutch": "nl",
    "nederlands": "nl",
    "polish": "pl",
    "polski": "pl",
    "russian": "ru",
    "japanese": "ja",
    "korean": "ko",
    "chinese": "zh",
    "arabic": "ar",
    "greek": "el",
    "swedish": "sv",
    "norwegian": "no",
    "danish": "da",
    "finnish": "fi",
    "czech": "cs",
    "hungarian": "hu",
    "romanian": "ro",
    "ukrainian": "uk",
    "hindi": "hi",
}

DEFAULT_LANGUAGE = "en"

# Words that introduce a chapter heading in a file name, in any supported
# language. Used to strip "Chapter"/"Bolum"/... before the number.
CHAPTER_WORDS = (
    "chapter",
    "bölüm",
    "bolum",
    "kapitel",
    "chapitre",
    "capitulo",
    "capítulo",
    "capitolo",
    "hoofdstuk",
    "rozdzia",
    "глава",
    "part",
    "episode",
    "ch",
)

TEXT_EXTENSIONS = {"", ".txt", ".md", ".markdown", ".text"}

ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}

# Words per minute used for the reading-time estimate.
WORDS_PER_MINUTE = 220


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def slugify(value: str) -> str:
    """URL-safe slug that survives Turkish characters."""
    value = value.replace("ı", "i").replace("İ", "i").replace("ş", "s")
    value = value.replace("ğ", "g").replace("ç", "c").replace("ö", "o").replace("ü", "u")
    value = _strip_accents(value).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "untitled"


def roman_to_int(value: str) -> int | None:
    value = value.strip().lower()
    if not value or any(ch not in ROMAN_VALUES for ch in value):
        return None
    total = 0
    previous = 0
    for ch in reversed(value):
        current = ROMAN_VALUES[ch]
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    return total or None


def _split_extension(name: str) -> tuple[str, str]:
    stem, dot, ext = name.rpartition(".")
    if not dot or len(ext) > 10 or " " in ext:
        return name, ""
    return stem, "." + ext.lower()


def detect_language(folder_name: str) -> tuple[str, str]:
    """Return ``(language_code, book_title)`` for a top-level content folder."""
    words = folder_name.split()
    if words:
        candidate = _strip_accents(words[-1]).lower().strip("()[]-_")
        raw_candidate = words[-1].lower().strip("()[]-_")
        code = LANGUAGE_SUFFIXES.get(candidate) or LANGUAGE_SUFFIXES.get(raw_candidate)
        if code:
            return code, " ".join(words[:-1]).strip(" -–—:")
    return DEFAULT_LANGUAGE, folder_name.strip()


def parse_chapter_name(file_name: str) -> tuple[int | None, str]:
    """Parse ``Chapter III - Anomaly`` into ``(3, "Anomaly")``."""
    stem, _ext = _split_extension(file_name)
    stem = stem.strip()

    pattern = re.compile(
        r"^\s*(?:(?P<word>[A-Za-zÀ-ÿıİşŞğĞçÇöÖüÜа-яА-Я]+)\s+)?"
        r"(?P<num>[IVXLCDMivxlcdm]+|\d+)\s*(?:[-–—:.]\s*|\s+)(?P<title>.+)$"
    )
    match = pattern.match(stem)
    if match:
        word = (match.group("word") or "").lower()
        word_ok = not word or any(_strip_accents(word).startswith(_strip_accents(w)) for w in CHAPTER_WORDS)
        if word_ok:
            raw_num = match.group("num")
            number = int(raw_num) if raw_num.isdigit() else roman_to_int(raw_num)
            if number is not None:
                return number, match.group("title").strip(" -–—:")

    leading = re.match(r"^\s*(\d+)\s*[-–—_.]\s*(.+)$", stem)
    if leading:
        return int(leading.group(1)), leading.group(2).strip()

    return None, stem


def _normalise_for_compare(value: str) -> str:
    value = _strip_accents(value.replace("ı", "i").replace("İ", "i")).lower()
    return re.sub(r"[^a-z0-9]+", "", value)


# --------------------------------------------------------------------------
# prose parsing
# --------------------------------------------------------------------------

_INLINE_STRONG = re.compile(r"\*\*(?P<text>[^*\n]+)\*\*")
_INLINE_EM = re.compile(r"(?<![\w*])\*(?P<text>[^*\n]+)\*(?![\w*])")
_INLINE_LINK = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<href>https?://[^\s)]+)\)")
_SCENE_BREAK = re.compile(r"^\s*(?:\*\s*){1,7}$|^\s*[-–—_]{3,}\s*$|^\s*#{1,6}\s*$")


def _inline_html(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = _INLINE_LINK.sub(
        lambda m: '<a href="{href}" rel="noopener noreferrer nofollow" target="_blank">{text}</a>'.format(
            href=html.escape(m.group("href"), quote=True), text=m.group("text")
        ),
        escaped,
    )
    escaped = _INLINE_STRONG.sub(lambda m: f"<strong>{m.group('text')}</strong>", escaped)
    escaped = _INLINE_EM.sub(lambda m: f"<em>{m.group('text')}</em>", escaped)
    return escaped


def _looks_like_heading(line: str, title: str, number: int | None) -> bool:
    """True when the first line of a file merely repeats the chapter heading."""
    if len(line) > 140:
        return False
    normalised = _normalise_for_compare(line)
    if not normalised:
        return False
    if _normalise_for_compare(title) and _normalise_for_compare(title) in normalised:
        return True
    lowered = _strip_accents(line).lower()
    if number is not None and any(lowered.startswith(_strip_accents(w)) for w in CHAPTER_WORDS):
        return True
    return False


@dataclass
class Block:
    kind: str  # "p" | "scene" | "break"
    html: str = ""
    text: str = ""


def parse_prose(raw: str, title: str, number: int | None) -> tuple[list[Block], int]:
    """Turn a plain-text chapter into renderable blocks plus a word count."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text)]
    paragraphs = [p for p in paragraphs if p]

    if paragraphs and _looks_like_heading(paragraphs[0].split("\n")[0].strip(), title, number):
        first = paragraphs[0]
        lines = [ln for ln in first.split("\n") if ln.strip()]
        if len(lines) == 1:
            paragraphs = paragraphs[1:]
        else:
            paragraphs[0] = "\n".join(lines[1:])

    blocks: list[Block] = []
    words = 0
    for paragraph in paragraphs:
        collapsed = re.sub(r"[ \t]+", " ", paragraph).strip()
        if _SCENE_BREAK.match(collapsed):
            if blocks and blocks[-1].kind != "break":
                blocks.append(Block(kind="break"))
            continue

        joined = " ".join(line.strip() for line in collapsed.split("\n") if line.strip())
        words += len(joined.split())

        # Scene setters in these files are short lines flagged with a trailing
        # asterisk, e.g. "1 Billion Years Later, At somewhere in space. *".
        scene = False
        if joined.endswith("*") and len(joined) <= 200:
            joined = joined[:-1].rstrip()
            scene = True
        elif joined.startswith("*") and joined.endswith("*") and joined.count("*") == 2:
            joined = joined.strip("*").strip()
            scene = True

        blocks.append(
            Block(kind="scene" if scene else "p", html=_inline_html(joined), text=joined)
        )

    while blocks and blocks[-1].kind == "break":
        blocks.pop()
    return blocks, words


# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------


@dataclass
class FileEntry:
    name: str
    path: str
    sha: str
    size: int = 0


class ContentSourceError(RuntimeError):
    pass


class LocalSource:
    """Reads chapters from a checkout on disk."""

    name = "local"

    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    def describe(self) -> str:
        return f"local:{self.root}"

    def _entry(self, path: str, rel: str) -> FileEntry:
        stat = os.stat(path)
        return FileEntry(
            name=os.path.basename(rel),
            path=rel,
            sha=f"{int(stat.st_mtime)}-{stat.st_size}",
            size=stat.st_size,
        )

    def snapshot(self) -> tuple[dict[str, list[FileEntry]], list[FileEntry]]:
        if not os.path.isdir(self.root):
            raise ContentSourceError(f"content root does not exist: {self.root}")
        folders: dict[str, list[FileEntry]] = {}
        root_files: list[FileEntry] = []
        for name in sorted(os.listdir(self.root)):
            if name.startswith(".") or name in {"website", "node_modules", "__pycache__"}:
                continue
            full = os.path.join(self.root, name)
            if os.path.isdir(full):
                entries = []
                for child in sorted(os.listdir(full)):
                    if child.startswith("."):
                        continue
                    child_path = os.path.join(full, child)
                    if os.path.isfile(child_path):
                        entries.append(self._entry(child_path, f"{name}/{child}"))
                if entries:
                    folders[name] = entries
            elif os.path.isfile(full):
                root_files.append(self._entry(full, name))
        return folders, root_files

    def read(self, entry: FileEntry) -> str:
        full = os.path.join(self.root, *entry.path.split("/"))
        with open(full, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()


class GitHubSource:
    """Reads chapters straight from GitHub so new commits show up by themselves."""

    name = "github"

    def __init__(self, repo: str, branch: str = "main", token: str | None = None, timeout: float = 10.0):
        self.repo = repo
        self.branch = branch
        self.token = token
        self.timeout = timeout

    def describe(self) -> str:
        return f"github:{self.repo}@{self.branch}"

    def _request(self, url: str, accept: str) -> bytes:
        request = urllib.request.Request(url)
        request.add_header("User-Agent", USER_AGENT)
        request.add_header("Accept", accept)
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            raise ContentSourceError(f"GitHub request failed for {url}: {exc}") from exc

    def _contents(self, path: str = "") -> list[dict]:
        quoted = urllib.parse.quote(path, safe="/")
        url = f"https://api.github.com/repos/{self.repo}/contents/{quoted}?ref={urllib.parse.quote(self.branch)}"
        payload = self._request(url, "application/vnd.github+json")
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, list):
            raise ContentSourceError(f"unexpected GitHub response for {path!r}")
        return data

    def snapshot(self) -> tuple[dict[str, list[FileEntry]], list[FileEntry]]:
        folders: dict[str, list[FileEntry]] = {}
        root_files: list[FileEntry] = []
        for item in self._contents(""):
            name = item.get("name", "")
            if name.startswith(".") or name in {"website", "node_modules"}:
                continue
            if item.get("type") == "dir":
                entries = [
                    FileEntry(
                        name=child["name"],
                        path=child["path"],
                        sha=child.get("sha", ""),
                        size=int(child.get("size") or 0),
                    )
                    for child in self._contents(item["path"])
                    if child.get("type") == "file" and not child["name"].startswith(".")
                ]
                if entries:
                    folders[name] = sorted(entries, key=lambda e: e.name)
            elif item.get("type") == "file":
                root_files.append(
                    FileEntry(
                        name=name,
                        path=item["path"],
                        sha=item.get("sha", ""),
                        size=int(item.get("size") or 0),
                    )
                )
        return folders, root_files

    def read(self, entry: FileEntry) -> str:
        quoted = urllib.parse.quote(entry.path, safe="/")
        url = f"https://raw.githubusercontent.com/{self.repo}/{urllib.parse.quote(self.branch)}/{quoted}"
        return self._request(url, "text/plain").decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# library model
# --------------------------------------------------------------------------


@dataclass
class Chapter:
    number: int | None
    order: int
    slug: str
    title: str
    language: str
    book_slug: str
    entry: FileEntry

    @property
    def label_key(self) -> str:
        return "chapter_number"


@dataclass
class Edition:
    language: str
    folder: str
    chapters: list[Chapter] = field(default_factory=list)

    def by_slug(self, slug: str) -> Chapter | None:
        for chapter in self.chapters:
            if chapter.slug == slug:
                return chapter
        return None


@dataclass
class Book:
    slug: str
    title: str
    editions: dict[str, Edition] = field(default_factory=dict)

    @property
    def languages(self) -> list[str]:
        return sorted(self.editions.keys())

    def edition(self, language: str) -> Edition | None:
        return self.editions.get(language)


@dataclass
class Library:
    books: list[Book] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    docs: dict[str, FileEntry] = field(default_factory=dict)
    source: str = ""
    fetched_at: float = 0.0
    error: str | None = None

    @property
    def source_display(self) -> str:
        """Source label safe to show visitors (never a filesystem path)."""
        if self.source.startswith("local:"):
            return "the repository checkout"
        if self.source.startswith("github:"):
            return "GitHub (" + self.source[len("github:") :] + ")"
        return self.source

    def book(self, slug: str) -> Book | None:
        for book in self.books:
            if book.slug == slug:
                return book
        return None

    def books_for(self, language: str) -> list[Book]:
        return [book for book in self.books if language in book.editions]


class ContentService:
    """Builds and caches the library, and lazily fetches chapter bodies."""

    def __init__(
        self,
        local_root: str,
        github_repo: str | None = None,
        github_branch: str = "main",
        github_token: str | None = None,
        mode: str = "auto",
        ttl: float = 300.0,
    ):
        self.mode = mode
        self.ttl = ttl
        self.local = LocalSource(local_root)
        self.github = GitHubSource(github_repo, github_branch, github_token) if github_repo else None
        self._lock = threading.RLock()
        self._library: Library | None = None
        self._body_cache: dict[str, tuple[list[Block], int]] = {}
        self._source = None

    # -- source selection ---------------------------------------------------

    def _sources(self) -> Iterable:
        if self.mode == "local":
            return [self.local]
        if self.mode == "github":
            if not self.github:
                raise ContentSourceError("DWFE_SOURCE=github but no repository configured")
            return [self.github]
        return [s for s in (self.github, self.local) if s is not None]

    # -- public API ---------------------------------------------------------

    def library(self, force: bool = False) -> Library:
        with self._lock:
            fresh = (
                self._library is not None
                and not force
                and (time.time() - self._library.fetched_at) < self.ttl
            )
            if fresh:
                return self._library
            try:
                library = self._build()
            except ContentSourceError as exc:
                if self._library is not None:
                    # Keep serving the last good snapshot rather than 500ing.
                    self._library.error = str(exc)
                    self._library.fetched_at = time.time()
                    return self._library
                library = Library(source="none", fetched_at=time.time(), error=str(exc))
            self._library = library
            return library

    def refresh(self) -> Library:
        return self.library(force=True)

    def blocks(self, chapter: Chapter) -> tuple[list[Block], int]:
        cache_key = f"{chapter.entry.path}@{chapter.entry.sha}"
        with self._lock:
            cached = self._body_cache.get(cache_key)
        if cached is not None:
            return cached

        raw = self._read(chapter.entry)
        parsed = parse_prose(raw, chapter.title, chapter.number)
        with self._lock:
            if len(self._body_cache) > 256:
                self._body_cache.clear()
            self._body_cache[cache_key] = parsed
        return parsed

    def read_doc(self, entry: FileEntry) -> str:
        return self._read(entry)

    def reading_minutes(self, words: int) -> int:
        return max(1, round(words / WORDS_PER_MINUTE))

    # -- internals ----------------------------------------------------------

    def _read(self, entry: FileEntry) -> str:
        errors = []
        for source in self._sources():
            try:
                return source.read(entry)
            except ContentSourceError as exc:
                errors.append(str(exc))
        raise ContentSourceError("; ".join(errors) or "no content source available")

    def _build(self) -> Library:
        errors = []
        for source in self._sources():
            try:
                folders, root_files = source.snapshot()
            except ContentSourceError as exc:
                errors.append(str(exc))
                continue
            self._source = source
            return self._assemble(folders, root_files, source.describe())
        raise ContentSourceError("; ".join(errors) or "no content source available")

    def _assemble(self, folders, root_files, source_label: str) -> Library:
        books: dict[str, Book] = {}
        languages: set[str] = set()

        for folder_name, entries in folders.items():
            chapters_raw = [e for e in entries if _split_extension(e.name)[1] in TEXT_EXTENSIONS]
            if not chapters_raw:
                continue
            language, book_title = detect_language(folder_name)
            book_slug = slugify(book_title)
            languages.add(language)
            book = books.setdefault(book_slug, Book(slug=book_slug, title=book_title))
            if language not in book.editions or len(book_title) > len(book.title):
                book.title = book_title or book.title

            parsed = []
            for entry in chapters_raw:
                number, title = parse_chapter_name(entry.name)
                parsed.append((number, title, entry))

            parsed.sort(key=lambda item: (item[0] is None, item[0] or 0, item[2].name))

            edition = Edition(language=language, folder=folder_name)
            for index, (number, title, entry) in enumerate(parsed, start=1):
                effective = number if number is not None else index
                # Slugs are numeric so the same chapter has the same URL in
                # every language, which makes the language switch lossless.
                slug = f"chapter-{effective}" if number is not None else f"c{index}-{slugify(title)}"
                edition.chapters.append(
                    Chapter(
                        number=number,
                        order=index,
                        slug=slug,
                        title=title,
                        language=language,
                        book_slug=book_slug,
                        entry=entry,
                    )
                )
            book.editions[language] = edition

        docs: dict[str, FileEntry] = {}
        for entry in root_files:
            key = _split_extension(entry.name)[0].lower()
            if key in {"readme", "license", "licence", "notice", "credits", "authors"}:
                docs.setdefault("license" if key == "licence" else key, entry)

        ordered_books = sorted(books.values(), key=lambda b: b.title.lower())
        ordered_languages = sorted(languages, key=lambda code: (code != DEFAULT_LANGUAGE, code))
        return Library(
            books=ordered_books,
            languages=ordered_languages,
            docs=docs,
            source=source_label,
            fetched_at=time.time(),
        )


def signature_ok(secret: str, body: bytes, header: str | None) -> bool:
    """Constant-time check of a GitHub ``X-Hub-Signature-256`` header."""
    import hmac

    if not header or not header.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, header[len("sha256=") :])
