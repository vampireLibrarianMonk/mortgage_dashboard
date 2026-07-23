from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from models import CalculateRequest, CalculateResponse
from calculations import calculate
import profiles_store

app = FastAPI(title="Mortgage Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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
