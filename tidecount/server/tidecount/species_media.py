"""Reference photographs, identification notes and checked names for the species list.

Three hand-curated files sit next to species.csv, all written or checked with `ml/species_media.py`:

- species_media.json: photos, each with creator, licence, source page and how it was checked
- species_profiles.json: identification notes and the species each one is easily confused with
- species_taxonomy.json: every listed name checked against WoRMS (or GBIF when WoRMS lacks it)

This module only reads them, so the Species page and, later, the video review screen share one
source of truth. None of them changes species.csv, which stays the list BioCLIP chooses from.
"""
import json
from functools import lru_cache

from . import config


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


def load() -> dict:
    """Images joined with identification notes by scientific name. Missing files give an empty
    result, so the app still runs without them."""
    images, notes = _read(config.SPECIES_MEDIA), _read(config.SPECIES_PROFILES)
    out = {}
    for name in images.keys() | notes.keys():
        entry = images.get(name, {"taxon": None, "images": []})
        out[name] = {**entry, "profile": notes.get(name)}
    return out


def compare_image(images: list[dict]) -> dict | None:
    """The photo a look-alike card shows: a side profile if there is one, else a photograph of any
    other view, else an illustration. Carries its credit, because CC BY needs it wherever it's shown."""
    rank = {"side": 0, "in_hand": 1, "underwater": 2, "other": 3, "illustration": 4}
    usable = [i for i in images if isinstance(i, dict) and i.get("url")]
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


def summaries() -> dict:
    """One small record per curated species: enough for a table badge or a comparison card."""
    out = {}
    for name, entry in load().items():
        images = entry.get("images", [])
        out[name] = {
            "image_count": len(images),
            "thumb": (images[0].get("thumb_url") or images[0]["url"]) if images else None,
            "compare": compare_image(images),
            "has_profile": bool(entry.get("profile")),
        }
    return out


def profile(name: str) -> dict:
    """The full entry for one species. Species nobody has curated still get their checked name and
    any entries that mention them, so the drawer can link back."""
    everything = load()
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
    }
