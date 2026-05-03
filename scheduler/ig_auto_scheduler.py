import json
import os
import time
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from json import JSONDecodeError


# ============================================================
# CONFIG — CHANGE ONLY THESE VALUES / FILES, NO CLI ARGUMENTS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

INPUT_DIR = BASE_DIR / "input"
PROCESSED_DIR = BASE_DIR / "processed"
PUBLISHED_DIR = BASE_DIR / "published"
FAILED_DIR = BASE_DIR / "failed"
LOG_DIR = BASE_DIR / "logs"
DATA_JSON = BASE_DIR / "data.json"

TIMEZONE_LABEL = "Asia/Kolkata"

# Run mode:
# True  = script keeps checking data.json continuously
# False = script checks once and exits
RUN_CONTINUOUSLY = False

# Used only when RUN_CONTINUOUSLY = True
CHECK_INTERVAL_SECONDS = 60

# Instagram Graph version
GRAPH_VERSION = "v25.0"
GRAPH_BASE_URL = f"https://graph.instagram.com/{GRAPH_VERSION}"

# For videos/reels, Instagram may need time to process the container
CONTAINER_STATUS_MAX_WAIT_SECONDS = 300
CONTAINER_STATUS_POLL_SECONDS = 10

# Supported files
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
VIDEO_EXTENSIONS = {".mp4", ".mov"}

# Optional: move files after success/failure
MOVE_SUCCESS_FILES = True
MOVE_FAILED_FILES = False

DELETE_CLOUDINARY_AFTER_PUBLISH = True


# ============================================================
# ENV
# ============================================================

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


# ============================================================
# HELPERS
# ============================================================

def ensure_dirs() -> None:
    for folder in [INPUT_DIR, PROCESSED_DIR, PUBLISHED_DIR, FAILED_DIR, LOG_DIR]:
        folder.mkdir(parents=True, exist_ok=True)


def now_local_naive() -> datetime:
    # Your machine is expected to be set to India time.
    # For your current local workflow, this keeps things simple.
    return datetime.now()


def parse_publish_at(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)

    log_file = LOG_DIR / "ig_auto_scheduler.log"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_posts() -> List[Dict[str, Any]]:
    if not DATA_JSON.exists():
        raise FileNotFoundError(f"Missing data.json at: {DATA_JSON}")

    try:
        with DATA_JSON.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except JSONDecodeError as exc:
        raise ValueError(f"data.json must be a valid JSON array: {DATA_JSON}") from exc

    if not isinstance(data, list):
        raise ValueError(f"data.json must be a valid JSON array: {DATA_JSON}")

    return data


