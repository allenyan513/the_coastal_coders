"""Serves the built UI, so a single process runs the whole app. app.py includes this router last,
because its catch-all path would otherwise answer requests meant for the API."""
from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from .. import config

router = APIRouter()


@router.get("/{path:path}")
def web(path: str):
    target = (config.WEB_DIST / path).resolve()
    if path and target.is_file() and config.WEB_DIST.resolve() in target.parents:
        return FileResponse(target)
    index = config.WEB_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return Response("The UI isn't built yet. Run `pnpm build` in web/.", media_type="text/plain")
