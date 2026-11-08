"""Fish Scan: one picture, BioCLIP's top five, checked like a Media Library upload, and nothing stored."""
import io
import sqlite3

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tidecount import config, db, models, scan
from tidecount.app import app
from tidecount.routes import scan as scan_routes

client = TestClient(app)


class FakeSuggester:
    """Stands in for BioCLIP: the first species on the list score highest. Remembers what it was given."""
    name = "Fake BioCLIP"

    def __init__(self):
        self.seen: list[Image.Image] = []

    def suggest(self, crops, k=3):
        self.seen.extend(crops)
        top = models.species_list()[:k]
        return [[{**s, "score": 0.5 / (i + 1)} for i, s in enumerate(top)] for _ in crops]


@pytest.fixture(autouse=True)
def fake_model(monkeypatch, tmp_path):
    # Never load the real model in tests, and keep the Media Library somewhere we can watch.
    fake = FakeSuggester()
    monkeypatch.setattr(scan_routes, "suggester", lambda: fake)
    monkeypatch.setattr(config, "SPECIES_LIBRARY", tmp_path / "species_library")
    return fake


def picture(size=(200, 100), fmt="JPEG", exif=None) -> bytes:
    out = io.BytesIO()
    image = Image.new("RGB", size, (20, 90, 160))
    if exif is not None:
        image.save(out, fmt, exif=exif)
    else:
        image.save(out, fmt)
    return out.getvalue()


def post(data: bytes, name="fish.jpg", **crop):
    return client.post("/api/scan", files={"file": (name, io.BytesIO(data), "image/jpeg")}, data={k: str(v) for k, v in crop.items()})


def events() -> int:
    with sqlite3.connect(db.DB_PATH) as con:
        return con.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def test_a_scan_returns_the_top_five_with_both_names_and_scores(fake_model):
    r = post(picture())
    assert r.status_code == 200, r.text
    body = r.json()
    listed = models.species_list()
    assert [s["rank"] for s in body["suggestions"]] == [1, 2, 3, 4, 5]
    assert [s["species"] for s in body["suggestions"]] == [s["species"] for s in listed[:5]]
    assert all(s["common"] and isinstance(s["score"], float) for s in body["suggestions"])
    assert body["model"] == "Fake BioCLIP"
    assert body["species_count"] == len(listed)
    assert body["scanned"] == {"width": 200, "height": 100, "cropped": False}
    assert len(fake_model.seen) == 1 and fake_model.seen[0].mode == "RGB"


def test_png_and_webp_scan_too():
    assert post(picture(fmt="PNG"), "fish.png").status_code == 200
    assert post(picture(fmt="WEBP"), "fish.webp").status_code == 200


def test_nothing_is_stored(tmp_path):
    before = events()
    assert post(picture()).status_code == 200
    assert post(picture(), x=0.1, y=0.1, w=0.5, h=0.5).status_code == 200
    assert events() == before  # no event, no track, no decision
    assert not (tmp_path / "species_library").exists()  # nothing in the Media Library
    assert all(p["kind"] == "curated" for p in client.get("/api/species/library").json()["photos"])


def test_the_crop_is_what_the_model_sees(fake_model):
    r = post(picture((200, 100)), x=0.25, y=0.5, w=0.5, h=0.5)
    assert r.status_code == 200
    assert r.json()["scanned"] == {"width": 100, "height": 50, "cropped": True}
    assert fake_model.seen[-1].size == (100, 50)


def test_a_phone_photo_is_turned_upright_before_the_crop(fake_model):
    # Stored 200 wide by 100 high, tagged "turn 90 degrees": shown, and scanned, 100 wide by 200 high.
    exif = Image.Exif()
    exif[0x0112] = 6
    r = post(picture((200, 100), exif=exif), x=0, y=0, w=1, h=0.5)
    assert r.status_code == 200
    assert fake_model.seen[-1].size == (100, 100)


def test_a_small_picture_is_flagged(fake_model):
    body = post(picture((40, 40))).json()
    assert body["small"] is True and body["min_side"] == 64
    assert post(picture((300, 300))).json()["small"] is False


@pytest.mark.parametrize("data", [
    b"<svg onload=alert(1)>",            # not an image at all
    b"",                                 # empty
    b"\xff\xd8\xff\xe0" + b"\x00" * 64,  # says JPEG, but isn't one
    b"GIF89a" + b"\x00" * 64,            # an image, but not a kind we scan
])
def test_only_real_jpeg_png_and_webp_are_scanned(data, fake_model):
    r = post(data)
    assert r.status_code == 400
    assert not fake_model.seen


def test_a_file_over_the_limit_is_refused(monkeypatch, fake_model):
    monkeypatch.setattr(scan, "MAX_BYTES", 1000)
    r = post(picture((400, 400)))
    assert r.status_code == 400 and "larger than" in r.json()["detail"]
    assert not fake_model.seen


def test_a_picture_with_too_many_pixels_is_refused_before_decoding(monkeypatch, fake_model):
    monkeypatch.setattr(scan, "MAX_PIXELS", 10_000)
    r = post(picture((200, 100)))
    assert r.status_code == 400 and "too large" in r.json()["detail"]
    assert not fake_model.seen


@pytest.mark.parametrize("crop", [
    {"x": 0.1, "y": 0.1},                           # not all four
    {"x": 0.6, "y": 0, "w": 0.6, "h": 1},           # runs off the right edge
    {"x": -0.2, "y": 0, "w": 0.5, "h": 0.5},        # starts outside
    {"x": 0, "y": 0, "w": 0, "h": 0.5},             # no width
    {"x": 0, "y": 0, "w": 0.01, "h": 0.01},         # a couple of pixels
    {"x": "nan", "y": 0, "w": 0.5, "h": 0.5},       # not a number
])
def test_a_bad_crop_is_refused(crop, fake_model):
    r = post(picture(), **crop)
    assert r.status_code in (400, 422)
    assert not fake_model.seen


