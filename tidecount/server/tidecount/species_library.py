"""The Media Library: reference photos people upload, and which species each photo is shown on.

Two kinds of photo appear in a species' gallery:

- curated: the Wikimedia Commons and iNaturalist photos in species_media.json. They are hosted by
  those sites, checked with `ml/species_media.py`, and never changed or deleted from here.
- uploads: files people add in the Media Library. Each file is stored once under
  config.SPECIES_LIBRARY and starts as "pending" review, so it is never taken for a verified
  identification reference until a person marks it so.

Everything editable sits in one file, library.json, beside the uploaded files:

    {"version": 1,
     "photos": {"<upload id>": {...credit, view, review...}},
     "links":  {"<species>": ["<photo id>", ...]},    # extra photos shown on a species, uploads or
                                                      # curated photos of another species
     "hidden": {"<species>": ["<curated id>", ...]}}  # its own curated photos taken off its gallery

Unlinking a photo from a species only edits `links` or `hidden`. The file, and the curated
manifest, stay as they are. A photo with no links stays in the library.
"""
import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from datetime import date
from pathlib import Path

from . import config

VIEWS = ("side", "underwater", "in_hand", "illustration", "other")
REVIEW = ("pending", "verified", "rejected")
MAX_BYTES = 15 * 1024 * 1024
# Detected from the file's first bytes, never from its name or the browser's content type.
KINDS = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
TEXT_LIMITS = {"caption": 300, "creator": 200, "license": 200, "license_url": 500, "source": 200, "source_url": 500, "place": 200}
REVIEW_TEXT = {
    "pending": "Uploaded to Tideflow. Pending review: not yet checked as an identification reference.",
    "verified": "Uploaded to Tideflow. Checked by a person as an identification reference.",
    "rejected": "Uploaded to Tideflow. Rejected in review.",
}

_lock = threading.Lock()


class Invalid(ValueError):
    """Something the person sent can't be stored; the message says what to fix."""


def _folder() -> Path:
    return config.SPECIES_LIBRARY


def _manifest() -> Path:
    return _folder() / "library.json"


