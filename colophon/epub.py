"""Reading and correcting the metadata inside an EPUB or KEPUB.

An EPUB is a zip holding a package document (the OPF), which is the only part
of the book that carries its metadata. Everything here is about finding that
document, reading what it says, and changing as little of the rest of the file
as possible: the text, the images and the licence all come out untouched.
"""

import hashlib
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass

OPF = "http://www.idpf.org/2007/opf"
DC = "http://purl.org/dc/elements/1.1/"
CONTAINER = "urn:oasis:names:tc:opendocument:xmlns:container"
XMLENC = "http://www.w3.org/2001/04/xmlenc#"

CONTAINER_PATH = "META-INF/container.xml"
ENCRYPTION_PATH = "META-INF/encryption.xml"

# Font obfuscation is declared the same way DRM is, but it is routine in retail
# books and hiding nothing: it only scrambles the embedded font files.
FONT_OBFUSCATION = "http://www.idpf.org/2008/embedding"

# Series live in two places at once. Calibre writes a `meta` tag of its own, and
# EPUB 3 has a collection with the type and position hanging off it by id. Any
# library app reads at least one of them, so both are written.
CALIBRE_SERIES = "calibre:series"
CALIBRE_SERIES_INDEX = "calibre:series_index"
COLLECTION = "belongs-to-collection"
COLLECTION_TYPE = "collection-type"
GROUP_POSITION = "group-position"
SERIES = "series"
NEW_COLLECTION_ID = "colophon-series"
COVER_ID = "colophon-cover"
COVER_META = "cover"

# The marker a book carries when no source could be sure what it is, and the note
# saying the same thing where a person browsing their library will read it. An
# unverified book is not a corrected one - this is the whole of what is written
# to it - and the tag and the note are added together and taken off together.
# A tag is a `dc:subject`, which is what Calibre and Calibre-Web NextGen read as
# a book's tags; the spec names the tag but not the element.
UNVERIFIED_TAG = "colophon:unverified"
UNVERIFIED_NOTE = "Metadata could not be verified by Colophon."
# A blank line before the note, so it reads as a paragraph of its own rather than
# as the end of the blurb's last sentence.
_UNVERIFIED_PLAIN = f"\n\n{UNVERIFIED_NOTE}"
_UNVERIFIED_HTML = f"<p>{UNVERIFIED_NOTE}</p>"
# The three ways the note can be sitting at the end of a description: on its own,
# after a blank line, or as its own paragraph. Longest first, so the plain one is
# never mistaken for the bare note. Every question about the note is asked
# against this one list.
_NOTES = (_UNVERIFIED_PLAIN, _UNVERIFIED_HTML, UNVERIFIED_NOTE)
# A tag, rather than a stray `<` in a blurb. The `<` must open a name - letters,
# digits and hyphens, which is what an element name is and what a URL's `https:`
# is not - and the tag is looked for anywhere in the text because a description's
# markup need not be a single element. `<https://example.com>` is a link left in
# a blurb, not markup, and a note hung off the end of one is still plain text.
_HTML_TAG = re.compile(r"<[a-zA-Z][a-zA-Z0-9-]*(\s[^>]*)?/?>")

# What a cover image can be, by the first bytes of the file. The sources do not
# say what they are serving beyond a `Content-Type` header, and the bytes are
# what ends up in the book, so the bytes are what the declaration is built from.
COVER_TYPES = (
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
)

_XMLNS = re.compile(rb'xmlns(?::([A-Za-z_][\w.-]*))?="([^"]*)"')


def is_cover(body):
    """Whether these bytes start with an image Colophon can put in a book.

    The one place that decides what a cover may be. It is asked twice - once by
    `sources.image`, which will not hand over bytes the writer would refuse, and
    once by `_image_type` below, which needs the media type as well - and the
    two have to answer the same thing, so there is one table and two questions.
    """
    return _image_type(body)[0] is not None


class EpubError(Exception):
    """The file is not an EPUB we can read, or not one we should change."""


@dataclass(frozen=True)
class Book:
    """What a book says about itself, before any source is consulted."""

    title: str | None
    authors: tuple
    isbn: str | None
    language: str | None
    description: str | None = None
    publisher: str | None = None
    date: str | None = None
    # The series the book already says it is in, and the number it claims, as
    # Calibre records them. Read here because the two are judged together: a
    # series number that is being left alone is only stale if the series around
    # it is changing.
    series: str | None = None
    series_number: str | None = None
    # Whether the book has a cover of its own. Read here rather than asked of
    # the file again later, so "does it have one" and "add it if it does not"
    # cannot be answered from two different readings of the same book.
    has_cover: bool = False
    # Whether the book carries Colophon's unverified mark already. Read here
    # because the mark and the correction are decided together: a book that was
    # marked and has now been matched has its mark taken off, and whether it has
    # one is a fact about the file as it was read.
    unverified: bool = False