def test_one_scan_at_a_time():
    assert scan_routes._busy.acquire(blocking=False)
    try:
        r = post(picture())
        assert r.status_code == 503 and r.headers["retry-after"]
    finally:
        scan_routes._busy.release()
    assert post(picture()).status_code == 200


def test_a_model_that_failed_to_load_says_so(monkeypatch):
    monkeypatch.setattr(scan_routes, "suggester", lambda: models.NullSuggester())
    r = post(picture())
    assert r.status_code == 503 and "couldn't be loaded" in r.json()["detail"]


CREDIT = {"creator": "A. Researcher", "license": "Own photo, used with permission", "view": "side"}


def library_upload(data: bytes) -> dict:
    r = client.post("/api/species/library", files={"file": ("fish.jpg", io.BytesIO(data), "image/jpeg")}, data=CREDIT)
    assert r.status_code in (200, 201), r.text
    return r.json()


def post_photo(photo_id: str, **crop):
    return client.post("/api/scan/photo", data={"photo_id": photo_id, **{k: str(v) for k, v in crop.items()}})


def curated_photo() -> dict:
    from tidecount import species_media
    for images in species_media.curated_images().values():
        for img in images:
            if isinstance(img, dict) and img.get("id") and str(img.get("url", "")).startswith("https://"):
                return img
    raise AssertionError("no curated photo in the manifest")


def test_a_library_upload_is_scanned_from_its_id_and_stays_in_the_library(fake_model):
    photo = library_upload(picture((200, 100)))
    r = post_photo(photo["id"], x=0, y=0, w=0.5, h=1)
    assert r.status_code == 200, r.text
    assert r.json()["scanned"] == {"width": 100, "height": 100, "cropped": True}
    assert fake_model.seen[-1].size == (100, 100)
    # Scanning didn't add, remove or change anything in the library.
    assert [p["id"] for p in client.get("/api/species/library").json()["photos"] if p["kind"] == "upload"] == [photo["id"]]


def test_a_curated_photo_is_fetched_by_the_server_from_its_manifest_url(monkeypatch, fake_model):
    img = curated_photo()
    asked = []
    monkeypatch.setattr(scan, "fetch_url", lambda url, timeout=20: asked.append(url) or picture((300, 200)))
    r = post_photo(img["id"])
    assert r.status_code == 200, r.text
    assert asked == [img["url"]]  # exactly the manifest's address, nothing a person sent
    assert r.json()["scanned"] == {"width": 300, "height": 200, "cropped": False}


def test_a_photo_that_cant_be_fetched_says_so(monkeypatch):
    def down(url, timeout=20):
        raise scan.Invalid("Couldn't get this photo from where it's hosted.")
    monkeypatch.setattr(scan, "fetch_url", down)
    r = post_photo(curated_photo()["id"])
    assert r.status_code == 400 and "Couldn't get this photo" in r.json()["detail"]


def test_an_unknown_or_rejected_photo_is_not_scanned(fake_model):
    assert post_photo("upload-000000000000").status_code == 404
    assert post_photo("../../etc/passwd").status_code == 404
    photo = library_upload(picture())
    client.patch(f"/api/species/library/{photo['id']}", json={"review": "rejected"})
    assert post_photo(photo["id"]).status_code == 404
    assert not fake_model.seen


def test_the_fetch_takes_only_https_and_stays_under_the_size_limit(monkeypatch):
    with pytest.raises(scan.Invalid):
        scan.fetch_url("http://example.com/fish.jpg")
    with pytest.raises(scan.Invalid):
        scan.fetch_url("file:///c:/windows/win.ini")

    class Big:
        def __init__(self): self.left = scan.MAX_BYTES + 10
        def read(self, n):
            n = min(n, self.left); self.left -= n
            return b"\0" * n
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class Opener:
        def open(self, req, timeout=None): return Big()

    monkeypatch.setattr(scan.urllib.request, "build_opener", lambda *h: Opener())
    with pytest.raises(scan.Invalid, match="larger than"):
        scan.fetch_url("https://example.com/huge.jpg")


def test_a_redirect_off_https_is_refused():
    handler = scan._HttpsOnly()
    with pytest.raises(scan.urllib.error.URLError):
        handler.redirect_request(scan.urllib.request.Request("https://a.example/x"), None, 302, "Found", {}, "http://evil.example/x")


def test_status_and_prepare(monkeypatch):
    calls = []
    monkeypatch.setattr(scan_routes, "suggester_state", lambda: "not_loaded")
    monkeypatch.setattr(scan_routes, "_load", lambda: calls.append(1))
    body = client.get("/api/scan/status").json()
    assert body["state"] == "not_loaded" and body["top_k"] == 5 and body["species_count"] == len(models.species_list())
    # Prepare starts one background load; asking again while it's loading starts no second one.
    threads = []
    monkeypatch.setattr(scan_routes.threading, "Thread", lambda **kw: threads.append(kw) or type("T", (), {"start": lambda self: None})())
    try:
        assert client.post("/api/scan/prepare").json()["state"] == "loading"
        assert client.post("/api/scan/prepare").json()["state"] == "loading"
        assert len(threads) == 1
    finally:
        scan_routes._loading.clear()
    monkeypatch.setattr(scan_routes, "suggester_state", lambda: "ready")
    assert client.post("/api/scan/prepare").json()["state"] == "ready"
    assert len(threads) == 1
