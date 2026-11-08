"""The Media Library: upload reference photos once, then choose which species show them.

Uploads start pending review. Unlinking a photo from a species never deletes it, and the curated
Wikimedia Commons and iNaturalist photos are never changed: only where they are shown.

Browsing is public: guests see verified photos, signed-in people pending ones too, managers also
rejected ones (species_library.visible). Every change is for managers; permanent deletion also needs
a recent password confirmation.
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import auth, models, species_library, species_media

router = APIRouter()


def _invalid(e: species_library.Invalid):
    return HTTPException(400, str(e))


@router.get("/api/species/library")
def library(user: auth.User | None = Depends(auth.viewer)):
    """Every photo in the library this viewer may see, uploaded or curated, with the species each is shown on."""
    photos = species_library.catalogue(species_media.curated_images(), auth.level(user))
    return {"photos": photos, "views": list(species_library.VIEWS), "review": list(species_library.REVIEW)}


@router.post("/api/species/library", status_code=201, dependencies=auth.MANAGER)
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


@router.patch("/api/species/library/{photo_id}", dependencies=auth.MANAGER)
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
def photo_file(photo_id: str, user: auth.User | None = Depends(auth.viewer)):
    """The image itself, only for viewers who may see it: a pending photo's address is no use to a guest."""
    found = species_library.file_of(photo_id, auth.level(user))
    if not found:
        raise HTTPException(404, "No such photo")
    path, media_type = found
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@router.delete("/api/species/library/{photo_id}", status_code=204, dependencies=auth.RECENT_MANAGER)
def delete_photo(photo_id: str):
    """Permanently delete an uploaded photo, its file and its links on every species. Curated
    Wikimedia Commons and iNaturalist photos can't be deleted. To take a photo off one species only,
    save that species' photos without it instead."""
    try:
        species_library.delete(photo_id, species_media.curated_images())
    except species_library.Protected:
        raise HTTPException(403, "Curated reference photos can't be deleted. Remove it from a species instead.")
    except KeyError:
        raise HTTPException(404, "No such uploaded photo")
    return Response(status_code=204)


class SpeciesPhotos(BaseModel):
    ids: list[str]


@router.put("/api/species/{name}/photos", dependencies=auth.MANAGER)
def save_species_photos(name: str, body: SpeciesPhotos):
    """Make these library photos the ones shown on a species, in one save. Leaving a photo out only
    unlinks it from this species: it stays in the library."""
    if name not in {row["species"] for row in models.species_table()}:
        raise HTTPException(404, "That species is not on the list")
    try:
        species_library.set_species_photos(name, body.ids, species_media.curated_images())
    except species_library.Invalid as e:
        raise _invalid(e)
    return species_media.profile(name, "manager")