@dataclass(frozen=True)
class Edits:
    """What a source says the book is. None leaves that field as it was.

    None is how a source spells "I have nothing to say about this field", and
    there is no value that means the opposite: taking something off a book is a
    separate flag, and there are two of them, because a value and its absence are
    not the only two states a field can be in.
    """

    title: str | None = None
    authors: tuple | None = None
    series: str | None = None
    series_number: str | None = None
    description: str | None = None
    publisher: str | None = None
    date: str | None = None
    isbn: str | None = None
    language: str | None = None
    # Set to take a series number off a book whose series is being replaced:
    # `series_number=None` means the source said nothing, which is not the same
    # as a number that is now a position in the wrong series.
    drop_series_number: bool = False
    # Set to take the description off a book altogether. `description=None` means
    # no rule and no mark had anything to say about it, which is not the same as
    # a description that is now nothing at all - which is what a marked book
    # whose blurb was only ever the note ends up with.
    drop_description: bool = False
    # Set when the description being carried is the file's own with the
    # unverified note taken off it, rather than a blurb a source offered. The log
    # line needs the difference to credit the right one, and nothing about the
    # text itself says which it is: a blurb the file came with and a blurb the
    # source repeats are the same characters.
    notes_taken_off: bool = False
    # Whether this book is being marked unverified (True), having that mark taken
    # off it (False), or is none of the correction's business (None). One field
    # rather than two because the tag and the note are one mark and go on and off
    # together. Marking writes `UNVERIFIED_TAG` and appends `UNVERIFIED_NOTE` to
    # the description; unmarking takes both off again. It is recomputed on every
    # pass rather than remembered, so a marked book that is corrected later comes
    # out clean.
    unverified: bool | None = None


def read(path):
    """Read the metadata out of the package document."""
    package = _package(path)
    metadata = _metadata(package)
    series, series_number = _read_series(metadata)
    description = _first_text(metadata, "description")
    return Book(
        title=_first_text(metadata, "title"),
        authors=tuple(_all_text(metadata, "creator")),
        isbn=_isbn(metadata),
        language=_first_text(metadata, "language"),
        description=description,
        publisher=_first_text(metadata, "publisher"),
        date=_first_text(metadata, "date"),
        series=series,
        series_number=series_number,
        has_cover=_has_cover(package, metadata),
        unverified=_has_unverified(metadata, description),
    )


def _unverified_subjects(metadata):
    """Every `dc:subject` on this book that is Colophon's unverified tag.

    A list rather than one element because a book can carry more than one: the
    tag is written once, but another tool - or an older Colophon - may have left
    duplicates, and a reader and a writer that disagreed about that would leave a
    book half-marked. Both of them ask this question here.
    """
    return [
        element
        for element in _elements(metadata, "subject")
        if (element.text or "").strip() == UNVERIFIED_TAG
    ]


def _has_unverified(metadata, description):
    """Whether a book is marked unverified, by either half of the mark.

    The tag or the note is enough. The two are written together, so a book
    carrying one of them was marked by some version of this program - or by a
    person who edited it - and a correction that matched the book should come out
    clean rather than half-marked.
    """
    if _unverified_subjects(metadata):
        return True
    return has_note((description or "").strip())


def _read_series(metadata):
    """The series the book is already in, and the number it claims.

    Calibre's two tags are read first, because they are the pair the writing
    side keeps together, and EPUB 3's collection is read when they are not
    there. Both are read for the same reason the cover is looked for both ways:
    a book that says what series it is in has said so, and whether a rule of
    `fill` sees an empty field must not depend on which shape of EPUB it is.
    """
    found = {}
    for element in metadata.findall(f"{{{OPF}}}meta"):
        if element.get("name") in (CALIBRE_SERIES, CALIBRE_SERIES_INDEX):
            found[element.get("name")] = (element.get("content") or "").strip() or None
    if found.get(CALIBRE_SERIES):
        return found.get(CALIBRE_SERIES), found.get(CALIBRE_SERIES_INDEX)

    collection = _collection(metadata)
    if collection is None:
        return found.get(CALIBRE_SERIES), found.get(CALIBRE_SERIES_INDEX)
    return (
        (collection.text or "").strip() or None,
        found.get(CALIBRE_SERIES_INDEX) or _refined(metadata, collection, GROUP_POSITION),
    )


