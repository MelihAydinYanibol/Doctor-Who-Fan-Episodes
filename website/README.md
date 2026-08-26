# Fan Episodes — reader website

A small Flask site that turns the folders in this repository into a shelf of
books you can read online. It reads the repository itself, so writing is still
just "add a file, commit, push" — nothing about the site needs to be touched
when a new chapter, a new translation, or a whole new book lands.

```
website/
├── app.py             Flask routes
├── content.py         finds chapters (local checkout or GitHub) and parses the prose
├── i18n.py            interface translations (English, Turkish) + language names
├── markdown_lite.py   tiny Markdown/plain-text renderer for README and LICENSE
├── test_reader.py     unit tests (no network, no fixtures on the real book)
├── templates/         Jinja templates
└── static/            stylesheet, reader script, favicon
```

## Quick start

```bash
cd website
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000
```

By default it reads the checkout it lives in, so it works offline.

## How the site is laid out

* `/<lang>/` — the library: one card per book, each with its banner, the
  languages it exists in and how far you have read it.
* `/<lang>/book/<book>` — that book's hero and chapter list.
* `/<lang>/read/<book>/<chapter>` — the chapter itself.
* `/<lang>/legal` — the notice and licence, rendered from the repository.

## Book banners

Put an image called `banner`, `cover`, `poster`, `art`, `hero` or `kapak` (any
of `.jpg`, `.png`, `.webp`, `.avif`, `.gif`, `.svg`) in a book's folder and it
becomes that book's banner on the shelf and the backdrop of its book page.
Landscape art works best — the card crops to 16:9.

A book with no image is not left blank: the site generates a banner from the
title itself, on a colour derived from the book's name, so every book on the
shelf looks deliberate from the first commit. If only one language edition has
artwork, the other editions borrow it.

Banners are served through `/cover/<book>/<lang>` from whichever source the
library came from — so a GitHub-backed deployment picks up new artwork the same
way it picks up new chapters — and carry an ETag so browsers re-download them
only when the file actually changes.

## How chapters are found

Nothing is hard-coded. At startup (and on every refresh) the reader scans the
top level of the repository:

* Each folder that contains text files is a **book edition**.
* The language comes from the last word of the folder name —
  `... Turkish` → `tr`, anything unrecognised → `en`. Folders whose names match
  apart from that word are treated as the same book in two languages, which is
  what makes the language switcher land on the same chapter.
* The chapter number and title come from the file name:
  `Chapter III - Anomaly` → chapter 3, "Anomaly". Roman or Arabic numerals,
  `Chapter`/`Bölüm`/`Kapitel`/`Chapitre`/… all work, and a file extension is
  optional.
* Inside a file, the first line is dropped when it just repeats the chapter
  heading; blank lines separate paragraphs; a short line ending in `*` is
  rendered as a scene setter; a line of `*` or `---` becomes a scene break.

So to publish a new chapter you commit a file named like the others, and a new
book is simply a new folder — it appears on the shelf on the next refresh. To
start a new translation, copy the folder name and append the language
(`My Book German`) — add the language to `LANGUAGE_SUFFIXES` in `content.py`
first if it isn't one of the two dozen already listed. Interface strings fall
back to English for languages that have no entry in `i18n.py`, so a new
translation is readable immediately.

## Pulling new chapters from GitHub automatically

`DWFE_SOURCE` picks where chapters come from:

| value | behaviour |
| --- | --- |
| `auto` (default) | try GitHub, fall back to the local checkout if it is unreachable |
| `local` | only the checkout on disk |
| `github` | only the GitHub API / `raw.githubusercontent.com` |

In `auto` or `github` mode the site notices new commits by itself. Three
things can trigger the re-read, and all of them are safe to combine:

1. **Time.** The chapter index is re-read when it is older than
   `DWFE_CACHE_TTL` seconds (default 300). Chapter bodies are cached by their
   git blob SHA, so a refresh only downloads what actually changed.

   Reading from a checkout on disk skips the wait entirely: re-listing it
   takes about 0.08 ms, so the index is rebuilt on every request and an edit
   to a chapter shows up as soon as you save it. The TTL is there to spare the
   GitHub API, so it still applies whenever GitHub is in play — including
   `auto` mode, where an unreachable API would otherwise be retried, and time
   out, on every request. `DWFE_LOCAL_CACHE_TTL` throttles the local rebuild
   if you ever need it to.
2. **A push webhook.** Point a GitHub webhook at `POST /webhook/github`
   (content type `application/json`, secret = `DWFE_WEBHOOK_SECRET`) and the
   site refreshes the moment you push. The signature is verified; unsigned
   requests are rejected whenever a secret is configured.
