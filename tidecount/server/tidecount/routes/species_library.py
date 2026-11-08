"""The Media Library: upload reference photos once, then choose which species show them.

Uploads start pending review. Unlinking a photo from a species never deletes it, and the curated
Wikimedia Commons and iNaturalist photos are never changed: only where they are shown.
"""
import hmac

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import config, models, species_library, species_media

router = APIRouter()


def _invalid(e: species_library.Invalid):
    return HTTPException(400, str(e))


@router.get("/api/species/library")
def library():
    """Every photo in the library, uploaded or curated, with the species each is shown on."""
    return {"photos": species_library.catalogue(species_media.curated_images()), "views": list(species_library.VIEWS), "review": list(species_library.REVIEW)}


@router.post("/api/species/library", status_code=201)
def upload_photo(
    response: Response,
    file: UploadFile = File(...),
    view: str = Form("other"),
    caption: str = Form(""),
    creator: str = Form(""),
    license: str = Form(""),
    license_url: str = Form(""),
    source: str = Form(""),
    source_url: str = Form(""),
    place: str = Form(""),
):
    """Store a photo in the library, pending review and linked to no species yet."""
    fields = dict(view=view, caption=caption, creator=creator, license=license, license_url=license_url, source=source, source_url=source_url, place=place)
    try:
        photo, new = species_library.add_upload(file.file, fields)
    except species_library.Invalid as e:
        raise _invalid(e)
    if not new:
        response.status_code = 200  # already in the library: the stored photo, not a second copy
    return {**species_library.as_image(photo), "added_on": photo.get("added_on", ""), "duplicate": not new}


class PhotoPatch(BaseModel):
    view: str | None = None
    caption: str | None = None
    creator: str | None = None
    license: str | None = None
    license_url: str | None = None
    source: str | None = None
    source_url: str | None = None
    place: str | None = None
    review: str | None = None


@router.patch("/api/species/library/{photo_id}")
def edit_photo(photo_id: str, patch: PhotoPatch):
    """Change an uploaded photo's credit, type or review status. Curated photos are edited in their manifest."""
    try:
        photo = species_library.update(photo_id, patch.model_dump(exclude_none=True))
    except KeyError:
        raise HTTPException(404, "Only uploaded photos can be edited here")
    except species_library.Invalid as e:
        raise _invalid(e)
    return {**species_library.as_image(photo), "added_on": photo.get("added_on", "")}


@router.get("/api/species/library/{photo_id}/file")
def photo_file(photo_id: str):
    found = species_library.file_of(photo_id)
    if not found:
        raise HTTPException(404, "No such photo")
    path, media_type = found
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


LOOPBACK = {"127.0.0.1", "::1", "localhost"}
FORWARDING = ("x-forwarded-for", "x-real-ip", "forwarded")


def may_delete(request: Request) -> bool:
    """Tideflow has no server accounts (sign-in is simulated in the browser), so the browser's role
    can't be trusted. Deleting is allowed with the deletion key, or for a request made directly on
    the computer running Tideflow. A proxied request (Caddy on a server) is never taken as local."""
    key = config.MEDIA_ADMIN_TOKEN
    given = request.headers.get("x-tideflow-admin-token", "")
    if key and given and hmac.compare_digest(given.encode(), key.encode()):
        return True
    host = request.client.host if request.client else ""
    return host in LOOPBACK and not any(h in request.headers for h in FORWARDING)


@router.delete("/api/species/library/{photo_id}", status_code=204)
def delete_photo(photo_id: str, request: Request):
    """Permanently delete an uploaded photo, its file and its links on every species. Curated
    Wikimedia Commons and iNaturalist photos can't be deleted. To take a photo off one species only,
    save that species' photos without it instead."""
    if not may_delete(request):
        wrong = bool(request.headers.get("x-tideflow-admin-token"))
        raise HTTPException(403, "That deletion key isn't right." if wrong else
                            "Deleting photos needs the deletion key here. On the computer running Tideflow it works without one.")
    try:
        species_library.delete(photo_id, species_media.curated_images())
    except species_library.Protected:
        raise HTTPException(403, "Curated reference photos can't be deleted. Remove it from a species instead.")
    except KeyError:
        raise HTTPException(404, "No such uploaded photo")
    return Response(status_code=204)


class SpeciesPhotos(BaseModel):
    ids: list[str]


@router.put("/api/species/{name}/photos")
def save_species_photos(name: str, body: SpeciesPhotos):
    """Make these library photos the ones shown on a species, in one save. Leaving a photo out only
    unlinks it from this species: it stays in the library."""
    if name not in {row["species"] for row in models.species_table()}:
        raise HTTPException(404, "That species is not on the list")
    try:
        species_library.set_species_photos(name, body.ids, species_media.curated_images())
    except species_library.Invalid as e:
        raise _invalid(e)
    return species_media.profile(name)