def _has_cover(package, metadata):
    """Whether a book has a cover, by both of the ways a book can say so.

    EPUB 2 declares one with `<meta name="cover" content="id"/>` pointing at a
    manifest item; EPUB 3 puts `properties="cover-image"` on the item itself. A
    book may say it either way, or both, and any of them means the cover it came
    with is its own and is not to be replaced.
    """
    return _cover_id(metadata) is not None or _declared_cover(package)


def correct(path, edits, write=True, cover=None, would_add_cover=False):
    """Overwrite the fields a source provides, and say which ones moved.

    Nothing else in the file changes: the text, the images and any licence left
    inside it survive byte for byte. A book with nothing to change is not
    written at all, so not even its timestamp moves - and with `write=False`
    the answers are what *would* change, which is what a dry run wants.

    `cover` is the image a source offers, and it is added only when the book has
    none: a book with a cover keeps it, whatever it was offered. `None` means no
    cover was offered. `would_add_cover` says a cover is coming without the bytes
    being to hand, which is a dry run: the book is declared to have one and no
    image is written, so a book whose only change is a cover still reports one.

    An image the file will not take raises `EpubError`, and nothing is written
    before the answer is known, so a caller left holding that error has an
    untouched book rather than a half-corrected one. The declaration and the
    image go in together, in one rewrite of the zip, so a failure cannot leave
    the book saying it has a cover it has not got.
    """
    package, opf_path, metadata, taken = _open_package(path)
    folder = _folder_of(opf_path)
    changed = list(_apply(metadata, edits))
    image = _set_cover(package, metadata, folder, taken, cover, would_add_cover)
    if image is not None:
        changed.append("cover")
    if not changed or not write:
        return tuple(changed)

    document = _document(package)
    # A cover that was declared with no bytes behind it is a dry run: the
    # document goes in and no entry is written for an image never fetched.
    # `_set_cover` answers (None, None) for exactly that case.
    if image is not None and image[0] is not None:
        _rewrite(path, opf_path, document, image)
    else:
        _rewrite(path, opf_path, document)
    return tuple(changed)


def _open_package(path):
    """The package document's tree, where it lives, its metadata, and the book's names.

    Everything the correction needs from the file is read here, in the one open,
    so nothing downstream has to open the book again to ask it something.
    """
    try:
        with zipfile.ZipFile(path) as book:
            _refuse_if_locked(book, path)
            opf_path = _package_path(book)
            declared = book.read(opf_path)
            taken = {entry.filename for entry in book.infolist()}
    except zipfile.BadZipFile as error:
        raise EpubError(f"{path} is not an EPUB: {error}") from error
    except KeyError as error:
        raise EpubError(f"{path} is not an EPUB: no {error}") from error

    _keep_namespace_prefixes(declared)
    package = _parse(path, declared)
    metadata = _metadata(package)
    if metadata is None:
        raise EpubError(f"{path} has no metadata section to correct")
    return package, opf_path, metadata, taken


def _folder_of(opf_path):
    """The folder the package document lives in, as a zip-name prefix."""
    folder, _, _ = opf_path.rpartition("/")
    return f"{folder}/" if folder else ""


def _document(package):
    return ET.tostring(package, encoding="utf-8", xml_declaration=True)


def _apply(metadata, edits):
    """Write what the source provides, in a fixed order, reporting each move."""
    changed = []
    if edits.title is not None and _set_text(metadata, "title", edits.title):
        changed.append("title")
    if edits.authors is not None and _set_authors(metadata, edits.authors):
        changed.append("authors")
    # The unverified mark decides what the description is before it is written:
    # marking is what puts the note on, and unmarking is what takes it off, so
    # the value written is settled first and the field is written once. A pass
    # with no mark takes the description just as the rules left it.
    description = _description_of(edits)
    if _set_description(metadata, description, drop=edits.drop_description):
        changed.append("description")
    for name in ("publisher", "date"):
        value = getattr(edits, name)
        if value is not None and _set_text(metadata, name, value):
            changed.append(name)
    if edits.language is not None and _set_text(metadata, "language", edits.language):
        changed.append("language")
    if edits.isbn is not None and _set_isbn(metadata, edits.isbn):
        changed.append("isbn")
    series_moved, number_moved = _set_series(metadata, edits)
    if series_moved:
        changed.append("series")
    if number_moved:
        changed.append("series_number")
    if edits.unverified is not None and _set_unverified_tag(metadata, edits.unverified):
        changed.append("tag")
    return tuple(changed)


