"""Simple JSON-file profile storage keyed by street address."""
import json
import uuid
from pathlib import Path
from datetime import datetime, timezone

PROFILES_DIR = Path(__file__).parent / "profiles"
PROFILES_DIR.mkdir(exist_ok=True)

INDEX_FILE = PROFILES_DIR / "index.json"


def _load_index() -> dict:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text())
    return {}


def _save_index(index: dict) -> None:
    INDEX_FILE.write_text(json.dumps(index, indent=2))


def list_profiles() -> list[dict]:
    index = _load_index()
    return sorted(
        [{"id": k, "address": v["address"], "updated_at": v["updated_at"]} for k, v in index.items()],
        key=lambda x: x["updated_at"],
        reverse=True,
    )


def save_profile(address: str, data: dict) -> dict:
    index = _load_index()
    # Check if address already exists (update in place)
    existing_id = None
    for pid, meta in index.items():
        if meta["address"].lower() == address.lower():
            existing_id = pid
            break

    profile_id = existing_id or str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()
    index[profile_id] = {"address": address, "updated_at": now}
    _save_index(index)

    # Save data file
    data_file = PROFILES_DIR / f"{profile_id}.json"
    data_file.write_text(json.dumps(data, indent=2))

    return {"id": profile_id, "address": address, "updated_at": now}


def load_profile(profile_id: str) -> dict | None:
    index = _load_index()
    if profile_id not in index:
        return None
    data_file = PROFILES_DIR / f"{profile_id}.json"
    if not data_file.exists():
        return None
    data = json.loads(data_file.read_text())
    return {"address": index[profile_id]["address"], "data": data}


def delete_profile(profile_id: str) -> bool:
    index = _load_index()
    if profile_id not in index:
        return False
    del index[profile_id]
    _save_index(index)
    data_file = PROFILES_DIR / f"{profile_id}.json"
    if data_file.exists():
        data_file.unlink()
    return True
