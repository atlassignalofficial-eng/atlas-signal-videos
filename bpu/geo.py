"""World geometry: Natural Earth countries, true areas, sphere moves, Mercator.

Natural Earth is public domain (https://www.naturalearthdata.com/about/terms-of-use/).
The file is pinned to a commit so renders are reproducible.

Geometry is kept as lists of rings, each ring a list of (lon, lat) degrees.
"""
import json
import math
import urllib.request
from pathlib import Path

NE_COMMIT = "ca96624a56bd078437bca8184e78163e5039ad19"
NE_URL = (f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{NE_COMMIT}"
          "/geojson/ne_110m_admin_0_countries.geojson")
SOURCE = {"name": "Natural Earth 1:110m Admin 0 countries", "url": NE_URL,
          "license": "public domain"}
R_KM = 6371.0088  # mean Earth radius
MERC_LIMIT = 85.0  # clamp latitude before projecting


def load_countries(cache_dir) -> list[dict]:
    """[{iso, name, continent, rings}] — downloads once into cache_dir."""
    path = Path(cache_dir) / f"ne_110m_countries_{NE_COMMIT[:8]}.geojson"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(NE_URL, timeout=60) as r:
            path.write_bytes(r.read())
    out = []
    for f in json.loads(path.read_text())["features"]:
        p, g = f["properties"], f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        out.append({"iso": p["ADM0_A3"], "name": p["NAME"], "continent": p["CONTINENT"],
                    "polys": [[[tuple(pt) for pt in ring] for ring in poly] for poly in polys]})
    return out


def select(countries, selector: str) -> list[list]:
    """Polygons for 'country:GRL', 'continent:Africa', or 'mainland:USA' (largest polygon)."""
    kind, _, value = selector.partition(":")
    if kind == "continent":
        polys = [p for c in countries if c["continent"] == value for p in c["polys"]]
    elif kind in ("country", "mainland"):
        match = [c for c in countries if c["iso"] == value]
        if not match:
            raise KeyError(f"unknown country {value}")
        polys = match[0]["polys"]
        if kind == "mainland":
            polys = [max(polys, key=lambda p: abs(_ring_area(p[0])))]
    else:
        raise ValueError(f"bad selector {selector!r}")
    if not polys:
        raise KeyError(f"nothing matches {selector}")
    return polys


def area_km2(polys) -> float:
    """True surface area of polygons (outer ring minus holes) on a sphere."""
    total = 0.0
    for poly in polys:
        total += abs(_ring_area(poly[0])) - sum(abs(_ring_area(h)) for h in poly[1:])
    return total


def _ring_area(ring) -> float:
    # Spherical excess approximation used by d3/turf: exact enough for country-scale rings.
    s = 0.0
    for (l1, p1), (l2, p2) in zip(ring, ring[1:] + ring[:1]):
        s += math.radians(l2 - l1) * (2 + math.sin(math.radians(p1)) + math.sin(math.radians(p2)))
    return s * R_KM * R_KM / 2


def _vec(lon, lat):
    lo, la = math.radians(lon), math.radians(lat)
    return (math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la))


def _lonlat(v):
    x, y, z = v
    return math.degrees(math.atan2(y, x)), math.degrees(math.asin(max(-1.0, min(1.0, z))))


def centroid(polys) -> tuple[float, float]:
    """Mean of all vertices on the sphere — good enough to aim a move."""
    sx = sy = sz = 0.0
    for poly in polys:
        for lon, lat in poly[0]:
            x, y, z = _vec(lon, lat)
            sx, sy, sz = sx + x, sy + y, sz + z
    n = math.sqrt(sx * sx + sy * sy + sz * sz)
    return _lonlat((sx / n, sy / n, sz / n))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _rotator(axis, angle):
    """Rodrigues rotation about a unit axis."""
    c, s = math.cos(angle), math.sin(angle)

    def rot(v):
        kv, cr = _dot(axis, v), _cross(axis, v)
        return tuple(v[i] * c + cr[i] * s + axis[i] * kv * (1 - c) for i in range(3))
    return rot


def move(polys, to_lonlat, t=1.0, upright=True) -> list:
    """Slide polygons along the great circle from their centroid toward `to_lonlat`.

    A rigid rotation of the sphere, so the shape keeps its TRUE size: on a
    Mercator map it visibly shrinks as it nears the equator. `upright` spins it
    about its own centre so north stays up. t in [0, 1] is progress.
    """
    lon0, lat0 = centroid(polys)
    a, b = _vec(lon0, lat0), _vec(*to_lonlat)
    axis = _cross(a, b)
    n = math.sqrt(_dot(axis, axis))
    if n < 1e-12:
        return polys
    travel = _rotator(tuple(x / n for x in axis), math.atan2(n, _dot(a, b)) * t)
    steps = [travel]
    if upright:
        here = travel(a)
        lon1, lat1 = _lonlat(here)
        north = travel(_vec(lon0, min(lat0 + 1, 89.9)))
        # bearing of the carried "north" point, measured in the local east/north frame
        east_dir = (-math.sin(math.radians(lon1)), math.cos(math.radians(lon1)), 0.0)
        north_dir = _cross(here, east_dir)
        d = tuple(north[i] - here[i] for i in range(3))
        bearing = math.atan2(_dot(d, east_dir), _dot(d, north_dir))
        steps.append(_rotator(here, bearing))

    def rot(lon, lat):
        v = _vec(lon, lat)
        for f in steps:
            v = f(v)
        return _lonlat(v)

    return [[[rot(lon, lat) for lon, lat in ring] for ring in poly] for poly in polys]


def mercator(lon, lat) -> tuple[float, float]:
    """Web-Mercator style (x, y) in radians; y grows northward."""
    lat = max(-MERC_LIMIT, min(MERC_LIMIT, lat))
    return math.radians(lon), math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