def read() -> dict:
    """The library as stored. A missing or unreadable file is an empty library."""
    try:
        with open(_manifest(), encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    for key in ("photos", "links", "hidden"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    data["version"] = 1
    return data


def _write(data: dict) -> None:
    """Replace library.json in one step, so a crash mid-write can't leave half a file."""
    _folder().mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_folder(), prefix=".library-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _manifest())
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _sniff(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _https(value: str, field: str) -> str:
    if value and not value.startswith("https://"):
        raise Invalid(f"{field.replace('_', ' ').capitalize()} must start with https://")
    return value


def clean_fields(raw: dict, partial: bool = False) -> dict:
    """Credit, view and review fields, trimmed and checked. With `partial`, only the fields given."""
    out = {}
    for key, limit in TEXT_LIMITS.items():
        if key in raw or not partial:
            value = str(raw.get(key) or "").strip()
            if len(value) > limit:
                raise Invalid(f"{key.replace('_', ' ').capitalize()} is too long (at most {limit} characters)")
            out[key] = value
    for key in ("license_url", "source_url"):
        if key in out:
            _https(out[key], key)
    for key in ("creator", "license"):
        if key in out and not out[key]:
            raise Invalid("Say who took the photo" if key == "creator" else "Give the licence or the permission to use the photo")
    if "view" in raw or not partial:
        view = str(raw.get("view") or "other")
        if view not in VIEWS:
            raise Invalid(f"Photo type must be one of {', '.join(VIEWS)}")
        out["view"] = view
    if "review" in raw:
        if raw["review"] not in REVIEW:
            raise Invalid(f"Review status must be one of {', '.join(REVIEW)}")
        out["review"] = raw["review"]
    return out


def add_upload(stream, fields: dict) -> tuple[dict, bool]:
    """Store an uploaded image once and add it to the library as pending review, linked to no species.
    The same file uploaded again returns the photo already stored (and `False`), so no file is kept twice."""
    meta = clean_fields(fields)
    meta.pop("review", None)  # uploads always start pending
    if not meta["source"]:
        meta["source"] = "Uploaded to Tideflow"
    folder = _folder() / "files"
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".upload-")
    digest, size, head = hashlib.sha256(), 0, b""
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise Invalid(f"The photo is larger than {MAX_BYTES // (1024 * 1024)} MB")
                if len(head) < 16:
                    head += chunk[:16]
                digest.update(chunk)
                out.write(chunk)
        kind = _sniff(head)
        if not kind:
            raise Invalid("Only JPEG, PNG and WebP photos can be uploaded")
        sha = digest.hexdigest()
        with _lock:
            data = read()
            for photo in data["photos"].values():
                if photo.get("sha256") == sha:
                    return photo, False
            photo_id = f"upload-{uuid.uuid4().hex[:12]}"
            name = f"{photo_id}.{kind}"
            os.replace(tmp, folder / name)
            tmp = None
            photo = {"id": photo_id, "file": name, "sha256": sha, "bytes": size, **meta, "review": "pending", "added_on": date.today().isoformat()}
            data["photos"][photo_id] = photo
            _write(data)
            return photo, True
    finally:
        if tmp:
            Path(tmp).unlink(missing_ok=True)


def update(photo_id: str, fields: dict) -> dict:
    """Change an upload's credit, photo type or review status."""
    changes = clean_fields(fields, partial=True)
    with _lock:
        data = read()
        photo = data["photos"].get(photo_id)
        if not photo:
            raise KeyError(photo_id)
        if "source" in changes and not changes["source"]:
            changes["source"] = "Uploaded to Tideflow"
        photo.update(changes)
        _write(data)
        return photo


def file_of(photo_id: str, level: str = "guest") -> tuple[Path, str] | None:
    """The stored file and its content type, or None for an unknown id or one this viewer may not see
    (so a guest can't fetch a pending photo by guessing its address)."""
    photo = read()["photos"].get(photo_id)
    if not photo or not visible(photo.get("review", "pending"), level) or not re.fullmatch(r"upload-[0-9a-f]{12}\.(jpg|png|webp)", str(photo.get("file", ""))):
        return None
    path = _folder() / "files" / photo["file"]
    return (path, KINDS[photo["file"].rsplit(".", 1)[1]]) if path.is_file() else None


def as_image(photo: dict) -> dict:
    """An upload shaped like a curated image, so the gallery and credits show it the same way."""
    url = f"/api/species/library/{photo['id']}/file"
    return {
        "id": photo["id"], "url": url, "thumb_url": url, "view": photo.get("view", "other"),
        "caption": photo.get("caption", ""), "creator": photo.get("creator", ""),
        "license": photo.get("license", ""), "license_url": photo.get("license_url", ""),
        "source": photo.get("source", ""), "source_url": photo.get("source_url", ""),
        "place": photo.get("place", ""), "review": photo.get("review", "pending"), "kind": "upload",
        "verification": REVIEW_TEXT.get(photo.get("review", "pending"), REVIEW_TEXT["pending"]),
    }


def _curated_index(curated: dict) -> dict:
    """Every curated image by id, with the species it belongs to."""
    out = {}
    for species, images in curated.items():
        for img in images:
            if isinstance(img, dict) and img.get("id"):
                out[img["id"]] = {**img, "review": "verified", "kind": "curated", "home": species}
    return out


def visible(review: str, level: str) -> bool:
    """Who may see a photo, by its review status and the viewer's level (auth.level): guests see
    verified photos only; anyone signed in also sees pending ones; rejected ones only managers, in
    the Media Library, so they can be reviewed again or deleted."""
    if review == "verified":
        return True
    if review == "pending":
        return level in ("user", "manager")
    return level == "manager"


def apply(curated: dict, level: str = "guest") -> dict:
    """Each species' gallery after the library's edits: its curated photos minus the hidden ones,
    then the photos linked to it that this viewer may see (rejected uploads never appear on a
    profile). `curated` maps species to images."""
    data = read()
    index = _curated_index(curated)
    out = {}
    for species in curated.keys() | data["links"].keys():
        hidden = set(data["hidden"].get(species) or [])
        images = [{**img, "review": "verified", "kind": "curated"} for img in curated.get(species, []) if isinstance(img, dict) and img.get("id") not in hidden]
        for pid in data["links"].get(species) or []:
            if pid in data["photos"]:
                review = data["photos"][pid].get("review", "pending")
                if review != "rejected" and visible(review, level):
                    images.append(as_image(data["photos"][pid]))
            elif pid in index:
                img = {k: v for k, v in index[pid].items() if k != "home"}
                images.append(img)
        out[species] = images
    return out


def catalogue(curated: dict, level: str = "guest") -> list[dict]:
    """Every photo in the library this viewer may see, uploads first, each with the species it is shown on."""
    data = read()
    shown_on: dict[str, list[str]] = {}
    for species, ids in data["links"].items():
        for pid in ids or []:
            shown_on.setdefault(pid, []).append(species)
    items = []
    for photo in sorted(data["photos"].values(), key=lambda p: p.get("added_on", ""), reverse=True):
        if not visible(photo.get("review", "pending"), level):
            continue
        items.append({**as_image(photo), "added_on": photo.get("added_on", ""), "species": sorted(shown_on.get(photo["id"], []))})
    for pid, img in _curated_index(curated).items():
        home = img.pop("home")
        on = ([] if pid in (data["hidden"].get(home) or []) else [home]) + shown_on.get(pid, [])
        items.append({**img, "added_on": img.get("added_on", ""), "home": home, "species": sorted(set(on))})
    return items


class Protected(Exception):
    """A curated Wikimedia Commons or iNaturalist photo, which is never deleted from here."""


def delete(photo_id: str, curated: dict) -> list[str]:
    """Permanently delete an uploaded photo: its entry, its links on every species, then its file.
    Returns the species it was shown on. Curated photos raise Protected; unknown ids KeyError."""
    if photo_id in _curated_index(curated):
        raise Protected(photo_id)
    with _lock:
        data = read()
        photo = data["photos"].pop(photo_id, None)
        if photo is None:
            raise KeyError(photo_id)
        was_on = []
        for species in list(data["links"]):
            ids = data["links"][species] or []
            if photo_id in ids:
                was_on.append(species)
                rest = [pid for pid in ids if pid != photo_id]
                if rest:
                    data["links"][species] = rest
                else:
                    del data["links"][species]
        # The manifest goes first: if removing the file then fails, nothing points at it any more.
        _write(data)
        name = str(photo.get("file", ""))
        if re.fullmatch(r"upload-[0-9a-f]{12}\.(jpg|png|webp)", name):
            (_folder() / "files" / name).unlink(missing_ok=True)
        return sorted(was_on)


def set_species_photos(species: str, ids: list[str], curated: dict) -> None:
    """Make `ids` the photos shown on `species`, in one save. Its own curated photos left out are
    hidden there; anything else is linked. Nothing is deleted. Unknown ids are refused."""
    seen, wanted = set(), []
    for pid in ids:
        if isinstance(pid, str) and pid not in seen:
            seen.add(pid)
            wanted.append(pid)
    own = [img["id"] for img in curated.get(species, []) if isinstance(img, dict) and img.get("id")]
    index = _curated_index(curated)
    with _lock:
        data = read()
        unknown = [pid for pid in wanted if pid not in data["photos"] and pid not in index]
        if unknown:
            raise Invalid(f"Not in the Media Library: {', '.join(unknown[:3])}")
        hidden = [pid for pid in own if pid not in seen]
        links = [pid for pid in wanted if pid not in own]
        for key, value in (("hidden", hidden), ("links", links)):
            if value:
                data[key][species] = value
            else:
                data[key].pop(species, None)
        _write(data)
