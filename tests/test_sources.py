"""Tests for fetching an image: the cover, and what can go wrong getting it."""

import unittest
import urllib.error
from pathlib import Path

from colophon.sources import SourceError, image
from tests.tempdir import TemporaryDirectory

# A JPEG's first bytes, which is what both sources actually serve.
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 200

URL = "https://assets.hardcover.app/external_data/40810017/cover.jpeg"


class Answering:
    """Stands in for the network: hands back these bytes, remembers the URL."""

    def __init__(self, body=JPEG, status=200, content_type="image/jpeg", error=None):
        self.body = body
        self.status = status
        self.content_type = content_type
        self.error = error
        self.sent = None

    def __call__(self, url, headers):
        self.sent = {"url": url, "headers": headers}
        if self.error is not None:
            raise self.error
        return self.status, self.body, self.content_type


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

    def test_nothing_to_fetch_is_not_an_error(self):
        """`fill` may leave a book almost alone; a source with no cover is normal."""
        self.assertIsNone(image(None, transport=Answering()))
        self.assertIsNone(image("", transport=Answering()))

    def test_an_http_error_is_a_source_problem(self):
        source = Answering(status=404, body=b"not found", content_type="text/html")

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
        source = Answering(body=b"<html>please log in</html>", content_type="text/html")

        with self.assertRaises(SourceError):
            image(URL, transport=source)

    def test_an_image_the_server_does_not_describe_is_still_an_image(self):
        """Google's thumbnails are described; a stand-in need not be."""
        source = Answering(body=JPEG, content_type=None)

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


if __name__ == "__main__":
    unittest.main()