def _set_unverified_tag(metadata, unverified):
    """Put the unverified tag on a book, or take it off, saying whether it moved.

    Every one of them, on the way off: the tag is meant to be written once, but a
    book may have been through another tool, or through an older Colophon, that
    left two - and taking one off while another stays would leave the book still
    marked while the log said the mark had gone. On the way on, one tag and no
    more: a book that carries it already is left exactly as it is, so a re-dropped
    file is not rewritten and a second pass reports nothing.

    The book's own subjects are not touched either way, because a tag says what a
    book is about as well as what became of it, and only one of those two is
    Colophon's to decide.
    """
    found = _unverified_subjects(metadata)
    if found:
        if unverified:
            return False
        for element in found:
            metadata.remove(element)
        return True
    if not unverified:
        return False

    element = ET.Element(f"{{{DC}}}subject")
    element.text = UNVERIFIED_TAG
    _insert_dc(metadata, element)
    return True


# Reading ------------------------------------------------------------------


def _package(path):
    """The package document's root element, or an EpubError explaining why not."""
    try:
        with zipfile.ZipFile(path) as book:
            _refuse_if_locked(book, path)
            return _parse(path, book.read(_package_path(book)))
    except zipfile.BadZipFile as error:
        raise EpubError(f"{path} is not an EPUB: {error}") from error
    except KeyError as error:
        raise EpubError(f"{path} is not an EPUB: no {error}") from error


def _parse(path, declared):
    try:
        return ET.fromstring(declared)
    except ET.ParseError as error:
        raise EpubError(f"{path} has an unreadable package document: {error}") from error


def _refuse_if_locked(book, path):
    """A DRM-encrypted book keeps its metadata locked away, so hands off."""
    try:
        declared = book.read(ENCRYPTION_PATH)
    except KeyError:
        return
    try:
        encryption = ET.fromstring(declared)
    except ET.ParseError as error:
        raise EpubError(f"{path} has an unreadable {ENCRYPTION_PATH}: {error}") from error
    for method in encryption.iter(f"{{{XMLENC}}}EncryptionMethod"):
        if method.get("Algorithm") != FONT_OBFUSCATION:
            raise EpubError(f"{path} is encrypted; not touching it")


def _package_path(book):
    """Where the package document lives, according to the container."""
    container = ET.fromstring(book.read(CONTAINER_PATH))
    rootfile = container.find(f".//{{{CONTAINER}}}rootfile")
    if rootfile is None or not rootfile.get("full-path"):
        raise EpubError("the container does not say where the package document is")
    return rootfile.get("full-path")


def _metadata(package):
    return package.find(f"{{{OPF}}}metadata")


def _first_text(metadata, name):
    found = _all_text(metadata, name)
    return found[0] if found else None


def _all_text(metadata, name):
    return [
        element.text.strip()
        for element in _elements(metadata, name)
        if element.text and element.text.strip()
    ]


def _elements(metadata, name):
    return [] if metadata is None else metadata.findall(f"{{{DC}}}{name}")


def _isbn(metadata):
    """The ISBN this file carries, without hyphens, ISBN 13 preferred.

    EPUB 2 says which identifier is an ISBN with an `opf:scheme` attribute and
    puts it anywhere among the identifiers; EPUB 3 usually writes it as a
    `urn:isbn:` in the text. Both are read the same way, and a UUID or a
    Gutenberg URL is passed over.
    """
    found = [
        normalised
        for element in _elements(metadata, "identifier")
        if (normalised := _as_isbn(element.text or "", element.get(f"{{{OPF}}}scheme")))
    ]
    thirteen = [isbn for isbn in found if len(isbn) == 13]
    return (thirteen or found or [None])[0]


