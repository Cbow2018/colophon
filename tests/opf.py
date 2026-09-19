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
