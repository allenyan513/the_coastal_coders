"""The Media Library: uploads stored once, pending review, linked to species and unlinked without deleting."""
import io

import pytest
from fastapi.testclient import TestClient

from tidecount import config, models, species_library, species_media
from tidecount.app import app

client = TestClient(app)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
CREDIT = {"creator": "A. Researcher", "license": "Own photo, used with permission", "view": "side"}


@pytest.fixture(autouse=True)
def library(monkeypatch, tmp_path):
    # Every test starts with an empty library; the curated manifest is the real one, read only.
    monkeypatch.setattr(config, "SPECIES_LIBRARY", tmp_path / "species_library")
    yield tmp_path / "species_library"


def upload(data=JPEG, **fields):
    return client.post("/api/species/library", files={"file": ("fish.jpg", io.BytesIO(data), "image/jpeg")}, data={**CREDIT, **fields})


def cod_profile():
    return client.get("/api/species/Gadus morhua/profile").json()


def test_an_upload_is_stored_once_pending_and_linked_to_no_species(library):
    r = upload()
    assert r.status_code == 201
    photo = r.json()
    assert photo["review"] == "pending" and photo["kind"] == "upload"
    assert "Pending review" in photo["verification"]
    assert photo["url"] == f"/api/species/library/{photo['id']}/file"
    again = upload()
    assert again.status_code == 200 and again.json()["id"] == photo["id"] and again.json()["duplicate"]
    assert len(list((library / "files").iterdir())) == 1
    listed = [p for p in client.get("/api/species/library").json()["photos"] if p["id"] == photo["id"]]
    assert listed and listed[0]["species"] == []
    f = client.get(photo["url"])
    assert f.status_code == 200 and f.headers["content-type"] == "image/jpeg" and f.content == JPEG


def test_an_upload_needs_a_real_image_and_a_credit():
    assert upload(data=b"<svg onload=alert(1)>").status_code == 400
    assert upload(creator="").status_code == 400
    assert upload(license="").status_code == 400
    assert upload(view="selfie").status_code == 400
    assert upload(source_url="http://example.com").status_code == 400
    assert client.get("/api/species/library").json()["photos"][0]["kind"] == "curated"  # nothing uploaded


def test_linking_shows_a_photo_on_several_species_and_unlinking_keeps_it():
    pid = upload().json()["id"]
    own = [i["id"] for i in cod_profile()["images"]]
    assert client.put("/api/species/Gadus morhua/photos", json={"ids": own + [pid]}).status_code == 200
    assert client.put("/api/species/Pollachius virens/photos", json={"ids": [pid]}).status_code == 200
    assert pid in [i["id"] for i in cod_profile()["images"]]
    pollock = client.get("/api/species/Pollachius virens/profile").json()
    assert pid in [i["id"] for i in pollock["images"]]

    client.put("/api/species/Gadus morhua/photos", json={"ids": own})
    assert pid not in [i["id"] for i in cod_profile()["images"]]
    item = next(p for p in client.get("/api/species/library").json()["photos"] if p["id"] == pid)
    assert item["species"] == ["Pollachius virens"]
    assert client.get(f"/api/species/library/{pid}/file").status_code == 200


def test_hiding_a_curated_photo_only_unlinks_it_and_never_touches_the_manifest():
    before = config.SPECIES_MEDIA.read_bytes()
    own = [i["id"] for i in cod_profile()["images"]]
    assert own, "cod has curated photos"
    client.put("/api/species/Gadus morhua/photos", json={"ids": own[1:]})
    assert [i["id"] for i in cod_profile()["images"]] == own[1:]
    item = next(p for p in client.get("/api/species/library").json()["photos"] if p["id"] == own[0])
    assert item["kind"] == "curated" and item["review"] == "verified" and item["species"] == []
    client.put("/api/species/Gadus morhua/photos", json={"ids": own})
    assert [i["id"] for i in cod_profile()["images"]] == own
    assert config.SPECIES_MEDIA.read_bytes() == before


def test_a_curated_photo_keeps_its_credit_and_source_links():
    img = cod_profile()["images"][0]
    assert img["kind"] == "curated" and img["review"] == "verified"
    assert img["source_url"].startswith("https://") and img["license_url"].startswith("https://") and img["creator"]


def test_unknown_ids_and_unlisted_species_are_refused_without_saving(library):
    assert client.put("/api/species/Gadus morhua/photos", json={"ids": ["nope"]}).status_code == 400
    assert client.put("/api/species/Homo sapiens/photos", json={"ids": []}).status_code == 404
    assert not (library / "library.json").exists()


