"""Reading and correcting the metadata inside an EPUB or KEPUB.

An EPUB is a zip holding a package document (the OPF), which is the only part
of the book that carries its metadata. Everything here is about finding that
document, reading what it says, and changing as little of the rest of the file
as possible: the text, the images and the licence all come out untouched.
"""

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

_XMLNS = re.compile(rb'xmlns(?::([A-Za-z_][\w.-]*))?="([^"]*)"')


class EpubError(Exception):
    """The file is not an EPUB we can read, or not one we should change."""


@dataclass(frozen=True)
class Book:
    """What a book says about itself, before any source is consulted."""

    title: str | None
    authors: tuple
    isbn: str | None
    language: str | None


@dataclass(frozen=True)
class Edits:
    """What a source says the book is. None leaves that field as it was."""

    title: str | None = None
    authors: tuple | None = None
    series: str | None = None
    series_number: str | None = None


def read(path):
    """Read the metadata out of the package document."""
    package = _package(path)
    metadata = _metadata(package)
    return Book(
        title=_first_text(metadata, "title"),
        authors=tuple(_all_text(metadata, "creator")),
        isbn=_isbn(metadata),
        language=_first_text(metadata, "language"),
    )


def correct(path, edits, write=True):
    """Overwrite the fields a source provides, and say which ones moved.

    Nothing else in the file changes: the text, the images and any licence left
    inside it survive byte for byte. A book with nothing to change is not
    written at all, so not even its timestamp moves - and with `write=False`
    the answers are what *would* change, which is what a dry run wants.
    """
    try:
        with zipfile.ZipFile(path) as book:
            _refuse_if_locked(book, path)
            opf_path = _package_path(book)
            declared = book.read(opf_path)
    except zipfile.BadZipFile as error:
        raise EpubError(f"{path} is not an EPUB: {error}") from error
    except KeyError as error:
        raise EpubError(f"{path} is not an EPUB: no {error}") from error

    _keep_namespace_prefixes(declared)
    package = _parse(path, declared)
    metadata = _metadata(package)
    if metadata is None:
        raise EpubError(f"{path} has no metadata section to correct")

    changed = _apply(metadata, edits)
    if changed and write:
        document = ET.tostring(package, encoding="utf-8", xml_declaration=True)
        _rewrite(path, opf_path, document)
    return changed


def _apply(metadata, edits):
    """Write what the source provides, in a fixed order, reporting each move."""
    changed = []
    if edits.title is not None and _set_text(metadata, "title", edits.title):
        changed.append("title")
    if edits.authors is not None and _set_authors(metadata, edits.authors):
        changed.append("authors")
    series_moved, number_moved = _set_series(metadata, edits)
    if series_moved:
        changed.append("series")
    if number_moved:
        changed.append("series_number")
    return tuple(changed)


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


def _set_text(metadata, name, value):
    """Put a value on the first dc:<name>, adding the element if it is missing."""
    value = str(value).strip()
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


# The zip itself -----------------------------------------------------------


def _keep_namespace_prefixes(declared):
    """Remember the document's prefixes so writing it back keeps them.

    ElementTree invents `ns0:`-style prefixes for namespaces it has not been
    told about, which would rename every reader-facing tag in the file.
    """
    for prefix, uri in _XMLNS.findall(declared):
        if uri:
            ET.register_namespace(prefix.decode() if prefix else "", uri.decode())


def _rewrite(path, opf_path, document):
    """Rewrite the zip with the new package document and nothing else disturbed.

    Both handles are closed before the swap: Windows refuses to replace a file
    that anything still has open, so the book is read, closed, and only then
    replaced by the rewritten copy.
    """
    half_written = path.parent / f".{path.name}.colophon-new"
    try:
        with zipfile.ZipFile(path) as book, zipfile.ZipFile(half_written, "w") as rewritten:
            for entry in book.infolist():
                body = document if entry.filename == opf_path else book.read(entry.filename)
                _copy_entry(rewritten, entry, body)
        os.replace(half_written, path)
    except OSError:
        half_written.unlink(missing_ok=True)
        raise


def _copy_entry(rewritten, entry, body):
    """Copy one entry as it was: same name, same order, same compression."""
    copied = zipfile.ZipInfo(entry.filename, entry.date_time)
    copied.compress_type = entry.compress_type
    copied.external_attr = entry.external_attr
    copied.internal_attr = entry.internal_attr
    copied.create_system = entry.create_system
    rewritten.writestr(copied, body)
