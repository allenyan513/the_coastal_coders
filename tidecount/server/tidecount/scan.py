"""Fish Scan: BioCLIP's top species for one still picture, kept apart from video analysis.

The picture is read into memory, checked, optionally cropped to the fish, and passed to the same
species model the video review uses. Nothing is written: not to the Media Library, not to the
database, not to the event log. The bytes are dropped when the request ends.

Uploads are checked the way the Media Library checks them: the same size limit and the same
file-type detection from the first bytes, never the file name or the browser's content type.
"""
import io
import math
import urllib.error
import urllib.request

from PIL import Image, ImageOps, UnidentifiedImageError

from . import species_library
from .occurrences import UA

MAX_BYTES = species_library.MAX_BYTES
# A decoded picture this large needs about 200 MB of memory; a phone photo is 12 to 50 million pixels.
MAX_PIXELS = 60_000_000
# Below this the crop is too small to say anything about a fish.
MIN_CROP_SIDE = 16
TOP_K = 5


class Invalid(ValueError):
    """The picture or the crop can't be scanned; the message says what to fix."""


def read_limited(stream) -> bytes:
    """The whole upload, refusing it as soon as it passes the size limit, so a huge file never fills memory."""
    chunks, size = [], 0
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_BYTES:
            raise Invalid(f"The picture is larger than {MAX_BYTES // (1024 * 1024)} MB")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise Invalid("The file is empty")
    return data


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """A photo host may redirect to its CDN, but never off https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise urllib.error.URLError("redirected away from https")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url(url: str, timeout: float = 20) -> bytes:
    """A curated reference photo from the site that hosts it (iNaturalist or Wikimedia Commons),
    read straight into memory with the same size limit as an upload. Only called with a URL taken
    from the curated manifest, never one a person typed."""
    if not url.startswith("https://"):
        raise Invalid("That photo isn't available to scan.")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*"})
    try:
        with urllib.request.build_opener(_HttpsOnly).open(req, timeout=timeout) as r:
            return read_limited(r)
    except Invalid:
        raise
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise Invalid("Couldn't get this photo from where it's hosted. Check the internet connection, or save the photo and upload it instead.")


def parse_crop(x, y, w, h) -> tuple[float, float, float, float] | None:
    """A crop box as fractions of the picture (0 to 1, from the top left), or None for the whole picture.
    It is all four values or none of them."""
    given = [v for v in (x, y, w, h) if v is not None]
    if not given:
        return None
    if len(given) != 4:
        raise Invalid("A crop needs x, y, w and h")
    if not all(math.isfinite(v) for v in given):
        raise Invalid("The crop must be numbers")
    eps = 1e-6
    if x < -eps or y < -eps or w <= 0 or h <= 0 or x + w > 1 + eps or y + h > 1 + eps:
        raise Invalid("The crop must lie inside the picture")
    return (max(0.0, x), max(0.0, y), w, h)


def open_image(data: bytes, crop: tuple[float, float, float, float] | None = None) -> Image.Image:
    """The picture as RGB, turned the way the camera held it, then cropped. Refuses anything that
    isn't a JPEG, PNG or WebP, and pictures too large to decode safely."""
    if not species_library._sniff(data[:16]):
        raise Invalid("Only JPEG, PNG and WebP pictures can be scanned")
    try:
        image = Image.open(io.BytesIO(data))
        # The size is in the header, so this is checked before any pixels are decoded.
        if image.width * image.height > MAX_PIXELS:
            raise Invalid(f"The picture is too large to scan (more than {MAX_PIXELS // 1_000_000} million pixels)")
        image.load()
    except Invalid:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise Invalid("The picture couldn't be read. It may be damaged or not really an image.")
    # The browser shows a phone photo turned upright, and the crop was drawn on that, so turn it here too.
    image = ImageOps.exif_transpose(image).convert("RGB")
    if crop:
        x, y, w, h = crop
        box = (round(x * image.width), round(y * image.height), round((x + w) * image.width), round((y + h) * image.height))
        box = (max(0, box[0]), max(0, box[1]), min(image.width, box[2]), min(image.height, box[3]))
        if box[2] - box[0] < MIN_CROP_SIDE or box[3] - box[1] < MIN_CROP_SIDE:
            raise Invalid(f"The crop is too small. Make it at least {MIN_CROP_SIDE} pixels each way.")
        image = image.crop(box)
    return image


def scan(suggester, image: Image.Image, k: int = TOP_K) -> list[dict]:
    """The model's top `k` species for the picture, best first, each with its rank."""
    found = suggester.suggest([image], k)[0]
    return [
        {"rank": i + 1, "species": s["species"], "common": s["common"], "score": round(float(s["score"]), 6)}
        for i, s in enumerate(found)
    ]
