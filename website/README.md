# The Time Parallax — reader website

A small Flask site that turns the chapter files in this repository into a
readable, accessible online book. It reads the repository itself, so writing
is still just "add a file, commit, push" — nothing about the site needs to be
touched when a new chapter or a new translation lands.

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

So to publish a new chapter you commit a file named like the others. To start
a new translation, copy the folder name and append the language
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
| `DWFE_CACHE_TTL` | `300` | seconds before the chapter index is re-read |
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
* **Progress** — a progress bar, per-chapter position saved locally, a
  "Continue reading" button and a percentage badge on chapters already started.
* A print stylesheet renders the chapter as clean prose without the chrome.

Verified with axe-core (WCAG 2.1 A/AA plus best practices): zero violations on
the index, chapter, legal and error pages in the light, dark, sepia and
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

20 tests covering file-name parsing, language detection, prose parsing, HTML
escaping, the GitHub source (with stubbed HTTP), webhook signatures, refresh
tokens, and every route.

## Licence

The site code is part of this repository and shares its licence; the book text
it displays is © the authors under CC BY-NC-SA 4.0, and *Doctor Who* belongs to
the BBC. See [../LICENSE](../LICENSE).
