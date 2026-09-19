"""Tests for fetching an image: the cover, and what can go wrong getting it."""

import unittest
import unittest.mock
import urllib.error
from pathlib import Path

from colophon.sources import IMAGE_TIMEOUT_SECONDS, SourceError, image
from tests.tempdir import TemporaryDirectory

# A JPEG's first bytes, which is what both sources actually serve.
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 200

# A WebP: a real image to a browser, and one Colophon will not put in a book.
# `RIFF....WEBP` is the whole of what makes it one.
WEBP = b"RIFF$\x00\x00\x00WEBPVP8 " + b"\x00" * 32

HTML = b"<html><body>please log in</body></html>"

URL = "https://assets.hardcover.app/external_data/40810017/cover.jpeg"


class Answering:
    """Stands in for the network: hands back these bytes, remembers the call.

    Three arguments, because that is what the real fetch takes: the URL, the
    headers, and the timeout it was called with.
    """

    def __init__(self, body=JPEG, status=200, error=None):
        self.body = body
        self.status = status
        self.error = error
        self.sent = None

    def __call__(self, url, headers, timeout=None):
        self.sent = {"url": url, "headers": headers, "timeout": timeout}
        if self.error is not None:
            raise self.error
        return self.status, self.body


class FetchingAnImageTests(unittest.TestCase):
    def test_it_hands_back_the_bytes_the_server_sent(self):
        answer = Answering()

        found = image(URL, transport=answer)

        self.assertEqual(found, JPEG)
        self.assertEqual(answer.sent["url"], URL)

    def test_it_asks_for_an_image_and_says_who_is_asking(self):
        answer = Answering()

        image(URL, transport=answer)

        self.assertIn("Colophon", answer.sent["headers"]["User-Agent"])

    def test_the_timeout_it_was_given_is_the_one_the_fetch_gets(self):
        """Otherwise the parameter is decoration."""
        answer = Answering()

        image(URL, timeout=7, transport=answer)

        self.assertEqual(answer.sent["timeout"], 7)

    def test_the_timeout_has_a_default_that_is_actually_passed_on(self):
        answer = Answering()

        image(URL, transport=answer)

        self.assertEqual(answer.sent["timeout"], IMAGE_TIMEOUT_SECONDS)

    def test_nothing_to_fetch_is_not_an_error(self):
        """`fill` may leave a book almost alone; a source with no cover is normal."""
        self.assertIsNone(image(None, transport=Answering()))
        self.assertIsNone(image("", transport=Answering()))

    def test_an_http_error_is_a_source_problem(self):
        source = Answering(status=404, body=HTML[:9])

        with self.assertRaises(SourceError) as caught:
            image(URL, transport=source)

        self.assertIn("404", str(caught.exception))

    def test_a_server_that_cannot_be_reached_is_a_source_problem(self):
        broken = Answering(error=urllib.error.URLError("no route to host"))

        with self.assertRaises(SourceError) as caught:
            image(URL, transport=broken)

        self.assertIn("cover", str(caught.exception).lower())

    def test_a_reply_that_is_not_an_image_is_refused(self):
        """A sign-in page served with a 200 is not a cover."""
        source = Answering(body=HTML)

        with self.assertRaises(SourceError):
            image(URL, transport=source)

    def test_a_webp_is_refused_however_the_server_describes_it(self):
        """The header is not a second opinion: Colophon's writer cannot store one.

        WebP is a real image format, so `image/webp` is an honest thing for a
        server to say. It is still not a cover this book can have, and taking it
        because a header said "image" would only move the refusal to the writer,
        where the book is the thing that suffers.
        """
        source = Answering(body=WEBP)

        with self.assertRaises(SourceError) as caught:
            image(URL, transport=source)

        self.assertIn("not an image", str(caught.exception))

    def test_html_described_as_an_image_is_refused(self):
        """A server saying `image/jpeg` does not make an error page a cover."""
        source = Answering(body=HTML)

        with self.assertRaises(SourceError):
            image(URL, transport=source)

    def test_an_image_the_server_does_not_describe_is_still_an_image(self):
        """Google's thumbnails are described; a stand-in need not be."""
        source = Answering(body=JPEG)

        self.assertEqual(image(URL, transport=source), JPEG)

    def test_an_enormous_file_is_refused_rather_than_read_into_memory(self):
        source = Answering(body=b"\xff\xd8\xff" + b"\x00" * (6 * 1024 * 1024))

        with self.assertRaises(SourceError) as caught:
            image(URL, transport=source)

        self.assertIn("large", str(caught.exception))

    def test_an_empty_reply_is_not_a_cover(self):
        self.assertIsNone(image(URL, transport=Answering(body=b"")))


class FetchingFromDiskTests(unittest.TestCase):
    """The same seam, over a real URL, with no network and no stand-in.

    `image` left to itself is the one path the stand-ins never exercise, so this
    is what proves it fetches, follows the reply and hands back real bytes.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_the_real_fetch_reads_a_real_url(self):
        import http.server
        import threading

        folder = self.folder

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(folder), **kwargs)

            def log_message(self, *args):
                """Say nothing; a test's own output is noisy enough."""

        (self.folder / "cover.jpg").write_bytes(JPEG)
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        found = image(f"http://127.0.0.1:{server.server_port}/cover.jpg")

        self.assertEqual(found, JPEG)


class FetcherForTests(unittest.TestCase):
    """The one-argument fetch the corrector holds, with its timeout bound."""

    def test_it_is_called_with_a_url_and_bounds_the_timeout(self):
        from colophon.sources import fetcher_for

        asked = []

        def transport(url, headers, timeout):
            asked.append((url, timeout))
            return 200, JPEG

        fetch = fetcher_for(timeout=3)
        with unittest.mock.patch("colophon.sources._fetch", transport):
            self.assertEqual(fetch(URL), JPEG)

        self.assertEqual(asked, [(URL, 3)])

    def test_a_failure_comes_back_as_a_source_error(self):
        from colophon.sources import fetcher_for

        def transport(url, headers, timeout):
            raise OSError("no route to host")

        with (
            unittest.mock.patch("colophon.sources._fetch", transport),
            self.assertRaises(SourceError),
        ):
            fetcher_for()(URL)


if __name__ == "__main__":
    unittest.main()