def save_posts(posts: List[Dict[str, Any]]) -> None:
    temp_file = DATA_JSON.with_suffix(".tmp.json")

    with temp_file.open("w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)

    temp_file.replace(DATA_JSON)


def update_post_status(
    post: Dict[str, Any],
    status: str,
    message: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    post["status"] = status
    post["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if message:
        post["message"] = message

    if extra:
        post.update(extra)


def validate_env() -> None:
    missing = []

    if not IG_USER_ID:
        missing.append("IG_USER_ID")
    if not IG_ACCESS_TOKEN:
        missing.append("IG_ACCESS_TOKEN")
    if not CLOUDINARY_CLOUD_NAME:
        missing.append("CLOUDINARY_CLOUD_NAME")
    if not CLOUDINARY_API_KEY:
        missing.append("CLOUDINARY_API_KEY")
    if not CLOUDINARY_API_SECRET:
        missing.append("CLOUDINARY_API_SECRET")

    if missing:
        raise RuntimeError("Missing .env values: " + ", ".join(missing))


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


def is_due(post: Dict[str, Any]) -> bool:
    status = str(post.get("status", "pending")).lower()

    if status not in {"pending", "failed_retry"}:
        return False

    publish_at_raw = str(post.get("publish_at", "")).strip()

    if not publish_at_raw:
        raise ValueError("Post is missing 'publish_at' field.")

    publish_time = parse_publish_at(publish_at_raw)
    return publish_time <= now_local_naive()

def delete_from_cloudinary(public_id: str, resource_type: str) -> None:
    if not DELETE_CLOUDINARY_AFTER_PUBLISH:
        return

    if not public_id:
        return

    log(f"Deleting from Cloudinary: {public_id}")

    result = cloudinary.uploader.destroy(
        public_id,
        resource_type=resource_type,
        invalidate=True,
    )

    log(f"Cloudinary delete response: {result}")

def upload_to_cloudinary(file_path: Path, media_type: str) -> Dict[str, str]:
    resource_type = "video" if media_type in {"reel", "video"} else "image"

    log(f"Uploading to Cloudinary: {file_path.name}")

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

    log(f"Cloudinary URL: {secure_url}")
    log(f"Cloudinary public_id: {public_id}")

    return {
        "secure_url": secure_url,
        "public_id": public_id,
        "resource_type": resource_type,
    }

def graph_post(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{GRAPH_BASE_URL}/{endpoint.lstrip('/')}"
    payload = dict(payload)
    payload["access_token"] = IG_ACCESS_TOKEN

    response = requests.post(url, data=payload, timeout=120)

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


def create_media_container(media_type: str, public_url: str, caption: str) -> str:
    log(f"Creating Instagram media container for type: {media_type}")

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

    log(f"Created container: {creation_id}")
    return creation_id


def wait_for_container_ready(creation_id: str, media_type: str) -> None:
    if media_type == "image":
        return

    log("Waiting for Instagram video/reel processing...")

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

        log(f"Container status: {status_code or status}")

        if status_code in {"FINISHED", "PUBLISHED"}:
            return

        if status_code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Container processing failed: {data}")

        if time.time() - started > CONTAINER_STATUS_MAX_WAIT_SECONDS:
            raise TimeoutError(f"Container was not ready in time: {data}")

        time.sleep(CONTAINER_STATUS_POLL_SECONDS)


def publish_media_container(creation_id: str) -> str:
    log(f"Publishing Instagram container: {creation_id}")

    data = graph_post(
        f"{IG_USER_ID}/media_publish",
        {
            "creation_id": creation_id,
        },
    )

    published_id = data.get("id")

    if not published_id:
        raise RuntimeError(f"No published media id returned: {data}")

    log(f"Published media ID: {published_id}")
    return published_id


def move_file_after_result(file_path: Path, status: str) -> None:
    if status == "published" and MOVE_SUCCESS_FILES:
        destination = PUBLISHED_DIR / file_path.name
    elif status == "failed" and MOVE_FAILED_FILES:
        destination = FAILED_DIR / file_path.name
    else:
        return

    if destination.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = destination.with_name(f"{destination.stem}_{timestamp}{destination.suffix}")

    shutil.move(str(file_path), str(destination))
    log(f"Moved file to: {destination}")


def process_one_post(post: Dict[str, Any]) -> None:
    file_path = get_file_path(post)
    media_type = detect_media_type(file_path, post.get("type"))
    caption = str(post.get("caption", "")).strip()

    if not caption:
        raise ValueError(f"Caption missing for file: {file_path.name}")

    uploaded = upload_to_cloudinary(file_path, media_type)

    public_url = uploaded["secure_url"]
    cloudinary_public_id = uploaded["public_id"]
    cloudinary_resource_type = uploaded["resource_type"]

    creation_id = create_media_container(media_type, public_url, caption)
    wait_for_container_ready(creation_id, media_type)
    published_media_id = publish_media_container(creation_id)

    delete_from_cloudinary(cloudinary_public_id, cloudinary_resource_type)

    update_post_status(
        post,
        "published",
        "Published successfully.",
        {
            "media_type": media_type,
            "cloudinary_url": public_url,
            "cloudinary_public_id": cloudinary_public_id,
            "cloudinary_resource_type": cloudinary_resource_type,
            "cloudinary_deleted": DELETE_CLOUDINARY_AFTER_PUBLISH,
            "creation_id": creation_id,
            "published_media_id": published_media_id,
            "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )

    move_file_after_result(file_path, "published")
def run_once() -> None:
    ensure_dirs()
    validate_env()

    posts = load_posts()
    changed = False

    for index, post in enumerate(posts):
        file_name = post.get("file", f"index-{index}")

        try:
            if not is_due(post):
                continue

            log(f"Processing due post: {file_name}")
            update_post_status(post, "processing", "Processing started.")
            save_posts(posts)

            process_one_post(post)

            changed = True
            save_posts(posts)

        except Exception as e:
            error_message = str(e)
            log(f"FAILED: {file_name} | {error_message}")

            update_post_status(
                post,
                "failed",
                error_message,
                {
                    "failed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
            )

            try:
                file_path = get_file_path(post)
                move_file_after_result(file_path, "failed")
            except Exception:
                pass

            changed = True
            save_posts(posts)

    if not changed:
        log("No due pending posts found.")


def main() -> None:
    ensure_dirs()
    log("IG auto scheduler started.")

    if RUN_CONTINUOUSLY:
        while True:
            run_once()
            log(f"Sleeping for {CHECK_INTERVAL_SECONDS} seconds...")
            time.sleep(CHECK_INTERVAL_SECONDS)
    else:
        run_once()

    log("IG auto scheduler finished.")

if __name__ == "__main__":
    main()
