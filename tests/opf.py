"""Reading what a corrected EPUB says, without going through the code under test.

Tests that assert on the file's own tags - what Calibre or an EPUB 3 reader
would find - use these, so the implementation cannot quietly redefine what
"written in Calibre's format" means.
"""

import xml.etree.ElementTree as ET
import zipfile

OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"


def metadata_of(path):
    """The package document's metadata element."""
    with zipfile.ZipFile(path) as book:
        container = ET.fromstring(book.read("META-INF/container.xml"))
        rootfile = container.find(f".//{{{CONTAINER_NS}}}rootfile")
        package = ET.fromstring(book.read(rootfile.get("full-path")))
    return package.find(f"{{{OPF_NS}}}metadata")


def calibre_series(path):
    """(series, series number) as Calibre records them."""
    metadata = metadata_of(path)
    found = {}
    for element in metadata.findall(f"{{{OPF_NS}}}meta"):
        if element.get("name") in ("calibre:series", "calibre:series_index"):
            found[element.get("name")] = element.get("content")
    return found.get("calibre:series"), found.get("calibre:series_index")


def epub3_series(path):
    """(series, collection type, position) as an EPUB 3 reader sees them."""
    for collection in collections(path).values():
        if collection.get("collection-type") == "series":
            return collection["name"], "series", collection.get("group-position")
    return None


def collections(path):
    """Every belongs-to-collection element, by id, with whatever refines it."""
    metadata = metadata_of(path)
    found = {}
    for element in metadata.findall(f"{{{OPF_NS}}}meta"):
        if element.get("property") == "belongs-to-collection":
            identifier = element.get("id")
            found[identifier] = {
                "name": (element.text or "").strip(),
                **{
                    other.get("property"): (other.text or "").strip()
                    for other in metadata.findall(f"{{{OPF_NS}}}meta")
                    if other.get("refines") == f"#{identifier}"
                },
            }
    return found


def subjects(path):
    """Every dc:subject the book carries, in the order it carries them.

    A tag is a `dc:subject`, which is what Calibre and Calibre-Web NextGen read
    as a book's tags. Read here by hand for the same reason as `text_of`: a test
    asserting on a written tag must not agree with the code merely by sharing
    its reader.
    """
    return [
        (element.text or "").strip()
        for element in metadata_of(path).findall(f"{{{DC_NS}}}subject")
        if (element.text or "").strip()
    ]


def entries_of(path):
    """Every entry in the zip, in order, by name."""
    with zipfile.ZipFile(path) as book:
        return {entry.filename: book.read(entry.filename) for entry in book.infolist()}


def refining_metas(path):
    """(property, refines) for every meta tag that refines something."""
    return [
        (element.get("property"), element.get("refines"))
        for element in metadata_of(path).findall(f"{{{OPF_NS}}}meta")
        if element.get("refines")
    ]


def text_of(path, name):
    """What a dc element says, or None when the book does not have one.

    The same read `colophon.epub` does, written here by hand so a test asserting
    on a written value cannot agree with the code merely by sharing its reader.
    """
    metadata = metadata_of(path)
    found = [
        (element.text or "").strip()
        for element in metadata.findall(f"{{{DC_NS}}}{name}")
        if (element.text or "").strip()
    ]
    return found[0] if found else None


def manifest_items(path):
    """Every manifest item, by id, as {href, media-type, properties}."""
    with zipfile.ZipFile(path) as book:
        container = ET.fromstring(book.read("META-INF/container.xml"))
        rootfile = container.find(f".//{{{CONTAINER_NS}}}rootfile")
        package = ET.fromstring(book.read(rootfile.get("full-path")))
    found = {}
    for item in package.find(f"{{{OPF_NS}}}manifest").findall(f"{{{OPF_NS}}}item"):
        found[item.get("id")] = {
            "href": item.get("href"),
            "media-type": item.get("media-type"),
            "properties": item.get("properties"),
        }
    return found


def cover_meta(path):
    """What EPUB 2's legacy cover declaration says, or None when there is none."""
    for element in metadata_of(path).findall(f"{{{OPF_NS}}}meta"):
        if element.get("name") == "cover":
            return element.get("content")
    return None