3. **By hand.** The "Check for new chapters" button on the index calls
   `POST /api/refresh`. Set `DWFE_REFRESH_TOKEN` to require
   `X-Refresh-Token` on that endpoint if the site is public.

If GitHub is unreachable during a refresh, the last good snapshot keeps being
served and the error is shown quietly in the footer — the site never goes down
because the API rate limit was hit.

## Configuration

All optional, all environment variables:

| variable | default | meaning |
| --- | --- | --- |
| `DWFE_SOURCE` | `auto` | `auto`, `local` or `github` |
| `DWFE_CONTENT_ROOT` | the repository root | where to read chapters from on disk |
| `DWFE_GITHUB_REPO` | `MelihAydinYanibol/Doctor-Who-Fan-Episodes` | `owner/name` |
| `DWFE_GITHUB_BRANCH` | `main` | branch to read |
| `DWFE_GITHUB_TOKEN` | — | optional; raises the API rate limit from 60/h to 5000/h |
| `DWFE_CACHE_TTL` | `300` | seconds before the chapter index is re-read from GitHub |
| `DWFE_LOCAL_CACHE_TTL` | `0` | the same, for a checkout on disk — zero means edits appear at once |
| `DWFE_REFRESH_TOKEN` | — | required header for `POST /api/refresh` |
| `DWFE_WEBHOOK_SECRET` | — | GitHub webhook secret |
| `DWFE_HOST` / `DWFE_PORT` | `127.0.0.1` / `5000` | dev server binding |

## Reading and accessibility features

Everything below is available without an account and saved per browser in
`localStorage`; the site works with JavaScript disabled too, just without the
preferences.

* **Themes** — system, light, dark, sepia, and a black/yellow high-contrast
  theme. The system option follows `prefers-color-scheme`, and the choice is
  applied before first paint so there is no flash.
* **Typefaces** — serif, sans, monospace, and a dyslexia-friendly option
  (OpenDyslexic or Atkinson Hyperlegible when installed, Verdana otherwise,
  with extra letter and word spacing).
* **Text size, line spacing, letter spacing, word spacing, paragraph spacing,
  line width and alignment** — all adjustable independently, which covers the
  WCAG 1.4.12 "text spacing" criteria directly rather than by zooming.
* **Focus mode** dims every paragraph except the one in the reading zone;
  **reduce motion and effects** turns off transitions, blur and gradients (and
  `prefers-reduced-motion` is honoured regardless).
* **Read aloud** using the browser's own speech synthesis, paragraph by
  paragraph, highlighting and scrolling as it goes, in the language of the
  text being read.
* **Keyboard** — `←`/`→` previous and next chapter, `s` settings, `d` cycle
  theme, `+`/`-` text size, `l` read aloud. A skip link, visible focus rings,
  landmarks, live-region announcements and `lang` on every translated block
  make screen-reader and keyboard-only use practical.
* **Language** — a first-time visitor is asked once which language they want
  to read in, with a note that it can be changed at any time from the menu in
  the header. The prompt is rendered already open so it works without
  JavaScript, and is upgraded to a modal (focus trap, backdrop, Esc to close)
  when scripting is available. It is skipped when the link already names a
  language (`?lang=`), when a choice is already stored, and when the library
  only has one language.
* **Progress** — a progress bar, per-chapter position saved locally, a
  "Continue reading" card on the shelf, a progress bar on each book card and a
  percentage badge on chapters already started. Progress is tracked per
  language, so a Turkish page never offers to resume an English chapter.
* A print stylesheet renders the chapter as clean prose without the chrome.

Verified with axe-core (WCAG 2.1 A/AA plus best practices): zero violations on
the library, book, chapter, legal and error pages in the light, dark, sepia and
high-contrast themes, in both languages. The one deliberate exception is focus
mode, whose whole purpose is to dim the paragraphs you are not reading; it is
off by default and the active paragraph always stays at full contrast.

## Deploying

```bash
pip install -r requirements.txt gunicorn
DWFE_SOURCE=github DWFE_CACHE_TTL=300 \
  gunicorn -w 2 -b 0.0.0.0:8000 app:app
```

`app:app` is a normal WSGI application, so anything that runs Flask (Fly.io,
Railway, Render, a VPS behind nginx, Docker) will serve it. In `github` mode
the container does not need a checkout of the book at all. `GET /healthz`
reports whether chapters are loading, for uptime checks.

## Tests

```bash
cd website && python -m unittest discover
```

30 tests covering file-name parsing, language detection, banner discovery,
prose parsing, HTML escaping, the GitHub source (with stubbed HTTP), webhook
signatures, refresh tokens, and every route.

## Licence

The site code is part of this repository and shares its licence; the book text
it displays is © the authors under CC BY-NC-SA 4.0, and *Doctor Who* belongs to
the BBC. See [../LICENSE](../LICENSE).
