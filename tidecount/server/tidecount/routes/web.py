"""Serves the built UI, so a single process runs the whole app. app.py includes this router last,
because its catch-all path would otherwise answer requests meant for the API."""
from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, Response

from .. import config

router = APIRouter()


@router.get("/{path:path}")
def web(path: str):
    # An /api path that reached here matches no endpoint. Answering with the UI's index.html would
    # hand the browser a web page where it expects JSON, and fail as "Unexpected token '<'".
    if path == "api" or path.startswith("api/"):
        return JSONResponse({"detail": f"No such API endpoint: /{path}"}, status_code=404)
    target = (config.WEB_DIST / path).resolve()
    if path and target.is_file() and config.WEB_DIST.resolve() in target.parents:
        return FileResponse(target)
    index = config.WEB_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return Response("The UI isn't built yet. Run `pnpm build` in web/.", media_type="text/plain")
