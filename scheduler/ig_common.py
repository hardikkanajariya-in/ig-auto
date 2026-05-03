import json
import os
import time
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import cloudinary
import cloudinary.uploader
import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
DATA_JSON = BASE_DIR / "data.json"
LOG_DIR = BASE_DIR / "logs"
PUBLISHED_DIR = BASE_DIR / "published"
FAILED_DIR = BASE_DIR / "failed"

TIMEZONE_NAME = "Asia/Kolkata"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)

GRAPH_VERSION = "v25.0"
GRAPH_BASE_URL = f"https://graph.instagram.com/{GRAPH_VERSION}"

CONTAINER_STATUS_MAX_WAIT_SECONDS = 300
CONTAINER_STATUS_POLL_SECONDS = 10

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
VIDEO_EXTENSIONS = {".mp4", ".mov"}

DELETE_CLOUDINARY_AFTER_PUBLISH = True


load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")

IG_USER_ID = os.getenv("IG_USER_ID", "").strip()
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN", "").strip()

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "").strip()
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "").strip()


cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True,
)


def ensure_dirs() -> None:
    for folder in [INPUT_DIR, LOG_DIR, PUBLISHED_DIR, FAILED_DIR]:
        folder.mkdir(parents=True, exist_ok=True)


def now_local_naive() -> datetime:
    return datetime.now(TIMEZONE)


def local_timestamp_string() -> str:
    return now_local_naive().strftime("%Y-%m-%d %H:%M:%S")


def parse_publish_at(value: str) -> datetime:
    parsed = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")
    return parsed.replace(tzinfo=TIMEZONE)


def log(message: str, log_filename: str = "ig_auto_scheduler.log") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = local_timestamp_string()
    line = f"[{timestamp}] {message}"
    print(line)

    log_file = LOG_DIR / log_filename
    with log_file.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


def load_posts() -> List[Dict[str, Any]]:
    if not DATA_JSON.exists():
        raise FileNotFoundError(f"Missing data.json at: {DATA_JSON}")

    try:
        with DATA_JSON.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except JSONDecodeError as exc:
        raise ValueError(f"data.json must be a valid JSON array: {DATA_JSON}") from exc

    if not isinstance(data, list):
        raise ValueError(f"data.json must be a valid JSON array: {DATA_JSON}")

    return data


def save_posts(posts: List[Dict[str, Any]]) -> None:
    temp_file = DATA_JSON.with_suffix(".tmp.json")

    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(posts, file, indent=2, ensure_ascii=False)

    temp_file.replace(DATA_JSON)


