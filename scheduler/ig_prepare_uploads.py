from typing import Any, Dict

from ig_common import (
    ensure_dirs,
    get_file_path,
    load_posts,
    local_timestamp_string,
    log,
    save_posts,
    update_post_status,
    upload_to_cloudinary,
    validate_env,
    detect_media_type,
)


LOG_FILENAME = "ig_prepare_uploads.log"


def caption_for_post(post: Dict[str, Any], file_name: str) -> str:
    caption = post.get("caption", "")
    if not isinstance(caption, str) or caption == "":
        raise ValueError(f"Caption missing for file: {file_name}")
    return caption


def main() -> None:
    ensure_dirs()
    validate_env(require_instagram=False, require_cloudinary=True)
    log("IG prepare uploads started.", LOG_FILENAME)

    posts = load_posts()
    uploaded_count = 0
    skipped_count = 0
    failed_count = 0

    for index, post in enumerate(posts):
        file_name = str(post.get("file", f"index-{index}"))
        status = str(post.get("status", "pending")).lower()
        cloudinary_url = str(post.get("cloudinary_url", "")).strip()

        try:
            if status == "published":
                log(f"Skipping published post: {file_name}", LOG_FILENAME)
                skipped_count += 1
                continue

            if status == "uploaded":
                log(f"Already uploaded, skipping: {file_name}", LOG_FILENAME)
                skipped_count += 1
                continue

            if status == "pending" and cloudinary_url:
                update_post_status(
                    post,
                    "uploaded",
                    "Cloudinary URL already exists, marked as uploaded.",
                )
                save_posts(posts)
                log(f"Pending post already had Cloudinary data, marked uploaded: {file_name}", LOG_FILENAME)
                skipped_count += 1
                continue

            if status == "failed_retry" and cloudinary_url:
                log(f"Retry post already has Cloudinary URL, skipping upload: {file_name}", LOG_FILENAME)
                skipped_count += 1
                continue

            if status != "pending" and not (status == "failed_retry" and not cloudinary_url):
                log(f"Skipping status {status}: {file_name}", LOG_FILENAME)
                skipped_count += 1
                continue

            caption_for_post(post, file_name)
            file_path = get_file_path(post)
            media_type = detect_media_type(file_path, post.get("type"))
            uploaded = upload_to_cloudinary(file_path, media_type, LOG_FILENAME)

            update_post_status(
                post,
                "uploaded",
                "Uploaded to Cloudinary and waiting for publish time.",
                {
                    "media_type": media_type,
                    "cloudinary_url": uploaded["secure_url"],
                    "cloudinary_public_id": uploaded["public_id"],
                    "cloudinary_resource_type": uploaded["resource_type"],
                    "uploaded_at": local_timestamp_string(),
                },
            )
            save_posts(posts)
            uploaded_count += 1
            log(f"Prepared post for later publishing: {file_name}", LOG_FILENAME)

        except Exception as exc:
            failed_count += 1
            error_message = str(exc)
            log(f"FAILED TO PREPARE: {file_name} | {error_message}", LOG_FILENAME)

            update_post_status(
                post,
                "failed",
                error_message,
                {
                    "failed_at": local_timestamp_string(),
                },
            )
            save_posts(posts)

    log(
        f"IG prepare uploads finished. uploaded={uploaded_count} skipped={skipped_count} failed={failed_count}",
        LOG_FILENAME,
    )


if __name__ == "__main__":
    main()