def test_pending_uploads_are_never_the_comparison_reference_and_rejected_ones_are_hidden():
    pid = upload(data=PNG).json()["id"]
    client.put("/api/species/Mola mola/photos", json={"ids": [i["id"] for i in client.get("/api/species/Mola mola/profile").json()["images"]] + [pid]})
    summary = client.get("/api/species/media").json()["Mola mola"]
    assert summary["compare"] is None or not summary["compare"]["thumb"].startswith("/api/species/library/")
    assert client.patch(f"/api/species/library/{pid}", json={"review": "verified"}).json()["review"] == "verified"
    assert client.patch(f"/api/species/library/{pid}", json={"review": "maybe"}).status_code == 400
    client.patch(f"/api/species/library/{pid}", json={"review": "rejected"})
    assert pid not in [i["id"] for i in client.get("/api/species/Mola mola/profile").json()["images"]]
    assert client.patch("/api/species/library/" + "gadus_morhua-1", json={"caption": "x"}).status_code == 404


def test_the_ai_list_is_untouched():
    upload()
    assert len(models.species_list()) == 182
    assert species_media.curated_images()  # the manifest still reads as before
    assert species_library.read()["links"] == {}


# --- permanent deletion (managers, after a recent password confirmation) -----------------------

def test_deleting_an_upload_removes_its_file_and_every_link(library):
    pid = upload().json()["id"]
    keep = upload(data=PNG).json()["id"]
    cod = [i["id"] for i in cod_profile()["images"]]
    client.put("/api/species/Gadus morhua/photos", json={"ids": cod + [pid, keep]})
    client.put("/api/species/Pollachius virens/photos", json={"ids": [pid]})
    assert len(list((library / "files").iterdir())) == 2

    assert client.delete(f"/api/species/library/{pid}").status_code == 204
    assert [i["id"] for i in cod_profile()["images"]] == cod + [keep]
    assert client.get("/api/species/Pollachius virens/profile").json()["images"] == []
    assert pid not in {p["id"] for p in client.get("/api/species/library").json()["photos"]}
    assert client.get(f"/api/species/library/{pid}/file").status_code == 404
    assert len(list((library / "files").iterdir())) == 1
    data = species_library.read()
    assert pid not in data["photos"] and "Pollachius virens" not in data["links"]
    assert client.delete(f"/api/species/library/{pid}").status_code == 404


def test_curated_photos_can_never_be_deleted():
    before = config.SPECIES_MEDIA.read_bytes()
    own = cod_profile()["images"][0]["id"]
    r = client.delete(f"/api/species/library/{own}")
    assert r.status_code == 403 and "Curated" in r.json()["detail"]
    assert own in [i["id"] for i in cod_profile()["images"]]
    assert config.SPECIES_MEDIA.read_bytes() == before


@pytest.mark.parametrize("role, status", [(None, 401), ("volunteer", 403)])
def test_only_managers_change_the_library(library, as_role, role, status):
    pid = upload().json()["id"]
    own = [i["id"] for i in cod_profile()["images"]]
    as_role(role)
    assert upload(data=PNG).status_code == status
    assert client.patch(f"/api/species/library/{pid}", json={"review": "verified"}).status_code == status
    assert client.put("/api/species/Gadus morhua/photos", json={"ids": own + [pid]}).status_code == status
    assert client.delete(f"/api/species/library/{pid}").status_code == status
    assert len(list((library / "files").iterdir())) == 1 and species_library.read()["links"] == {}
    assert species_library.read()["photos"][pid]["review"] == "pending"


# --- who sees which photos ---------------------------------------------------------------------

def test_guests_see_verified_photos_only_everywhere(as_role):
    pending = upload().json()["id"]
    verified = upload(data=PNG).json()["id"]
    client.patch(f"/api/species/library/{verified}", json={"review": "verified"})
    own = [i["id"] for i in cod_profile()["images"]]
    client.put("/api/species/Gadus morhua/photos", json={"ids": own + [pending, verified]})

    as_role(None)
    shown = [i["id"] for i in cod_profile()["images"]]
    assert verified in shown and pending not in shown and set(own) <= set(shown)
    listed = {p["id"] for p in client.get("/api/species/library").json()["photos"]}
    assert verified in listed and pending not in listed
    assert client.get(f"/api/species/library/{pending}/file").status_code == 404  # the address is no use to a guest
    assert client.get(f"/api/species/library/{verified}/file").status_code == 200
    assert client.get("/api/species/media").json()["Gadus morhua"]["image_count"] == len(own) + 1

    as_role("volunteer")
    images = {i["id"]: i for i in cod_profile()["images"]}
    assert images[pending]["review"] == "pending"  # shown to researchers, and labelled
    assert client.get(f"/api/species/library/{pending}/file").status_code == 200


def test_rejected_photos_are_for_managers_only(as_role):
    pid = upload().json()["id"]
    client.patch(f"/api/species/library/{pid}", json={"review": "rejected"})
    assert pid in {p["id"] for p in client.get("/api/species/library").json()["photos"]}
    for role in (None, "volunteer"):
        as_role(role)
        assert pid not in {p["id"] for p in client.get("/api/species/library").json()["photos"]}
        assert client.get(f"/api/species/library/{pid}/file").status_code == 404