def update_post_status(
    post: Dict[str, Any],
    status: str,
    message: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    post["status"] = status
    post["updated_at"] = local_timestamp_string()

    if message is not None:
        post["message"] = message

    if extra:
        post.update(extra)


def validate_env(require_instagram: bool = True, require_cloudinary: bool = True) -> None:
    missing = []

    if require_instagram:
        if not IG_USER_ID:
            missing.append("IG_USER_ID")
        if not IG_ACCESS_TOKEN:
            missing.append("IG_ACCESS_TOKEN")

    if require_cloudinary:
        if not CLOUDINARY_CLOUD_NAME:
            missing.append("CLOUDINARY_CLOUD_NAME")
        if not CLOUDINARY_API_KEY:
            missing.append("CLOUDINARY_API_KEY")
        if not CLOUDINARY_API_SECRET:
            missing.append("CLOUDINARY_API_SECRET")

    if missing:
        raise RuntimeError("Missing environment values: " + ", ".join(missing))


def get_file_path(post: Dict[str, Any]) -> Path:
    filename = str(post.get("file", "")).strip()

    if not filename:
        raise ValueError("Post is missing 'file' field.")

    file_path = INPUT_DIR / filename

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    return file_path


def detect_media_type(file_path: Path, explicit_type: Optional[str]) -> str:
    if explicit_type:
        normalized = explicit_type.strip().lower()
        if normalized in {"image", "reel", "video"}:
            return normalized
        raise ValueError(f"Unsupported type: {explicit_type}")

    suffix = file_path.suffix.lower()

    if suffix in IMAGE_EXTENSIONS:
        return "image"

    if suffix in VIDEO_EXTENSIONS:
        return "reel"

    raise ValueError(f"Unsupported file extension: {suffix}")


def upload_to_cloudinary(file_path: Path, media_type: str, log_filename: str = "ig_auto_scheduler.log") -> Dict[str, str]:
    resource_type = "video" if media_type in {"reel", "video"} else "image"

    log(f"Uploading to Cloudinary: {file_path.name}", log_filename)

    result = cloudinary.uploader.upload(
        str(file_path),
        resource_type=resource_type,
        folder="ig-auto",
        overwrite=False,
    )

    secure_url = result.get("secure_url")
    public_id = result.get("public_id")

    if not secure_url or not public_id:
        raise RuntimeError(f"Cloudinary upload failed. Response: {result}")

    log(f"Cloudinary URL stored for: {file_path.name}", log_filename)
    log(f"Cloudinary public_id stored for: {file_path.name}", log_filename)

    return {
        "secure_url": secure_url,
        "public_id": public_id,
        "resource_type": resource_type,
    }


def delete_from_cloudinary(
    public_id: str,
    resource_type: str,
    log_filename: str = "ig_auto_scheduler.log",
) -> None:
    if not DELETE_CLOUDINARY_AFTER_PUBLISH:
        return

    if not public_id:
        return

    log(f"Deleting from Cloudinary: {public_id}", log_filename)

    result = cloudinary.uploader.destroy(
        public_id,
        resource_type=resource_type,
        invalidate=True,
    )

    log(f"Cloudinary delete response: {result}", log_filename)


def graph_post(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{GRAPH_BASE_URL}/{endpoint.lstrip('/')}"
    body = dict(payload)
    body["access_token"] = IG_ACCESS_TOKEN

    response = requests.post(url, data=body, timeout=120)

    try:
        data = response.json()
    except Exception:
        raise RuntimeError(f"Non-JSON response from Instagram: {response.text}")

    if response.status_code >= 400 or "error" in data:
        raise RuntimeError(f"Instagram API error: {json.dumps(data, indent=2)}")

    return data


def graph_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{GRAPH_BASE_URL}/{endpoint.lstrip('/')}"
    query = dict(params or {})
    query["access_token"] = IG_ACCESS_TOKEN

    response = requests.get(url, params=query, timeout=60)

    try:
        data = response.json()
    except Exception:
        raise RuntimeError(f"Non-JSON response from Instagram: {response.text}")

    if response.status_code >= 400 or "error" in data:
        raise RuntimeError(f"Instagram API error: {json.dumps(data, indent=2)}")

    return data


def create_media_container(
    media_type: str,
    public_url: str,
    caption: str,
    log_filename: str = "ig_auto_scheduler.log",
) -> str:
    log(f"Creating Instagram media container for type: {media_type}", log_filename)

    if media_type == "image":
        payload = {
            "image_url": public_url,
            "caption": caption,
        }
    elif media_type in {"reel", "video"}:
        payload = {
            "media_type": "REELS",
            "video_url": public_url,
            "caption": caption,
        }
    else:
        raise ValueError(f"Unsupported media type: {media_type}")

    data = graph_post(f"{IG_USER_ID}/media", payload)
    creation_id = data.get("id")

    if not creation_id:
        raise RuntimeError(f"No creation_id returned: {data}")

    log(f"Created container: {creation_id}", log_filename)
    return creation_id


def wait_for_container_ready(
    creation_id: str,
    media_type: str,
    log_filename: str = "ig_auto_scheduler.log",
) -> None:
    if media_type == "image":
        return

    log("Waiting for Instagram video/reel processing...", log_filename)
    started = time.time()

    while True:
        data = graph_get(
            creation_id,
            {
                "fields": "status_code,status",
            },
        )

        status_code = str(data.get("status_code", "")).upper()
        status = str(data.get("status", ""))

        log(f"Container status: {status_code or status}", log_filename)

        if status_code in {"FINISHED", "PUBLISHED"}:
            return

        if status_code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Container processing failed: {data}")

        if time.time() - started > CONTAINER_STATUS_MAX_WAIT_SECONDS:
            raise TimeoutError(f"Container was not ready in time: {data}")

        time.sleep(CONTAINER_STATUS_POLL_SECONDS)


def publish_media_container(creation_id: str, log_filename: str = "ig_auto_scheduler.log") -> str:
    log(f"Publishing Instagram container: {creation_id}", log_filename)

    data = graph_post(
        f"{IG_USER_ID}/media_publish",
        {
            "creation_id": creation_id,
        },
    )

    published_id = data.get("id")

    if not published_id:
        raise RuntimeError(f"No published media id returned: {data}")

    log(f"Published media ID: {published_id}", log_filename)
    return published_id
