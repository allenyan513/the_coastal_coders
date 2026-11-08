"""Reference photographs, identification notes and checked names for the species list.

Three hand-curated files sit next to species.csv, all written or checked with `ml/species_media.py`:

- species_media.json: photos, each with creator, licence, source page and how it was checked
- species_profiles.json: identification notes and the species each one is easily confused with
- species_taxonomy.json: every listed name checked against WoRMS (or GBIF when WoRMS lacks it)
- species_conservation.json: conservation or invasive status, written by hand from official sources

This module only reads them, so the Species page and, later, the video review screen share one
source of truth. None of them changes species.csv, which stays the list BioCLIP chooses from.
"""
import json
from functools import lru_cache

from . import config, species_library


def _read(path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("species", {})
    except (FileNotFoundError, ValueError):
        return {}


@lru_cache(maxsize=1)
def _taxonomy(mtime: float) -> dict:
    return _read(config.SPECIES_TAXONOMY)


def taxonomy(name: str) -> dict | None:
    """The WoRMS (or GBIF) check for one name, or None when it hasn't been checked."""
    try:
        mtime = config.SPECIES_TAXONOMY.stat().st_mtime
    except FileNotFoundError:
        return None
    return _taxonomy(mtime).get(name)


CONSERVATION_KINDS = {"at_risk", "invasive_ns"}
# What sort of statement each status is, so scientific assessments, legal listings and invasive
# classifications are never shown as one agreed status.
STATUS_TYPES = {"assessment", "legal", "introduced", "other"}


def _status_type(s: dict, kind: str) -> str:
    """The curated type, or one inferred from the authority for older entries without it."""
    if s.get("type") in STATUS_TYPES:
        return s["type"]
    a = str(s.get("authority", "")).lower()
    if a.startswith("cosewic"):
        return "assessment"
    if "species at risk act" in a or "endangered species act" in a:
        return "legal"
    return "introduced" if kind == "invasive_ns" else "other"


def _statuses(raw, kind: str) -> list[dict]:
    out = []
    for s in raw or []:
        if not (isinstance(s, dict) and s.get("authority") and s.get("status")):
            continue
        source = str(s.get("source") or "")
        out.append({
            "authority": str(s["authority"]), "status": str(s["status"]),
            "date": str(s.get("date") or ""), "note": str(s.get("note") or ""),
            "type": _status_type(s, kind),
            # Empty means the whole species (as far as this entry covers it); otherwise only the
            # population named, which the page must never present as the species' status.
            "population": str(s.get("population") or ""),
            "jurisdiction": str(s.get("jurisdiction") or ""),
            "source": source if source.startswith("https://") else "",
        })
    return out


def conservation() -> dict:
    """Verified conservation or invasive status by scientific name, from species_conservation.json.
    An entry is used only when it says what it is, when it was verified and where from; anything
    less is dropped, so a half-written entry can never show as a status. A species with no entry
    has no known status here, which the page must not present as safe."""
    out = {}
    for name, e in _read(config.SPECIES_CONSERVATION).items():
        if not isinstance(e, dict) or e.get("kind") not in CONSERVATION_KINDS or not e.get("badge") or not e.get("verified_on"):
            continue
        sources = [s for s in (e.get("sources") or []) if isinstance(s, dict) and str(s.get("url", "")).startswith("https://")]
        if not sources:
            continue
        statuses = _statuses(e.get("statuses"), e["kind"])
        out[name] = {
            "kind": e["kind"], "badge": str(e["badge"]), "verified_on": str(e["verified_on"]),
            # "populations" as soon as any status names a population: the badge then describes
            # some populations only, and the list and header must say so.
            "scope": "populations" if any(s["population"] for s in statuses) else "species",
            "population": e.get("population") or "",
            # Where it lived before and where wild fish are known now, kept apart on purpose.
            "historical_range": e.get("historical_range") or "",
            "current_range": e.get("current_range") or "",
            "range_note": e.get("range_note") or "",
            # The environment the known wild population lives in now, when it differs from WoRMS's
            # species-level list (e.g. a landlocked population of a once sea-run fish).
            "environment_now": e.get("environment_now") or "",
            "environment_now_note": e.get("environment_now_note") or "",
            "environment_historical": e.get("environment_historical") or "",
            "statuses": statuses,
            "significance": e.get("significance") or "",
            "threats": [t for t in (e.get("threats") or []) if isinstance(t, str) and t],
            "sources": [{"label": s.get("label") or s["url"], "url": s["url"]} for s in sources],
        }
    return out


def load(level: str = "guest") -> dict:
    """Images joined with identification notes by scientific name. Missing files give an empty
    result, so the app still runs without them. `level` (auth.level) decides which uploads show:
    guests get verified photos only, signed-in people pending ones too."""
    images, notes = _read(config.SPECIES_MEDIA), _read(config.SPECIES_PROFILES)
    # The Media Library's links and hidden photos, on top of the curated manifest (which it never changes).
    galleries = species_library.apply(curated_images(images), level)
    out = {}
    for name in images.keys() | notes.keys() | galleries.keys():
        entry = images.get(name, {"taxon": None, "images": []})
        out[name] = {**entry, "images": galleries.get(name, []), "profile": notes.get(name)}
    return out


def curated_images(images: dict | None = None) -> dict:
    """The curated photos by species, exactly as in species_media.json."""
    images = _read(config.SPECIES_MEDIA) if images is None else images
    return {name: [i for i in (e.get("images") or []) if isinstance(i, dict)] for name, e in images.items() if isinstance(e, dict)}


def compare_image(images: list[dict]) -> dict | None:
    """The photo a look-alike card shows: a side profile if there is one, else a photograph of any
    other view, else an illustration. Carries its credit, because CC BY needs it wherever it's shown."""
    rank = {"side": 0, "in_hand": 1, "underwater": 2, "other": 3, "illustration": 4}
    # Only checked photos: an upload pending review is never offered as the reference to compare with.
    usable = [i for i in images if isinstance(i, dict) and i.get("url") and i.get("review", "verified") == "verified"]
    if not usable:
        return None
    best = min(usable, key=lambda i: rank.get(i.get("view"), 5))
    return {
        "thumb": best.get("thumb_url") or best["url"],
        "view": best.get("view"),
        "creator": best.get("creator", ""),
        "license": best.get("license", ""),
        "license_url": best.get("license_url", ""),
        "source": best.get("source", ""),
        "source_url": best.get("source_url", ""),
    }


def summaries(level: str = "guest") -> dict:
    """One small record per curated species: enough for a table badge or a comparison card."""
    out = {}
    curated, status = load(level), conservation()
    for name in curated.keys() | status.keys():
        entry = curated.get(name, {})
        images = entry.get("images", [])
        out[name] = {
            "image_count": len(images),
            "thumb": (images[0].get("thumb_url") or images[0]["url"]) if images else None,
            "compare": compare_image(images),
            "has_profile": bool(entry.get("profile")),
            # Only verified statuses; a fish without one has no badge at all.
            "conservation": {k: status[name][k] for k in ("kind", "badge", "scope")} if name in status else None,
        }
    return out


def profile(name: str, level: str = "guest") -> dict:
    """The full entry for one species. Species nobody has curated still get their checked name and
    any entries that mention them, so the drawer can link back."""
    everything = load(level)
    entry = everything.get(name) or {"taxon": None, "images": [], "profile": None}
    # .get() throughout: these files are edited by hand, and one bad look-alike entry shouldn't
    # make every species' profile fail.
    mentioned_by = [
        {"species": other, "note": s.get("note") or ""}
        for other, e in sorted(everything.items())
        if other != name and isinstance(e.get("profile"), dict)
        for s in (e["profile"].get("similar") or [])
        if isinstance(s, dict) and s.get("species") == name
    ]
    return {
        "species": name,
        "curated": bool(entry.get("images") or entry.get("profile")),
        **entry,
        "names": taxonomy(name),
        "mentioned_by": mentioned_by,
        "conservation": conservation().get(name),
    }