def _as_isbn(text, scheme=None):
    """The digits of an ISBN, or None if this is some other kind of identifier."""
    digits = text.strip()
    lowered = digits.lower()
    for prefix in ("urn:isbn:", "isbn:"):
        if lowered.startswith(prefix):
            digits = digits[len(prefix) :]
            break
    digits = digits.replace("-", "").replace(" ", "").strip()

    if len(digits) == 13 and digits.isdigit() and digits[:3] in ("978", "979"):
        return digits
    if len(digits) == 10 and digits[:9].isdigit() and digits[9] in "0123456789Xx":
        return digits.upper()
    # The file says this is an ISBN, so believe it even if the digits are odd.
    if scheme and "isbn" in scheme.lower() and len(digits) in (10, 13):
        return digits.upper()
    return None


# Writing ------------------------------------------------------------------


def _set_description(metadata, value, drop=False):
    """Write the description, take it off, or leave it alone.

    The description is the one field a correction can empty: marking a book
    appends a note to whatever blurb it has, and a later match takes the note off
    again - leaving nothing at all when the note was the whole of it. So `None`
    here means "no rule and no mark had anything to say" and `drop` means
    "nothing is left of it", which is the difference between a book that never
    had a blurb and one whose blurb was only ever Colophon's note.
    """
    if drop:
        return _drop_description(metadata)
    if value is None:
        return False
    return _set_text(metadata, "description", value)


def _drop_description(metadata):
    """Take the description off the book, saying whether there was one to take off."""
    elements = _elements(metadata, "description")
    for element in elements:
        metadata.remove(element)
    return bool(elements)


def _set_text(metadata, name, value):
    """Put a value on the first dc:<name>, adding the element if it is missing."""
    value = str(value).strip()
    if not value:
        return False
    elements = _elements(metadata, name)
    if not elements:
        element = ET.Element(f"{{{DC}}}{name}")
        element.text = value
        _insert_dc(metadata, element)
        return True
    if (elements[0].text or "").strip() == value:
        return False
    elements[0].text = value
    return True


def _description_of(edits):
    """The description this correction leaves behind, or None to leave it alone.

    Two passes mark a book rather than correct it, and both work on whatever
    `description` the caller settled on - the source's blurb where a rule wrote
    one, the file's own otherwise - so nothing here has to know which rule ran.
    Marking puts the note on and unmarking takes it off, each only once: a
    description already ending in the note was marked on an earlier pass, and a
    note in the middle of a blurb was not put there by Colophon.
    """
    if not edits.unverified:
        # Not a mark either way, so the description is nothing to do with this
        # pass unless the book was marked before and something has to come off.
        if edits.description is None:
            return None
        return unmarked(edits.description)
    # Marking writes a description even when the file has none: the note is what
    # tells a person browsing their library that nobody could vouch for the book,
    # so it is the one thing that must be there.
    return _noted(edits.description)


def _noted(text):
    """A description with the unverified note put on its end.

    The form the note takes follows the blurb: a description carrying markup gets
    a paragraph of its own, so the note cannot end up hanging outside the last
    element, and a plain one gets a blank line. Which of the two it is has to be
    looked at rather than known, because a `dc:description` may hold either and
    the design spec never settled which.
    """
    text = (text or "").strip()
    if not text:
        return UNVERIFIED_NOTE
    if has_note(text):
        return text
    if _HTML_TAG.search(text):
        return f"{text}{_UNVERIFIED_HTML}"
    return f"{text}{_UNVERIFIED_PLAIN}"


def unmarked(text):
    """The description with the unverified note taken off its end, if it is there.

    Public because the pipeline needs the same answer: whether a rule should
    write a blurb depends on whether the book has one, and a book whose
    description is only the note has none. One rule, asked from both sides, so
    the two cannot disagree about what "already has a description" means.

    Only the end: the note may have had a blurb written after it by some other
    tool, and that is not the note Colophon put there.
    """
    if not has_note(text):
        return (text or "").strip() or None
    # `has_note` says one of the three fits, so this finds which and takes it off.
    # The first that fits wins: the plain forms both end in the bare note, and the
    # longest is tried first for exactly that reason.
    for note in _NOTES:
        if text.endswith(note):
            return text[: -len(note)].strip() or None


def has_note(text):
    """Whether a description carries the note at its end, in either of its forms."""
    return bool(text) and text.endswith(_NOTES)


