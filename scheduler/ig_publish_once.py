from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ig_common import (
    DELETE_CLOUDINARY_AFTER_PUBLISH,
    create_media_container,
    delete_from_cloudinary,
    ensure_dirs,
    load_posts,
    local_timestamp_string,
    log,
    now_local_naive,
    parse_publish_at,
    publish_media_container,
    save_posts,
    update_post_status,
    validate_env,
    wait_for_container_ready,
)


LOG_FILENAME = "ig_publish_once.log"


def caption_for_post(post: Dict[str, Any], file_name: str) -> str:
    caption = post.get("caption", "")
    if not isinstance(caption, str) or caption == "":
        raise ValueError(f"Caption missing for file: {file_name}")
    return caption


def next_scheduled_post(posts: List[Dict[str, Any]]) -> Optional[Tuple[datetime, str, str]]:
    candidates: List[Tuple[datetime, str, str]] = []

    for index, post in enumerate(posts):
        file_name = str(post.get("file", f"index-{index}"))
        publish_at_raw = str(post.get("publish_at", "")).strip()
        status = str(post.get("status", "pending")).lower()
        cloudinary_url = str(post.get("cloudinary_url", "")).strip()

        if not publish_at_raw:
            continue

        if status == "uploaded":
            candidates.append((parse_publish_at(publish_at_raw), file_name, status))
            continue

        if status == "failed_retry" and cloudinary_url:
            candidates.append((parse_publish_at(publish_at_raw), file_name, status))

    if not candidates:
        return None

    return min(candidates, key=lambda item: item[0])


def due_for_publish(post: Dict[str, Any]) -> bool:
    publish_at_raw = str(post.get("publish_at", "")).strip()
    if not publish_at_raw:
        raise ValueError("Post is missing 'publish_at' field.")
    return parse_publish_at(publish_at_raw) <= now_local_naive()


def can_publish(post: Dict[str, Any]) -> bool:
    status = str(post.get("status", "")).lower()
    cloudinary_url = str(post.get("cloudinary_url", "")).strip()

    if status == "uploaded":
        return bool(cloudinary_url)

    if status == "failed_retry":
        return bool(cloudinary_url)

    return False


def main() -> None:
    ensure_dirs()
    validate_env(
        require_instagram=True,
        require_cloudinary=DELETE_CLOUDINARY_AFTER_PUBLISH,
    )
    log("IG publish once started.", LOG_FILENAME)

    posts = load_posts()
    published_count = 0
    skipped_count = 0
    failed_count = 0

    for index, post in enumerate(posts):
        file_name = str(post.get("file", f"index-{index}"))
        status = str(post.get("status", "pending")).lower()
        cloudinary_url = str(post.get("cloudinary_url", "")).strip()

        try:
            if status == "pending":
                log(f"Pending post must be prepared locally first: {file_name}", LOG_FILENAME)
                skipped_count += 1
                continue

            if not can_publish(post):
                log(f"Skipping status {status}: {file_name}", LOG_FILENAME)
                skipped_count += 1
                continue

            if not due_for_publish(post):
                skipped_count += 1
                continue

            media_type = str(post.get("media_type", "")).strip().lower()
            if media_type not in {"image", "reel", "video"}:
                raise ValueError(f"Missing or unsupported media_type for file: {file_name}")

            caption = caption_for_post(post, file_name)
            cloudinary_public_id = str(post.get("cloudinary_public_id", "")).strip()
            cloudinary_resource_type = str(post.get("cloudinary_resource_type", "")).strip()

            update_post_status(post, "publishing", "Publishing started.")
            save_posts(posts)

            creation_id = create_media_container(media_type, cloudinary_url, caption, LOG_FILENAME)
            wait_for_container_ready(creation_id, media_type, LOG_FILENAME)
            published_media_id = publish_media_container(creation_id, LOG_FILENAME)

            cloudinary_deleted = False
            if DELETE_CLOUDINARY_AFTER_PUBLISH and cloudinary_public_id and cloudinary_resource_type:
                delete_from_cloudinary(
                    cloudinary_public_id,
                    cloudinary_resource_type,
                    LOG_FILENAME,
                )
                cloudinary_deleted = True

            update_post_status(
                post,
                "published",
                "Published successfully.",
                {
                    "creation_id": creation_id,
                    "published_media_id": published_media_id,
                    "published_at": local_timestamp_string(),
                    "cloudinary_deleted": cloudinary_deleted,
                },
            )
            save_posts(posts)
            published_count += 1
            log(f"Published due post: {file_name}", LOG_FILENAME)

        except Exception as exc:
            failed_count += 1
            error_message = str(exc)
            log(f"FAILED TO PUBLISH: {file_name} | {error_message}", LOG_FILENAME)

            update_post_status(
                post,
                "failed",
                error_message,
                {
                    "failed_at": local_timestamp_string(),
                },
            )
            save_posts(posts)

    if published_count == 0:
        next_post = next_scheduled_post(posts)
        if next_post is None:
            log("No due uploaded posts found and no upcoming uploaded posts are scheduled.", LOG_FILENAME)
        else:
            publish_at, file_name, status = next_post
            log(
                f"No due uploaded posts found. Next scheduled uploaded post: {file_name} at {publish_at.strftime('%Y-%m-%d %H:%M %Z')} with status {status}.",
                LOG_FILENAME,
            )

    log(
        f"IG publish once finished. published={published_count} skipped={skipped_count} failed={failed_count}",
        LOG_FILENAME,
    )

if __name__ == "__main__":
    main()
