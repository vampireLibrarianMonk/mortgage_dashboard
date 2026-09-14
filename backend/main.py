from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from models import CalculateRequest, CalculateResponse
from calculations import calculate
import profiles_store

app = FastAPI(title="Mortgage Dashboard API")

# CORS is only needed for local dev, where the Vite dev server (5173) calls the
# API on a different origin. In production the app is same-origin (FastAPI serves
# the built frontend), so these origins are harmless but unused.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/calculate", response_model=CalculateResponse)
def calculate_endpoint(req: CalculateRequest):
    return calculate(req)


# --- Profile management ---

class SaveProfileRequest(BaseModel):
    address: str
    data: dict


@app.get("/profiles")
def list_profiles_endpoint():
    return profiles_store.list_profiles()


@app.post("/profiles")
def save_profile_endpoint(req: SaveProfileRequest):
    return profiles_store.save_profile(req.address, req.data)


@app.get("/profiles/{profile_id}")
def load_profile_endpoint(profile_id: str):
    result = profiles_store.load_profile(profile_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return result


@app.delete("/profiles/{profile_id}")
def delete_profile_endpoint(profile_id: str):
    if not profiles_store.delete_profile(profile_id):
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"ok": True}


@app.get("/healthz")
def healthz():
    """Liveness probe used by the reverse proxy / startup checks."""
    return {"status": "ok"}


# --- Static frontend (production) ---
# When the frontend has been built (`npm run build`), FastAPI serves the compiled
# SPA from frontend/dist so the whole app runs on a single port behind the proxy.
# In dev this directory won't exist and the Vite dev server handles the UI instead.
_DIST_DIR = (Path(__file__).resolve().parent.parent / "frontend" / "dist")

if _DIST_DIR.is_dir():
    _ASSETS_DIR = _DIST_DIR / "assets"
    if _ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="assets")

    @app.get("/")
    def _serve_index():
        return FileResponse(_DIST_DIR / "index.html")

    @app.get("/{full_path:path}")
    def _serve_spa(full_path: str):
        """Serve real static files if present, else fall back to index.html (SPA routing)."""
        candidate = _DIST_DIR / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST_DIR / "index.html")