def _set_isbn(metadata, isbn):
    """Write the ISBN as EPUB 3's URN, on whichever identifier is an ISBN.

    A book's other identifiers - a UUID, a Gutenberg URL - are not touched: they
    identify the file, and the ISBN identifies the edition. An identifier that
    already says it is an ISBN is rewritten in place rather than added to, so a
    book corrected twice does not end up claiming two ISBNs.

    The comparison is of the numbers, not of the strings: `urn:isbn:9781521748831`,
    `978-1-5217-4883-1` and `9781521748831` are one ISBN, and writing the same one
    again in another form would be a change reported for nothing. `_as_isbn` is
    what reads the digits out of either form, so the two cannot disagree about
    what an ISBN is.
    """
    wanted = _as_isbn(str(isbn))
    if not wanted:
        return False
    for element in _elements(metadata, "identifier"):
        text = (element.text or "").strip()
        scheme = (element.get(f"{{{OPF}}}scheme") or "").lower()
        if "isbn" in scheme or text.lower().startswith("urn:isbn:"):
            # An identifier whose digits do not read as an ISBN at all is still
            # one the file says is one, so it is the one to write over.
            if _as_isbn(text, scheme) == wanted:
                return False
            element.text = f"urn:isbn:{wanted}"
            element.attrib.pop(f"{{{OPF}}}scheme", None)
            return True

    element = ET.Element(f"{{{DC}}}identifier")
    element.text = f"urn:isbn:{wanted}"
    _insert_dc(metadata, element)
    return True


def _set_authors(metadata, authors):
    """Replace the file's creators with this list.

    The first `dc:creator` is kept where it is, because EPUB 3 files hang
    `file-as` and `role` off it by id. Surplus creators go, along with the
    metas that refined them so nothing dangles, and extra authors are added as
    plain creators.
    """
    wanted = [str(author).strip() for author in authors if str(author).strip()]
    if not wanted:
        return False

    existing = _elements(metadata, "creator")
    changed = False
    for index, author in enumerate(wanted):
        if index < len(existing):
            if (existing[index].text or "").strip() != author:
                existing[index].text = author
                changed = True
        else:
            element = ET.Element(f"{{{DC}}}creator")
            element.text = author
            _insert_dc(metadata, element)
            changed = True

    for surplus in existing[len(wanted) :]:
        _drop_with_refines(metadata, surplus)
        changed = True
    return changed


def _set_series(metadata, edits):
    """Calibre's two tags and EPUB 3's collection, so any reader sees the series."""
    series_moved = False
    number_moved = False

    if edits.series is not None:
        collection = _collection(metadata, create=True)
        series = str(edits.series).strip()
        if _set_meta(metadata, CALIBRE_SERIES, series):
            series_moved = True
        if (collection.text or "").strip() != series:
            collection.text = series
            series_moved = True
        if _set_refined(metadata, collection, COLLECTION_TYPE, SERIES):
            series_moved = True
    else:
        collection = _collection(metadata)

    if edits.series_number is not None:
        position = _position(edits.series_number)
        if _set_meta(metadata, CALIBRE_SERIES_INDEX, position):
            number_moved = True
        if collection is not None and _set_refined(
            metadata, collection, GROUP_POSITION, position
        ):
            number_moved = True
    elif edits.drop_series_number:
        # The series this number belonged to is gone, so a number left behind
        # would be a position in a series the book is no longer in. A reader
        # cannot tell that from a number that is still true, which is why it is
        # taken off rather than left.
        if _drop_meta(metadata, CALIBRE_SERIES_INDEX):
            number_moved = True
        if collection is not None and _drop_refined(metadata, collection, GROUP_POSITION):
            number_moved = True

    return series_moved, number_moved


def _collection(metadata, create=False):
    """EPUB 3's series collection, adding one if asked and there is not one.

    A collection that says it is something else - a boxed set, say - is left
    alone, and a second collection is added rather than hijacking it.
    """
    for element in metadata.findall(f"{{{OPF}}}meta"):
        if element.get("property") != COLLECTION:
            continue
        if _refined(metadata, element, COLLECTION_TYPE) in (None, SERIES):
            return element
    if not create:
        return None

    element = ET.SubElement(metadata, f"{{{OPF}}}meta")
    element.set("property", COLLECTION)
    element.set("id", _free_id(metadata, NEW_COLLECTION_ID))
    return element


def _set_meta(metadata, name, value):
    """One of the book's `meta name= content=` tags, added if it is missing."""
    for element in metadata.findall(f"{{{OPF}}}meta"):
        if element.get("name") == name:
            if element.get("content") == value:
                return False
            element.set("content", value)
            return True

    element = ET.SubElement(metadata, f"{{{OPF}}}meta")
    element.set("name", name)
    element.set("content", value)
    return True


