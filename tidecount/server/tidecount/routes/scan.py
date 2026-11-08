"""Fish Scan: one still picture, BioCLIP's top five species, nothing stored.

It uses the species model the video review already loads (`common.suggester`), so the two never
hold two copies of BioCLIP. The model loads the first time it's needed, or in the background as
soon as someone picks a picture to scan (`/api/scan/prepare`).
"""
import logging
import threading

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .. import models, scan, settings, species_library, species_media
from .common import suggester, suggester_state

router = APIRouter()
log = logging.getLogger("tidecount.scan")

# One scan at a time: the model is large, and a second request waits on the first anyway.
_busy = threading.BoundedSemaphore(1)
_loading = threading.Event()


def _state() -> str:
    state = suggester_state()
    return "loading" if state == "not_loaded" and _loading.is_set() else state


def _status() -> dict:
    return {
        "state": _state(),
        "species_count": len(models.species_list()),
        "top_k": scan.TOP_K,
        "max_bytes": scan.MAX_BYTES,
        "min_side": settings.current().species.min_side,
    }


@router.get("/api/scan/status")
def status():
    """Whether the species model is ready, still loading, not loaded yet, or unavailable here."""
    return _status()


def _load() -> None:
    try:
        suggester()
    except Exception:
        log.exception("Species model failed to load for Fish Scan")
    finally:
        _loading.clear()


@router.post("/api/scan/prepare")
def prepare():
    """Start loading the species model in the background, so the first scan doesn't wait for it.
    Does nothing when it's loaded or already loading."""
    if suggester_state() == "not_loaded" and not _loading.is_set():
        _loading.set()
        threading.Thread(target=_load, name="scan-model-load", daemon=True).start()
    return _status()


@router.post("/api/scan")
def scan_picture(
    file: UploadFile = File(...),
    x: float | None = Form(None),
    y: float | None = Form(None),
    w: float | None = Form(None),
    h: float | None = Form(None),
):
    """BioCLIP's top five species for a JPEG, PNG or WebP picture, optionally cropped to a box given
    as fractions of the picture. The picture is never saved, and nothing is recorded."""
    try:
        crop = scan.parse_crop(x, y, w, h)
        data = scan.read_limited(file.file)
        image = scan.open_image(data, crop)
    except scan.Invalid as e:
        raise HTTPException(400, str(e))
    finally:
        file.file.close()
    del data  # only the decoded, cropped picture is needed from here
    return _run(image, crop)


def _library_bytes(photo_id: str) -> bytes:
    """A Media Library photo's bytes: the stored file of an upload, or a curated photo fetched from its
    host. Only photos the library knows by id, so this can't be pointed at any other address."""
    found = species_library.file_of(photo_id)
    if found:
        with open(found[0], "rb") as f:
            return scan.read_limited(f)
    for images in species_media.curated_images().values():
        for img in images:
            if isinstance(img, dict) and img.get("id") == photo_id and img.get("url"):
                return scan.fetch_url(str(img["url"]))
    raise HTTPException(404, "That photo isn't in the Media Library")


@router.post("/api/scan/photo")
def scan_library_photo(
    photo_id: str = Form(...),
    x: float | None = Form(None),
    y: float | None = Form(None),
    w: float | None = Form(None),
    h: float | None = Form(None),
):
    """The same scan for a photo already in the Media Library, named by its id. The server reads it
    itself, so a curated photo hosted elsewhere isn't blocked by the browser's cross-site rules.
    A rejected upload isn't offered. Nothing is saved or recorded."""
    try:
        crop = scan.parse_crop(x, y, w, h)
        rejected = species_library.read()["photos"].get(photo_id, {}).get("review") == "rejected"
        if rejected:
            raise HTTPException(404, "That photo isn't in the Media Library")
        image = scan.open_image(_library_bytes(photo_id), crop)
    except scan.Invalid as e:
        raise HTTPException(400, str(e))
    return _run(image, crop)


def _run(image, crop):
    """Run the species model on a checked, cropped picture and shape the answer."""
    if not _busy.acquire(blocking=False):
        raise HTTPException(503, "Another scan is running. Try again in a moment.", headers={"Retry-After": "3"})
    try:
        model = suggester()
        if isinstance(model, models.NullSuggester):
            raise HTTPException(503, "The species model couldn't be loaded on this computer, so pictures can't be scanned.")
        try:
            found = scan.scan(model, image)
        except Exception:
            log.exception("Fish Scan failed")
            raise HTTPException(500, "The scan failed. Try another picture, or try again.")
    finally:
        _busy.release()

    min_side = settings.current().species.min_side
    return {
        "suggestions": found,
        "model": model.name,
        "species_count": len(models.species_list()),
        "scanned": {"width": image.width, "height": image.height, "cropped": crop is not None},
        "small": min(image.size) < min_side,
        "min_side": min_side,
    }
