"""Tests for the reader.

    python -m unittest discover -s website

They build a throwaway repository on disk so the suite never depends on the
network or on the real chapter files.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

from app import create_app
from content import (
    ContentService,
    find_cover,
    GitHubSource,
    detect_language,
    parse_chapter_name,
    parse_prose,
    signature_ok,
    slugify,
)
from markdown_lite import render_document


def build_fixture(root: str) -> None:
    english = os.path.join(root, "My Book")
    turkish = os.path.join(root, "My Book Turkish")
    os.makedirs(english)
    os.makedirs(turkish)

    with open(os.path.join(english, "Chapter I - Alpha"), "w", encoding="utf-8") as handle:
        handle.write(
            "Chapter I – Alpha\n\nFirst paragraph. \n\nSomewhere else entirely. *\n\n*\n\nLast words.\n"
        )
    with open(os.path.join(english, "Chapter II - Beta"), "w", encoding="utf-8") as handle:
        handle.write("Chapter 2 – Beta\n\nEnglish only.\n")
    with open(os.path.join(turkish, "Bölüm I - Alfa"), "w", encoding="utf-8") as handle:
        handle.write("Bölüm I – Alfa\n\nİlk paragraf.\n")

    # A 1x1 GIF is enough to prove the banner pipeline end to end.
    with open(os.path.join(english, "banner.gif"), "wb") as handle:
        handle.write(
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
            b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
            b"\x00\x00\x02\x02D\x01\x00;"
        )

    with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("## License\n\nA *fan work*. See [CC](https://example.com/cc).\n")
    with open(os.path.join(root, "LICENSE"), "w", encoding="utf-8") as handle:
        handle.write("CC BY-NC-SA 4.0\n\n  Share — copy it\n  Adapt — remix it\n")


class ParsingTests(unittest.TestCase):
    def test_chapter_names(self):
        self.assertEqual(parse_chapter_name("Chapter I - Familiar Face"), (1, "Familiar Face"))
        self.assertEqual(parse_chapter_name("Chapter III - Anomaly"), (3, "Anomaly"))
        self.assertEqual(parse_chapter_name("Chapter 12 – Something"), (12, "Something"))
        self.assertEqual(parse_chapter_name("Bölüm II - Hiç Yaşanmamış"), (2, "Hiç Yaşanmamış"))
        self.assertEqual(parse_chapter_name("Chapter IV - Anomaly.txt"), (4, "Anomaly"))
        self.assertEqual(parse_chapter_name("Prologue"), (None, "Prologue"))

    def test_language_detection(self):
        self.assertEqual(detect_language("Doctor Who : The Time Parallax"), ("en", "Doctor Who : The Time Parallax"))
        self.assertEqual(detect_language("Doctor Who : The Time Parallax Turkish"), ("tr", "Doctor Who : The Time Parallax"))
        self.assertEqual(detect_language("A Book German"), ("de", "A Book"))

    def test_slugify_handles_turkish(self):
        self.assertEqual(slugify("Hiç Yaşanmamış Bir Hayat"), "hic-yasanmamis-bir-hayat")

    def test_prose_parsing(self):
        raw = "Chapter I – Alpha\n\nOne. \n\nA place, later. *\n\n*\n\nTwo.\n"
        blocks, words = parse_prose(raw, "Alpha", 1)
        kinds = [block.kind for block in blocks]
        self.assertEqual(kinds, ["p", "scene", "break", "p"])
        self.assertEqual(blocks[1].html, "A place, later.")
        self.assertEqual(words, 6)

    def test_prose_escapes_html(self):
        blocks, _ = parse_prose("T\n\nHe said <script>alert(1)</script> quietly.", "T", 1)
        self.assertIn("&lt;script&gt;", blocks[0].html)
        self.assertNotIn("<script>", blocks[0].html)

    def test_markdown_and_plaintext(self):
        html = render_document("## Hi\n\nA *fan work*. [CC](https://example.com)\n", "README.md")
        self.assertIn("<h3>Hi</h3>", html)
        self.assertIn("<em>fan work</em>", html)
        self.assertIn('href="https://example.com"', html)
        plain = render_document("Line one\nLine two\n", "LICENSE")
        self.assertIn("Line one<br>Line two", plain)

    def test_find_cover_prefers_banner_and_ignores_prose(self):
        from content import FileEntry

        def entry(name):
            return FileEntry(name=name, path=name, sha="x")

        files = [entry("Chapter I - Alpha"), entry("cover.png"), entry("banner.jpg")]
        self.assertEqual(find_cover(files).name, "banner.jpg")
        self.assertEqual(find_cover([entry("Kapak.webp")]).name, "Kapak.webp")
        self.assertEqual(find_cover([entry("banner-wide.png")]).name, "banner-wide.png")
        self.assertIsNone(find_cover([entry("Chapter I - Alpha"), entry("notes.png")]))

    def test_webhook_signature(self):
        body = b'{"ref":"refs/heads/main"}'
        import hashlib
        import hmac

        digest = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        self.assertTrue(signature_ok("s3cret", body, "sha256=" + digest))
        self.assertFalse(signature_ok("s3cret", body, "sha256=deadbeef"))
        self.assertFalse(signature_ok("s3cret", body, None))


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        build_fixture(self.root)
        self.service = ContentService(local_root=self.root, mode="local", ttl=0)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_editions_are_grouped_into_one_book(self):
        library = self.service.library()
        self.assertEqual([book.slug for book in library.books], ["my-book"])
        book = library.books[0]
        self.assertEqual(sorted(book.editions), ["en", "tr"])
        self.assertEqual([c.slug for c in book.editions["en"].chapters], ["chapter-1", "chapter-2"])
        self.assertEqual(book.editions["tr"].chapters[0].slug, "chapter-1")

    def test_cover_is_found_and_shared_across_editions(self):
        book = self.service.library().books[0]
        self.assertEqual(book.editions["en"].cover.name, "banner.gif")
        self.assertIsNone(book.editions["tr"].cover)
        # The Turkish edition has no artwork of its own, so it borrows the one
        # that exists rather than falling back to the generated banner.
        self.assertEqual(book.cover_for("tr"), ("en", book.editions["en"].cover))
        self.assertEqual(book.cover_for("en")[0], "en")

    def test_cover_is_not_mistaken_for_a_chapter(self):
        slugs = [c.slug for c in self.service.library().books[0].editions["en"].chapters]
        self.assertEqual(slugs, ["chapter-1", "chapter-2"])

    def test_hue_is_stable_for_a_title(self):
        book = self.service.library().books[0]
        self.assertEqual(book.hue, self.service.refresh().books[0].hue)
        self.assertTrue(0 <= book.hue < 360)

    def test_docs_are_discovered(self):
        library = self.service.library()
        self.assertEqual(sorted(library.docs), ["license", "readme"])

    def test_new_chapter_appears_after_refresh(self):
        self.assertEqual(len(self.service.library().books[0].editions["en"].chapters), 2)
        path = os.path.join(self.root, "My Book", "Chapter III - Gamma")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("Chapter III – Gamma\n\nBrand new.\n")
        library = self.service.refresh()
        self.assertEqual(len(library.books[0].editions["en"].chapters), 3)

    def test_local_edits_appear_without_waiting_for_the_ttl(self):
        # A long TTL must not hold back a checkout on disk: re-listing it costs
        # a fraction of a millisecond, so an edit shows up on the next request.
        service = ContentService(local_root=self.root, mode="local", ttl=300, local_ttl=0)
        chapter = service.library().books[0].editions["en"].chapters[0]
        self.assertIn("First paragraph.", [b.text for b in service.blocks(chapter)[0]])

        path = os.path.join(self.root, "My Book", "Chapter I - Alpha")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("Chapter I – Alpha\n\nRewritten entirely.\n")

        chapter = service.library().books[0].editions["en"].chapters[0]
        texts = [b.text for b in service.blocks(chapter)[0]]
        self.assertIn("Rewritten entirely.", texts)
        self.assertNotIn("First paragraph.", texts)

    def test_a_new_local_chapter_appears_without_waiting(self):
        service = ContentService(local_root=self.root, mode="local", ttl=300, local_ttl=0)
        self.assertEqual(len(service.library().books[0].editions["en"].chapters), 2)
        with open(os.path.join(self.root, "My Book", "Chapter III - Gamma"), "w", encoding="utf-8") as handle:
            handle.write("Chapter III – Gamma\n\nBrand new.\n")
        self.assertEqual(len(service.library().books[0].editions["en"].chapters), 3)

    def test_the_ttl_still_guards_github(self):
        # With GitHub in play the TTL must hold, or an unreachable API would be
        # retried — and time out — on every single request.
        remote = ContentService(
            local_root=self.root, github_repo="Owner/Repo", mode="auto", ttl=300, local_ttl=0
        )
        self.assertEqual(remote.effective_ttl(), 300)

        forced = ContentService(
            local_root=self.root, github_repo="Owner/Repo", mode="github", ttl=300, local_ttl=0
        )
        self.assertEqual(forced.effective_ttl(), 300)

        local_only = ContentService(local_root=self.root, mode="local", ttl=300, local_ttl=0)
        self.assertEqual(local_only.effective_ttl(), 0)

        # And the local TTL is a knob, not a hard-coded zero.
        throttled = ContentService(local_root=self.root, mode="local", ttl=300, local_ttl=30)
        self.assertEqual(throttled.effective_ttl(), 30)

    def test_last_good_snapshot_survives_a_broken_source(self):
        self.service.library()
        self.service.local.root = os.path.join(self.root, "gone")
        library = self.service.library(force=True)
        self.assertTrue(library.books)
        self.assertIsNotNone(library.error)


class GitHubSourceTests(unittest.TestCase):
    def test_snapshot_and_read_use_the_expected_urls(self):
        listings = {
            "": [
                {"name": "My Book", "path": "My Book", "type": "dir"},
                {"name": "README.md", "path": "README.md", "type": "file", "sha": "a", "size": 3},
                {"name": "website", "path": "website", "type": "dir"},
            ],
            "My Book": [
                {
                    "name": "Chapter I - Alpha",
                    "path": "My Book/Chapter I - Alpha",
                    "type": "file",
                    "sha": "b",
                    "size": 9,
                }
            ],
        }
        seen = []

        def fake_request(self, url, accept):
            seen.append(url)
            if "raw.githubusercontent.com" in url:
                return b"Chapter I - Alpha\n\nHello.\n"
            path = "My Book" if "My%20Book" in url else ""
            return json.dumps(listings[path]).encode("utf-8")

        original = GitHubSource._request
        GitHubSource._request = fake_request
        try:
            source = GitHubSource("Owner/Repo", "main")
            folders, root_files = source.snapshot()
            self.assertEqual(list(folders), ["My Book"])
            self.assertEqual([f.name for f in root_files], ["README.md"])
            body = source.read(folders["My Book"][0])
            self.assertIn("Hello.", body)
        finally:
            GitHubSource._request = original

        self.assertFalse(any("website" in url for url in seen), "the website folder must not be crawled")
        self.assertTrue(any(url.startswith("https://raw.githubusercontent.com/Owner/Repo/main/") for url in seen))


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        build_fixture(self.root)
        os.environ.update(DWFE_SOURCE="local", DWFE_CONTENT_ROOT=self.root, DWFE_CACHE_TTL="0")
        self.client = create_app().test_client()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        for key in ("DWFE_SOURCE", "DWFE_CONTENT_ROOT", "DWFE_CACHE_TTL"):
            os.environ.pop(key, None)

    def test_root_redirects_to_a_language(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/en/", response.headers["Location"])
        # The redirect must not stamp the language cookie: a guess from the
        # browser's headers is not a choice, and the cookie would suppress the
        # picker on the page the reader actually lands on.
        self.assertNotIn("dwfe_lang", response.headers.get("Set-Cookie", ""))

    def test_the_picker_survives_the_root_redirect(self):
        self.client.get("/")
        body = self.client.get("/en/").get_data(as_text=True)
        self.assertIn('id="language-dialog"', body)

    def test_library_index_lists_books_not_chapters(self):
        body = self.client.get("/en/").get_data(as_text=True)
        self.assertIn('href="/en/book/my-book"', body)
        self.assertIn("My Book", body)
        self.assertNotIn("chapter-1", body)

    def test_book_page_lists_chapters(self):
        body = self.client.get("/en/book/my-book").get_data(as_text=True)
        self.assertIn("/en/read/my-book/chapter-1", body)
        self.assertIn("Alpha", body)

    def test_unknown_book_is_a_404(self):
        self.assertEqual(self.client.get("/en/book/no-such-book").status_code, 404)

    def test_chapter_renders(self):
        response = self.client.get("/en/read/my-book/chapter-1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("First paragraph.", response.get_data(as_text=True))

    def test_cover_is_served_with_an_etag(self):
        response = self.client.get("/cover/my-book/en")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/gif")
        self.assertTrue(response.get_data().startswith(b"GIF89a"))
        cached = self.client.get("/cover/my-book/en", headers={"If-None-Match": response.headers["ETag"]})
        self.assertEqual(cached.status_code, 304)

    def test_missing_cover_is_a_404(self):
        self.assertEqual(self.client.get("/cover/my-book/tr").status_code, 404)
        self.assertEqual(self.client.get("/cover/nope/en").status_code, 404)

    def test_generated_banner_is_used_when_a_book_has_no_artwork(self):
        body = self.client.get("/tr/").get_data(as_text=True)
        # Turkish borrows the English artwork, so the fallback needs its own book.
        os.makedirs(os.path.join(self.root, "Second Book"))
        with open(os.path.join(self.root, "Second Book", "Chapter I - Solo"), "w", encoding="utf-8") as handle:
            handle.write("Chapter I - Solo\n\nAlone.\n")
        body = self.client.get("/en/").get_data(as_text=True)
        self.assertIn("book-banner-generated", body)
        self.assertIn("banner-title", body)

    def test_turkish_chapter_declares_its_language(self):
        body = self.client.get("/tr/read/my-book/chapter-1").get_data(as_text=True)
        self.assertIn('lang="tr"', body)
        self.assertIn("İlk paragraf.", body)

    def test_untranslated_chapter_offers_the_language_that_has_it(self):
        response = self.client.get("/tr/read/my-book/chapter-2")
        self.assertEqual(response.status_code, 404)
        self.assertIn("/en/read/my-book/chapter-2", response.get_data(as_text=True))

    def test_first_visit_is_asked_to_pick_a_language(self):
        body = self.client.get("/en/").get_data(as_text=True)
        self.assertIn('id="language-dialog"', body)
        # Every language is offered, and the note tells them it is not final.
        self.assertIn("/tr/", body)
        self.assertIn("change this whenever you like", body)

    def test_the_picker_is_asked_once_and_then_never_again(self):
        first = self.client.get("/en/")
        self.assertIn('id="language-dialog"', first.get_data(as_text=True))
        # The same client keeps the cookie the first response set.
        second = self.client.get("/en/")
        self.assertNotIn('id="language-dialog"', second.get_data(as_text=True))

    def test_a_link_that_names_a_language_is_not_second_guessed(self):
        body = self.client.get("/en/?lang=en").get_data(as_text=True)
        self.assertNotIn('id="language-dialog"', body)

    def test_the_picker_shows_on_a_chapter_landed_on_directly(self):
        body = self.client.get("/tr/read/my-book/chapter-1").get_data(as_text=True)
        self.assertIn('id="language-dialog"', body)

    def test_no_picker_when_there_is_only_one_language(self):
        root = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(root, "Solo Book"))
            with open(os.path.join(root, "Solo Book", "Chapter I - One"), "w", encoding="utf-8") as handle:
                handle.write("Chapter I - One\n\nAlone.\n")
            os.environ["DWFE_CONTENT_ROOT"] = root
            client = create_app().test_client()
            self.assertNotIn('id="language-dialog"', client.get("/en/").get_data(as_text=True))
        finally:
            os.environ["DWFE_CONTENT_ROOT"] = self.root
            shutil.rmtree(root, ignore_errors=True)

    def test_legal_page_shows_repository_documents(self):
        body = self.client.get("/en/legal").get_data(as_text=True)
        self.assertIn("README.md", body)
        self.assertIn("LICENSE", body)
        self.assertIn("CC BY-NC-SA 4.0", body)

    def test_api_and_health(self):
        payload = self.client.get("/api/library").get_json()
        self.assertEqual(payload["languages"], ["en", "tr"])
        self.assertTrue(self.client.get("/healthz").get_json()["ok"])

    def test_webhook_requires_a_valid_signature_when_configured(self):
        os.environ["DWFE_WEBHOOK_SECRET"] = "s3cret"
        try:
            client = create_app().test_client()
            unsigned = client.post("/webhook/github", data=b"{}", headers={"X-GitHub-Event": "push"})
            self.assertEqual(unsigned.status_code, 403)
        finally:
            os.environ.pop("DWFE_WEBHOOK_SECRET", None)

    def test_refresh_token_is_enforced_when_configured(self):
        os.environ["DWFE_REFRESH_TOKEN"] = "letmein"
        try:
            client = create_app().test_client()
            self.assertEqual(client.post("/api/refresh").status_code, 403)
            ok = client.post("/api/refresh", headers={"X-Refresh-Token": "letmein"})
            self.assertEqual(ok.status_code, 200)
        finally:
            os.environ.pop("DWFE_REFRESH_TOKEN", None)


if __name__ == "__main__":
    unittest.main()