def _drop_meta(metadata, name):
    """Take one of those tags off the book, saying whether there was one."""
    found = False
    for element in list(metadata.findall(f"{{{OPF}}}meta")):
        if element.get("name") == name:
            metadata.remove(element)
            found = True
    return found


def _drop_refined(metadata, element, name):
    """Take off the meta refining this element, saying whether there was one."""
    identifier = element.get("id")
    if not identifier:
        return False
    found = False
    for other in list(metadata.findall(f"{{{OPF}}}meta")):
        if other.get("refines") == f"#{identifier}" and other.get("property") == name:
            metadata.remove(other)
            found = True
    return found


def _refined(metadata, element, name):
    """What a meta refining this element says, if anything does."""
    identifier = element.get("id")
    if not identifier:
        return None
    for other in metadata.findall(f"{{{OPF}}}meta"):
        if other.get("refines") == f"#{identifier}" and other.get("property") == name:
            return (other.text or "").strip()
    return None


def _set_refined(metadata, element, name, value):
    """Set a meta refining this element, adding it if it is missing."""
    identifier = element.get("id")
    if not identifier:
        identifier = _free_id(metadata, NEW_COLLECTION_ID)
        element.set("id", identifier)

    for other in metadata.findall(f"{{{OPF}}}meta"):
        if other.get("refines") == f"#{identifier}" and other.get("property") == name:
            if (other.text or "").strip() == value:
                return False
            other.text = value
            return True

    other = ET.SubElement(metadata, f"{{{OPF}}}meta")
    other.set("property", name)
    other.set("refines", f"#{identifier}")
    other.text = value
    return True


def _drop_with_refines(metadata, element):
    """Remove an element and anything refining it, so no id is left dangling."""
    identifier = element.get("id")
    metadata.remove(element)
    if identifier:
        for other in list(metadata):
            if other.get("refines") == f"#{identifier}":
                metadata.remove(other)


def _insert_dc(metadata, element):
    """Add a dc element, keeping the dc elements ahead of the meta ones."""
    for index, existing in enumerate(metadata):
        if existing.tag in (f"{{{OPF}}}meta", f"{{{OPF}}}link"):
            metadata.insert(index, element)
            return
    metadata.append(element)


def _free_id(metadata, wanted):
    taken = {element.get("id") for element in metadata.iter() if element.get("id")}
    if wanted not in taken:
        return wanted
    number = 2
    while f"{wanted}-{number}" in taken:
        number += 1
    return f"{wanted}-{number}"


def _position(value):
    """A series number as a reader wants it: 6, not 6.0; 1.5 stays 1.5."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value).strip()
    return f"{number:g}"


# The cover -----------------------------------------------------------------


def _cover_id(metadata):
    """The manifest id EPUB 2's cover meta points at, if the book says one."""
    for element in metadata.findall(f"{{{OPF}}}meta"):
        if element.get("name") == COVER_META:
            found = (element.get("content") or "").strip()
            if found:
                return found
    return None

def _declared_cover(package):
    """Whether an EPUB 3 manifest item claims to be the cover image."""
    manifest = package.find(f"{{{OPF}}}manifest")
    if manifest is None:
        return False
    for item in manifest.findall(f"{{{OPF}}}item"):
        properties = (item.get("properties") or "").split()
        if "cover-image" in properties:
            return True
    return False


def _set_cover(package, metadata, folder, taken, cover, would_add_cover=False):
    """Declare an image the book's cover, or None when there is nothing to declare.

    A book that already has a cover keeps it: the setting says a cover is added
    to a book that has none, so being offered one is not a reason to replace
    what a person chose. Either way of declaring a cover counts - EPUB 2's
    `<meta name="cover">` and EPUB 3's `properties="cover-image"` - because a
    book that says it has one either way has one.

    The image goes in beside the package document, which is where a relative
    manifest href is resolved from, under a name built from its own bytes, so
    the same image added twice is the same entry rather than a second copy. With
    `would_add_cover` the declaration is made and no entry is named for an image,
    which is what a dry run is: what the book would say, without fetching or
    storing the image it would say it about.

    Returns (name, image) for the rewrite to put in the zip, or (None, None) for
    a declaration with no image behind it. The name is the zip entry's own, which
    is the href resolved back against the folder the package document lives in.
    """
    if cover is None and not would_add_cover:
        return None
    if _cover_id(metadata) is not None or _declared_cover(package):
        return None

    identifier = _free_id(metadata, COVER_ID)
    # A declaration with no image behind it still needs a media type, and the
    # media type is what says what the image is. Nothing reads it in a dry run;
    # it is the one both sources serve, so it is the least surprising guess.
    media_type = "image/jpeg"
    name = None
    if cover:
        media_type, extension = _image_type(cover)
        if media_type is None:
            raise EpubError("the offered cover is not an image Colophon recognises")
        name = _free_name(folder, taken, cover, extension)

    manifest = package.find(f"{{{OPF}}}manifest")
    item = ET.SubElement(manifest, f"{{{OPF}}}item")
    item.set("id", identifier)
    item.set("media-type", media_type)
    if name is not None:
        item.set("href", _relative_href(name, folder))
    if _is_epub3(package):
        item.set("properties", "cover-image")
    _set_meta(metadata, COVER_META, identifier)
    return name, cover


