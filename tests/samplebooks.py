"""Small EPUBs built to order, for the cases the Gutenberg fixtures do not cover.

Tests write their metadata out in full, because the difference between an
EPUB 2 identifier and an EPUB 3 one is the whole point of some of them.
"""

import zipfile
from pathlib import Path

GUTENBERG_DIR = Path(__file__).parent / "fixtures" / "books"

PACKAGE = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:opf="http://www.idpf.org/2007/opf"
         xmlns:calibre="http://calibre.kovidgoyal.net/2009/metadata"
         version="{version}" unique-identifier="bookid">
  <metadata>
{metadata}
  </metadata>
  <manifest>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter"/>
  </spine>
</package>
"""

CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

CHAPTER = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Cragside</p></body></html>
"""

KEPUB_CHAPTER = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<p><span class="koboSpan" id="kobo.1.1">Cragside</span></p>
</body></html>
"""

# Metadata blocks tests point at, so the EPUB 2 and EPUB 3 shapes are visible
# in the test rather than buried in a builder.
SIMPLE = "    <dc:title>Cragside</dc:title>\n    <dc:creator>LJ Ross</dc:creator>"

ISBN = "9781521748831"

# A book as it arrives: the title still carries the series and the number, the
# author is spelt the way the file has it, and there is an ISBN to look up.
AS_DOWNLOADED = f"""    <dc:title>Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)</dc:title>
    <dc:creator>L. J. Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <dc:language>en</dc:language>
"""

# The same three DCI Ryan books as they arrive with no ISBN in them, which is
# the case CBO-36 exists for: the title is matched after cleaning, and the
# series number in the bracket is not what identifies the book. Belsay's title
# carries no number at all, and its series number is only on Hardcover.
CRAGSIDE = """    <dc:title>Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)</dc:title>
    <dc:creator>L. J. Ross</dc:creator>
    <dc:language>en</dc:language>
"""

BERWICK = """    <dc:title>Berwick: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 24)</dc:title>
    <dc:creator>L. J. Ross</dc:creator>
    <dc:language>en</dc:language>
"""

BELSAY = """    <dc:title>Belsay: A DCI Ryan Mystery</dc:title>
    <dc:creator>L. J. Ross</dc:creator>
    <dc:language>en</dc:language>
"""

# The lookalike: the same author, a different book of hers.
THE_INFIRMARY = """    <dc:title>The Infirmary: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 11)</dc:title>
    <dc:creator>L. J. Ross</dc:creator>
    <dc:language>en</dc:language>
"""

# A book that says nothing about who wrote it, so there is nothing to compare.
WITHOUT_AUTHOR = """    <dc:title>Cragside</dc:title>
    <dc:language>en</dc:language>
"""

# The series' first book, for the tests where the file is genuinely not among
# the candidates a source offered: the author agrees and no title does, so the
# rules score it 0.6 and cannot decide - which is what the LLM is for.
HOLY_ISLAND = """    <dc:title>Holy Island: A DCI Ryan Mystery</dc:title>
    <dc:creator>L. J. Ross</dc:creator>
    <dc:language>en</dc:language>
"""

# The same book with the initials run together, which is how a file often spells
# an author a source spaces out, and the other way round from AS_DOWNLOADED.
INITIALS_WITHOUT_STOPS = """    <dc:title>Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)</dc:title>
    <dc:creator>LJ Ross</dc:creator>
    <dc:language>en</dc:language>
"""

# A book that says nothing about its author or its language either.
WITHOUT_AUTHOR_OR_LANGUAGE = """    <dc:title>Cragside</dc:title>
"""

# A subtitle that names the book rather than describing it, so it comes off for
# searching - and a record that may still be carrying it.
SAPIENS = """    <dc:title>Sapiens: A Brief History of Humankind</dc:title>
    <dc:creator>Yuval Noah Harari</dc:creator>
    <dc:language>en</dc:language>
