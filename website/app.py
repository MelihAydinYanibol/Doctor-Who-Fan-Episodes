"""Flask reader for the Doctor Who fan-episode repository.

Run it:

    pip install -r requirements.txt
    python app.py                 # http://127.0.0.1:5000

Configuration (all optional, all via environment variables):

    DWFE_SOURCE          auto | local | github        (default: auto)
    DWFE_CONTENT_ROOT    path to the repository checkout (default: ../)
    DWFE_GITHUB_REPO     owner/name (default: MelihAydinYanibol/Doctor-Who-Fan-Episodes)
    DWFE_GITHUB_BRANCH   branch to read (default: main)
    DWFE_GITHUB_TOKEN    optional token, raises the GitHub API rate limit
    DWFE_CACHE_TTL       seconds between automatic re-reads (default: 300)
    DWFE_LOCAL_CACHE_TTL same, for a local checkout, where re-reading is cheap
                         (default: 0 — edits appear as soon as they are saved)
    DWFE_REFRESH_TOKEN   shared secret for POST /api/refresh
    DWFE_WEBHOOK_SECRET  secret for the GitHub push webhook at /webhook/github
"""

from __future__ import annotations

import datetime as _dt
import os

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from content import (
    DEFAULT_LANGUAGE,
    ContentService,
    ContentSourceError,
    content_type_for,
    signature_ok,
)
from i18n import LANGUAGE_NAMES, language_name, text_direction, translator
from markdown_lite import render_document

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONTENT_ROOT = os.path.dirname(BASE_DIR)
LANG_COOKIE = "dwfe_lang"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        CONTENT_ROOT=os.environ.get("DWFE_CONTENT_ROOT", DEFAULT_CONTENT_ROOT),
        SOURCE=os.environ.get("DWFE_SOURCE", "auto").strip().lower(),
        GITHUB_REPO=os.environ.get("DWFE_GITHUB_REPO", "MelihAydinYanibol/Doctor-Who-Fan-Episodes"),
        GITHUB_BRANCH=os.environ.get("DWFE_GITHUB_BRANCH", "main"),
        GITHUB_TOKEN=os.environ.get("DWFE_GITHUB_TOKEN") or None,
        CACHE_TTL=float(os.environ.get("DWFE_CACHE_TTL", "300")),
        LOCAL_CACHE_TTL=float(os.environ.get("DWFE_LOCAL_CACHE_TTL", "0")),
        REFRESH_TOKEN=os.environ.get("DWFE_REFRESH_TOKEN") or None,
        WEBHOOK_SECRET=os.environ.get("DWFE_WEBHOOK_SECRET") or None,
        JSON_AS_ASCII=False,
    )

    service = ContentService(
        local_root=app.config["CONTENT_ROOT"],
        github_repo=app.config["GITHUB_REPO"],
        github_branch=app.config["GITHUB_BRANCH"],
        github_token=app.config["GITHUB_TOKEN"],
        mode=app.config["SOURCE"],
        ttl=app.config["CACHE_TTL"],
        local_ttl=app.config["LOCAL_CACHE_TTL"],
    )
    app.extensions["content"] = service

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def pick_language(requested: str | None = None) -> str:
        library = service.library()
        available = library.languages or [DEFAULT_LANGUAGE]
        for candidate in (
            requested,
            request.args.get("lang"),
            request.cookies.get(LANG_COOKIE),
        ):
            if candidate and candidate in available:
                return candidate
        header = request.accept_languages.best_match(available)
        if header:
            return header
        return DEFAULT_LANGUAGE if DEFAULT_LANGUAGE in available else available[0]

    def base_context(language: str) -> dict:
        library = service.library()
        updated = (
            _dt.datetime.fromtimestamp(library.fetched_at, _dt.timezone.utc)
            if library.fetched_at
            else None
        )
        books = library.books_for(language) or library.books
        translate = translator(language)
        if library.source.startswith("github:"):
            source_label = translate("source_github", repo=library.source[len("github:"):])
        elif library.source.startswith("local:"):
            source_label = translate("source_local")
        else:
            source_label = library.source_display
        return {
            "lang": language,
            "t": translate,
            "library": library,
            "books": books,
            "primary_book": books[0] if books else None,
            "languages": library.languages,
            "language_name": language_name,
            "source_label": source_label,
            "dir": text_direction(language),
            "updated_iso": updated.isoformat(timespec="seconds") if updated else "",
            "updated_human": updated.strftime("%d %b %Y, %H:%M UTC") if updated else "",
            "current_endpoint": request.endpoint,
            "view_args": dict(request.view_args or {}),
            # Nobody has told us which language they want yet: no saved choice
            # and no ?lang= on the link they followed. Every response sets the
            # cookie, so the picker is offered once and never nags again.
            "first_visit": LANG_COOKIE not in request.cookies and not request.args.get("lang"),
            # Handed to the browser as JSON: notifications are composed in the
            # page, but the wording has to come from here to stay translated.
            # Fetched without kwargs so the {placeholders} survive for JS.
            "notification_strings": {
                "one": translate("notification_title"),
                "many": translate("notification_title_many"),
                "body": translate("notification_body"),
                "bannerOne": translate("new_chapters_one"),
                "bannerMany": translate("new_chapters_many"),
                "subscribed": translate("subscribe_done"),
                "unsubscribed": translate("unsubscribe_done"),
                "blocked": translate("subscribe_blocked"),
                "unsupported": translate("subscribe_unsupported"),
                "chapterNumber": translate("chapter_number"),
                "restartBody": translate("restart_body"),
            },
        }

    def language_variants(book_slug: str | None, chapter_slug: str | None) -> list[dict]:
        """Where the language switcher should send the reader for each language."""
        library = service.library()
        variants = []
        for code in library.languages:
            target = url_for("index", lang=code)
            # "exact" means the switch lands on the same thing you are reading.
            # On a non-book page the library index *is* the same thing.
            exact = book_slug is None
            if book_slug:
                book = library.book(book_slug)
                edition = book.edition(code) if book else None
                if edition:
                    if chapter_slug and edition.by_slug(chapter_slug):
                        target = url_for(
                            "chapter", lang=code, book_slug=book_slug, chapter_slug=chapter_slug
                        )
                        exact = True
                    else:
                        target = url_for("book_page", lang=code, book_slug=book_slug)
                        exact = not chapter_slug
            variants.append(
                {
                    "code": code,
                    "name": language_name(code),
                    "url": target,
                    "exact": exact,
                }
            )
        return variants

    def with_language_cookie(response: Response, language: str) -> Response:
        response.set_cookie(
            LANG_COOKIE,
            language,
            max_age=60 * 60 * 24 * 365,
            samesite="Lax",
            httponly=False,
        )
        return response

    def chapter_payload(book, edition, chapter):
        blocks, words = service.blocks(chapter)
        chapters = edition.chapters
        position = chapters.index(chapter)
        return {
            "book": book,
            "edition": edition,
            "chapter": chapter,
            "blocks": blocks,
            "words": words,
            "minutes": service.reading_minutes(words),
            "previous": chapters[position - 1] if position > 0 else None,
            "next": chapters[position + 1] if position + 1 < len(chapters) else None,
            "position": position + 1,
            "total": len(chapters),
        }

    # ------------------------------------------------------------------
    # routes
    # ------------------------------------------------------------------

    @app.route("/")
    def root():
        # Deliberately no cookie here: guessing a language from the browser's
        # headers is not the reader choosing one, and stamping the cookie on
        # the redirect would suppress the first-visit picker on the page it
        # lands on. The rendered page sets it.
        return redirect(url_for("index", lang=pick_language()))

    def shelf_entry(book, language: str) -> dict | None:
        """Everything the library grid needs for one book."""
        edition = book.edition(language) or (
            book.editions[book.languages[0]] if book.languages else None
        )
        if edition is None:
            return None
        cover = book.cover_for(language)
        return {
            "book": book,
            "edition": edition,
            "chapters": len(edition.chapters),
            "first": edition.chapters[0] if edition.chapters else None,
            "cover_url": url_for("cover", book_slug=book.slug, lang=cover[0]) if cover else None,
            "translated": edition.language == language,
            "languages": book.languages,
        }

    @app.route("/<lang>/")
    def index(lang: str):
        library = service.library()
        if library.languages and lang not in library.languages:
            return redirect(url_for("index", lang=pick_language()))
        context = base_context(lang)
        context["shelf"] = [
            entry for entry in (shelf_entry(book, lang) for book in library.books) if entry
        ]
        context["language_variants"] = language_variants(None, None)
        response = make_response(render_template("index.html", **context))
        return with_language_cookie(response, lang)

    @app.route("/<lang>/book/<book_slug>")
    def book_page(lang: str, book_slug: str):
        library = service.library()
        book = library.book(book_slug)
        if book is None:
            abort(404)
        edition = book.edition(lang) or (
            book.editions[book.languages[0]] if book.languages else None
        )
        if edition is None:
            abort(404)
        cover = book.cover_for(lang)
        context = base_context(lang)
        context.update(
            book=book,
            edition=edition,
            cover_url=url_for("cover", book_slug=book.slug, lang=cover[0]) if cover else None,
            language_variants=language_variants(book_slug, None),
        )
        response = make_response(render_template("book.html", **context))
        return with_language_cookie(response, lang)

    @app.route("/cover/<book_slug>/<lang>")
    def cover(book_slug: str, lang: str):
        """Serve a book's banner from whichever source the library came from."""
        library = service.library()
        book = library.book(book_slug)
        edition = book.edition(lang) if book else None
        entry = edition.cover if edition else None
        if entry is None:
            abort(404)

        etag = f'"{entry.sha}"'
        if request.headers.get("If-None-Match") == etag:
            return Response(status=304, headers={"ETag": etag})
        try:
            data = service.read_binary(entry)
        except ContentSourceError:
            abort(404)
        response = Response(data, mimetype=content_type_for(entry.name))
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "public, max-age=3600"
        return response

    @app.route("/<lang>/read/<book_slug>/<chapter_slug>")
    def chapter(lang: str, book_slug: str, chapter_slug: str):
        library = service.library()
        book = library.book(book_slug)
        if book is None:
            abort(404)

        edition = book.edition(lang)
        if edition is None:
            # Language exists on the site but not for this book: show what does.
            fallback = book.languages[0] if book.languages else DEFAULT_LANGUAGE
            return redirect(url_for("chapter", lang=fallback, book_slug=book_slug, chapter_slug=chapter_slug))

        current = edition.by_slug(chapter_slug)
        if current is None:
            elsewhere = [
                code
                for code, other in book.editions.items()
                if other.by_slug(chapter_slug) is not None
            ]
            if not elsewhere:
                abort(404)
            context = base_context(lang)
            context.update(
                book=book,
                missing_slug=chapter_slug,
                available_languages=elsewhere,
                language_variants=language_variants(book_slug, chapter_slug),
            )
            response = make_response(render_template("missing.html", **context), 404)
            return with_language_cookie(response, lang)

        try:
            payload = chapter_payload(book, edition, current)
        except ContentSourceError:
            abort(503)

        context = base_context(lang)
        context.update(payload)
        context["language_variants"] = language_variants(book_slug, chapter_slug)
        response = make_response(render_template("chapter.html", **context))
        return with_language_cookie(response, lang)

    @app.route("/<lang>/legal")
    def legal(lang: str):
        library = service.library()
        documents = []
        for key in ("readme", "license", "notice"):
            entry = library.docs.get(key)
            if not entry:
                continue
            try:
                raw = service.read_doc(entry)
            except ContentSourceError:
                continue
            documents.append(
                {
                    "key": key,
                    "name": entry.name,
                    "html": render_document(raw, entry.name),
                    "path": entry.path,
                }
            )
        context = base_context(lang)
        context.update(documents=documents, language_variants=language_variants(None, None))
        response = make_response(render_template("legal.html", **context))
        return with_language_cookie(response, lang)

    # ------------------------------------------------------------------
    # machine-readable endpoints
    # ------------------------------------------------------------------

    @app.route("/api/library")
    def api_library():
        library = service.library()
        return jsonify(
            {
                "source": library.source_display,
                "fetched_at": library.fetched_at,
                "error": library.error,
                "languages": library.languages,
                "books": [
                    {
                        "slug": book.slug,
                        "title": book.title,
                        "cover": (
                            url_for("cover", book_slug=book.slug, lang=book.cover_for(book.languages[0])[0])
                            if book.languages and book.cover_for(book.languages[0])
                            else None
                        ),
                        "editions": {
                            code: [
                                {
                                    "slug": chapter.slug,
                                    "number": chapter.number,
                                    "title": chapter.title,
                                    "path": chapter.entry.path,
                                    "url": url_for(
                                        "chapter",
                                        lang=code,
                                        book_slug=book.slug,
                                        chapter_slug=chapter.slug,
                                    ),
                                }
                                for chapter in edition.chapters
                            ]
                            for code, edition in book.editions.items()
                        },
                    }
                    for book in library.books
                ],
            }
        )

    @app.route("/api/refresh", methods=["POST"])
    def api_refresh():
        token = app.config["REFRESH_TOKEN"]
        if token:
            supplied = request.headers.get("X-Refresh-Token") or request.args.get("token")
            if supplied != token:
                abort(403)
        library = service.refresh()
        return jsonify(
            {
                "ok": library.error is None,
                "source": library.source_display,
                "error": library.error,
                "chapters": sum(
                    len(edition.chapters) for book in library.books for edition in book.editions.values()
                ),
            }
        )

    @app.route("/webhook/github", methods=["POST"])
    def github_webhook():
        secret = app.config["WEBHOOK_SECRET"]
        body = request.get_data()
        if secret and not signature_ok(secret, body, request.headers.get("X-Hub-Signature-256")):
            abort(403)
        event = request.headers.get("X-GitHub-Event", "")
        if event == "ping":
            return jsonify({"ok": True, "pong": True})
        if event != "push":
            return jsonify({"ok": True, "ignored": event})
        library = service.refresh()
        return jsonify({"ok": True, "source": library.source_display, "error": library.error})

    @app.route("/healthz")
    def healthz():
        library = service.library()
        return jsonify(
            {
                "ok": bool(library.books),
                "source": library.source_display,
                "books": len(library.books),
                "error": library.error,
            }
        )

    # ------------------------------------------------------------------
    # errors and template globals
    # ------------------------------------------------------------------

    @app.errorhandler(404)
    def not_found(_error):
        language = pick_language()
        context = base_context(language)
        context["language_variants"] = language_variants(None, None)
        return render_template("error.html", code=404, **context), 404

    @app.errorhandler(503)
    def unavailable(_error):
        language = pick_language()
        context = base_context(language)
        context["language_variants"] = language_variants(None, None)
        return render_template("error.html", code=503, **context), 503

    @app.context_processor
    def inject_globals():
        return {
            "all_language_names": LANGUAGE_NAMES,
            "repo_url": f"https://github.com/{app.config['GITHUB_REPO']}",
        }

    @app.after_request
    def add_headers(response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "public, max-age=3600")
        return response

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("DWFE_HOST", "127.0.0.1"),
        port=int(os.environ.get("DWFE_PORT", "5000")),
        debug=_env_bool("DWFE_DEBUG", False),
    )