def _free_name(folder, taken, image, extension):
    """A name for this image that the book does not already use.

    Built from the image's own bytes, so the same image added twice is the same
    entry rather than a second copy, and so the name does not depend on when the
    pass ran. A book that already uses the name keeps it: the new image goes
    beside it.
    """
    digest = hashlib.md5(image).hexdigest()[:8]
    name = f"{folder}cover-{digest}{extension}"
    number = 2
    while name in taken:
        name = f"{folder}cover-{digest}-{number}{extension}"
        number += 1
    return name


def _image_type(cover):
    """What an image is, from its own first bytes, or (None, None) if it is not one."""
    for signature, media_type, extension in COVER_TYPES:
        if cover.startswith(signature):
            return media_type, extension
    return None, None


def _is_epub3(package):
    """Which of the two layout versions this package document declares."""
    return str(package.get("version", "3.0")).startswith("3")


def _relative_href(name, package_folder):
    """A manifest href, which is resolved from the package document, not the zip root."""
    return name.removeprefix(package_folder)


# The zip itself -----------------------------------------------------------


def _keep_namespace_prefixes(declared):
    """Remember the document's prefixes so writing it back keeps them.

    ElementTree invents `ns0:`-style prefixes for namespaces it has not been
    told about, which would rename every reader-facing tag in the file.
    """
    for prefix, uri in _XMLNS.findall(declared):
        if uri:
            ET.register_namespace(prefix.decode() if prefix else "", uri.decode())


def _rewrite(path, opf_path, document, image=None):
    """Rewrite the zip with the new package document and nothing else disturbed.

    Both handles are closed before the swap: Windows refuses to replace a file
    that anything still has open, so the book is read, closed, and only then
    replaced by the rewritten copy.

    `image` is the cover to add, as (zip name, bytes), and it goes into this same
    rewrite as the last entry - after everything the book already had, so the
    order it was written in is left as it was. One rewrite, so the book can
    never end up declaring a cover whose image never arrived.

    The entry is stamped with the book's own date, not the clock. Correcting the
    same book twice has to give the same bytes - the relay decides a re-dropped
    book is a duplicate by comparing them - and a wall-clock stamp would make
    every re-drop a different file, or a "different file" beside it.
    """
    half_written = path.parent / f".{path.name}.colophon-new"
    try:
        with zipfile.ZipFile(path) as book, zipfile.ZipFile(half_written, "w") as rewritten:
            stamped = _EPOCH
            for entry in book.infolist():
                if stamped is _EPOCH:
                    stamped = entry.date_time
                body = document if entry.filename == opf_path else book.read(entry.filename)
                _copy_entry(rewritten, entry, body)
            if image is not None:
                name, cover = image
                added = zipfile.ZipInfo(name, stamped)
                added.compress_type = zipfile.ZIP_DEFLATED
                rewritten.writestr(added, cover)
        os.replace(half_written, path)
    except OSError:
        half_written.unlink(missing_ok=True)
        raise


# What a zip entry is stamped with when the book has no entry to copy a date
# from. The zip format cannot store anything before 1980, so this is the earliest
# a valid one can be - which is what makes it the same every time.
_EPOCH = (1980, 1, 1, 0, 0, 0)


def _copy_entry(rewritten, entry, body):
    """Copy one entry as it was: same name, same order, same compression."""
    copied = zipfile.ZipInfo(entry.filename, entry.date_time)
    copied.compress_type = entry.compress_type
    copied.external_attr = entry.external_attr
    copied.internal_attr = entry.internal_attr
    copied.create_system = entry.create_system
    rewritten.writestr(copied, body)
