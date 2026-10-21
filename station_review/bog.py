"""Read a Niagara station backup (.bog) into a simple node tree.

A .bog is a zip holding file.xml (the station's baja object graph).  Only values that differ
from their defaults are stored, and live values (status, out) are mostly transient, so the
tree describes configuration plus the last values that were passed along links.
"""
import io
import re
import zipfile
import xml.etree.ElementTree as ET

INVALID_CHARREF = re.compile(r'&#([xX][0-9a-fA-F]+|\d+);')


def _strip_bad_charrefs(text):
    """Remove XML character references that XML 1.0 forbids (e.g. &#x0; in firmware strings).
    Without this ElementTree refuses the whole file."""
    def f(m):
        g = m.group(1)
        n = int(g[1:], 16) if g[0] in 'xX' else int(g)
        return m.group(0) if (n in (9, 10, 13) or n >= 32) else ''
    return INVALID_CHARREF.sub(f, text)


def decode_name(n):
    """Niagara escapes names with $xx hex codes, sometimes twice ($2436 -> $36 -> '6')."""
    if n is None:
        return None
    prev = None
    while prev != n and '$' in n:
        prev = n
        n = re.sub(r'\$([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), n)
    return n


class Node:
    __slots__ = ('raw', 'name', 't', 'v', 'h', 'f', 'kids', 'parent', 'tag')

    def __repr__(self):
        return f'<{self.name} {self.t}>'


def _build(el, parent=None):
    n = Node()
    n.tag = el.tag
    n.raw = el.get('n')
    n.name = decode_name(n.raw)
    n.t = el.get('t', '')
    n.v = el.get('v')
    n.h = el.get('h')
    n.f = el.get('f', '')
    n.parent = parent
    n.kids = [_build(c, n) for c in el if c.tag in ('p', 'a')]
    return n


class Bog:
    """Parsed station.  .root is the station node; .handles maps h:xx handles to nodes."""

    def __init__(self, data, saved=None):
        if data[:2] == b'PK':
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                name = next((i for i in z.infolist() if i.filename.endswith('.xml')), None)
                if name is None:
                    raise ValueError('this .bog has no file.xml inside')
                xml = z.read(name).decode('utf-8', errors='replace')
                if saved is None:
                    y, mo, d, hh, mm, ss = name.date_time
                    saved = f'{y:04d}-{mo:02d}-{d:02d} {hh:02d}:{mm:02d}'
        else:
            xml = data.decode('utf-8', errors='replace')
        if '<bajaObjectGraph' not in xml[:2000]:
            raise ValueError('this does not look like a Niagara station (.bog) file')
        root = ET.fromstring(_strip_bad_charrefs(xml))
        top = _build(root)
        self.saved = saved
        self.handles = {}
        for n in walk(top):
            if n.h:
                self.handles[n.h] = n
        self.root = next((n for n in walk(top) if n.t == 'b:Station'), None)
        if self.root is None:
            raise ValueError('no station found in this file')

    @classmethod
    def from_file(cls, path):
        with open(path, 'rb') as fh:
            return cls(fh.read())


# ---------------------------------------------------------------- helpers
def walk(n):
    if n is None:
        return
    yield n
    for k in n.kids:
        yield from walk(k)


def child(n, name):
    if n is None:
        return None
    for k in n.kids:
        if k.name == name:
            return k
    return None


def val(n, name, default=None):
    c = child(n, name)
    if c is None:
        return default
    if c.v is not None:
        return c.v
    vv = child(c, 'value')
    if vv is not None and vv.v is not None:
        return vv.v
    return default


def comps(n):
    return [k for k in n.kids if k.h] if n is not None else []


def path(n):
    parts = []
    while n is not None and n.name is not None:
        parts.append(n.name)
        n = n.parent
    parts = list(reversed(parts))
    if parts and parts[0] == 'station':
        parts = parts[1:]
    return '/'.join(parts)


def status_bits(s):
    """Persisted status strings are hex bit masks, e.g. '40' = null, '0;activeLevel=...' = ok."""
    if not s:
        return 0
    try:
        return int(s.split(';')[0], 16)
    except ValueError:
        return 0


NULL_BIT = 0x40


def units(facets):
    """'units=u:celsius;°C;(K);+273.15;|precision=i:1' -> '°C'"""
    if not facets:
        return ''
    m = re.search(r'units=u:([^;|]*);([^;|]*)', facets)
    if not m:
        return ''
    return m.group(2) or m.group(1)