"""

TWO_CREATORS = """    <dc:title>Cragside</dc:title>
    <dc:creator id="author_0">LJ Ross</dc:creator>
    <dc:creator id="author_1">Someone Else</dc:creator>
    <meta property="role" refines="#author_0" scheme="marc:relators">aut</meta>
    <meta property="role" refines="#author_1" scheme="marc:relators">aut</meta>
    <meta property="file-as" refines="#author_0">Ross, LJ</meta>
"""

EXISTING_SERIES_COLLECTION = """    <dc:title>Cragside</dc:title>
    <meta property="belongs-to-collection" id="series-1">Old Series</meta>
    <meta property="collection-type" refines="#series-1">series</meta>
    <meta property="group-position" refines="#series-1">1</meta>
"""
# A book that arrived with everything the design spec's "fill if empty" rules
# care about already on it, so a rule can be shown to leave each one alone.
WITH_THE_OTHER_FIELDS = f"""    <dc:title>Cragside</dc:title>
    <dc:creator>LJ Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <dc:language>en</dc:language>
    <dc:description>A house full of secrets.</dc:description>
    <dc:publisher>Ulverscroft</dc:publisher>
    <dc:date>2019-01-01</dc:date>
"""

# The bare essentials of a PNG: the eight byte signature every one starts with.
# Enough for a test to show the bytes were copied into the book unchanged, and
# small enough to read in a diff.
PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89"
)

# A JPEG, which is what both sources actually serve, so the media type is read
# off the bytes rather than assumed from what the book already had.
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 8 + b"\xff\xd9"

A_BOXED_SET = """    <dc:title>Cragside</dc:title>
    <meta property="belongs-to-collection" id="set-1">The Complete DCI Ryan</meta>
    <meta property="collection-type" refines="#set-1">set</meta>
"""

DRM = """<?xml version="1.0"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
            xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
  <enc:EncryptedData>
    <enc:EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/>
    <enc:CipherData><enc:CipherReference URI="OEBPS/content.opf"/></enc:CipherData>
  </enc:EncryptedData>
</encryption>
"""

OBFUSCATED_FONT = """<?xml version="1.0"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
            xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
  <enc:EncryptedData>
    <enc:EncryptionMethod Algorithm="http://www.idpf.org/2008/embedding"/>
    <enc:CipherData><enc:CipherReference URI="OEBPS/fonts/body.otf"/></enc:CipherData>
  </enc:EncryptedData>
</encryption>
"""


def write_epub(path, metadata, version="3.0", content=CHAPTER, extra_entries=()):
    """Write a minimal, valid EPUB whose package document holds this metadata."""
    path = Path(path)
    with zipfile.ZipFile(path, "w") as book:
        book.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        book.writestr("META-INF/container.xml", CONTAINER)
        book.writestr("OEBPS/content.opf", PACKAGE.format(version=version, metadata=metadata))
        book.writestr("OEBPS/chapter.xhtml", content)
        for name, body in extra_entries:
            book.writestr(name, body)
    return path


def add_isbn(path, isbn):
    """Put an ISBN into a book that arrived without one.

    A real Gutenberg EPUB carries no ISBN, so this is how a real book gets taken
    through a lookup. It edits the package document by hand rather than through
    the code under test, so the fixture is not set up by the thing being tested.
    """
    path = Path(path)
    with zipfile.ZipFile(path) as book:
        entries = [(entry, book.read(entry.filename)) for entry in book.infolist()]

    with zipfile.ZipFile(path, "w") as book:
        for entry, body in entries:
            if entry.filename.endswith(".opf"):
                body = _with_isbn(body, isbn)
            written = zipfile.ZipInfo(entry.filename, entry.date_time)
            written.compress_type = entry.compress_type
            book.writestr(written, body)
    return path


def _with_isbn(opf, isbn):
    text = opf.decode("utf-8")
    at = text.index("<dc:identifier")
    return (text[:at] + f"<dc:identifier>urn:isbn:{isbn}</dc:identifier>\n    " + text[at:]).encode(
        "utf-8"
    )
