import json
import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from dotenv import load_dotenv

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None


# ============================================================
# CONFIG — CHANGE ONLY THESE VALUES WHEN NEEDED
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
PROCESSED_DIR = BASE_DIR / "processed"
FAILED_DIR = BASE_DIR / "failed"
LOG_DIR = BASE_DIR / "logs"
LOGO_PATH = BASE_DIR / "assets" / "logo.png"

BRAND_NAME = "GharSet"
WEBSITE_URL = ""
WHATSAPP_NUMBER = ""
TARGET_AUDIENCE = "Indian online shoppers"
PRODUCT_CATEGORY = "home product"

TRIM_END_SECONDS = 3.0
MUTE_WORDS = ["meesho", "misho", "meeshoo", "mesho"]
WHISPER_MODEL = "small"

# Based on your screenshot: source logo is top-right.
# Tune these constants only if the logo patch is not perfect.
WATERMARK_RIGHT = 28
WATERMARK_TOP = 55
WATERMARK_WIDTH = 190
WATERMARK_HEIGHT = 150
MY_LOGO_WIDTH = 105

ANALYSIS_FRAME_COUNT = 6
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}

OUTPUT_CRF = "20"
OUTPUT_PRESET = "medium"
OUTPUT_AUDIO_BITRATE = "160k"


STOPWORDS = {
    "the", "is", "are", "a", "an", "and", "or", "for", "to", "of", "in", "on",
    "with", "this", "that", "it", "you", "your", "my", "our", "at", "by", "from",
    "as", "be", "was", "were", "will", "can", "just", "now", "new", "best", "very",
    "use", "using", "product", "video", "shorts", "short", "like", "subscribe", "follow",
    "meesho", "misho", "meeshoo", "mesho",
}


load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")


# ============================================================
# CORE HELPERS
# ============================================================

def run_command(command):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr)

    return result.stdout


def check_ffmpeg():
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg not found in PATH.")

    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe not found in PATH.")


def get_video_duration(video_path):
    command = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(video_path),
    ]
    output = run_command(command)
    data = json.loads(output)
    return float(data["format"]["duration"])


def has_audio_stream(video_path):
    command = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "json",
        str(video_path),
    ]
    output = run_command(command)
    data = json.loads(output)
    return bool(data.get("streams"))


def clean_word(word):
    return re.sub(r"[^a-zA-Z0-9]", "", word).lower()


def merge_ranges(ranges, gap=0.08):
    if not ranges:
        return []

    ranges = sorted(ranges)
    merged = [ranges[0]]

    for start, end in ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + gap:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return merged


# ============================================================
# AUDIO TRANSCRIPTION + WORD MUTING
# ============================================================

def transcribe_and_find_mute_ranges(video_path, mute_words, model_size="small", padding=0.18):
    if WhisperModel is None:
        print("faster-whisper is not installed. Skipping transcript and mute detection.")
        return "", []

    mute_words_set = {clean_word(word) for word in mute_words if clean_word(word)}

    model = WhisperModel(
        model_size,
        device="cpu",
        compute_type="int8",
    )

    segments, _ = model.transcribe(
        str(video_path),
        word_timestamps=True,
        vad_filter=True,
    )

    transcript_parts = []
    mute_ranges = []

    for segment in segments:
        text = segment.text.strip()
        if text:
            transcript_parts.append(text)

        if not segment.words:
            continue

        for item in segment.words:
            spoken_word = clean_word(item.word)
            if spoken_word in mute_words_set:
                start = max(0, item.start - padding)
                end = item.end + padding
                mute_ranges.append((start, end))

    transcript = " ".join(transcript_parts).strip()
    return transcript, merge_ranges(mute_ranges)


def build_audio_filter(mute_ranges):
    if not mute_ranges:
        return "[0:a]anull[a]"

    filter_parts = []
    current_label = "0:a"

    for index, (start, end) in enumerate(mute_ranges):
        next_label = f"a{index}"
        filter_parts.append(
            f"[{current_label}]volume=enable='between(t,{start:.3f},{end:.3f})':volume=0[{next_label}]"
        )
        current_label = next_label

    filter_parts.append(f"[{current_label}]anull[a]")
    return ";".join(filter_parts)


# ============================================================
# FRAME EXTRACTION FOR MANUAL REVIEW
# ============================================================

def extract_keyframes(video_path, frames_dir, frame_count=6):
    frames_dir.mkdir(parents=True, exist_ok=True)

    for old_file in frames_dir.glob("*.jpg"):
        old_file.unlink()

    duration = get_video_duration(video_path)
    safe_duration = max(1.0, duration - TRIM_END_SECONDS)

    timestamps = []
    if frame_count <= 1:
        timestamps = [min(1.0, safe_duration)]
    else:
        for index in range(frame_count):
            position = 0.12 + (0.76 * index / max(1, frame_count - 1))
            timestamps.append(max(0.2, min(safe_duration, safe_duration * position)))

    frame_paths = []

    for index, timestamp in enumerate(timestamps, start=1):
        frame_path = frames_dir / f"frame_{index:02d}.jpg"
        command = [
            "ffmpeg",
            "-y",
            "-ss", f"{timestamp:.2f}",
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(frame_path),
        ]
        run_command(command)
        if frame_path.exists():
            frame_paths.append(frame_path)

    return frame_paths


# ============================================================
# FREE OPTION 3 SEO GENERATION
# ============================================================

def extract_keywords_from_text(text, max_keywords=22):
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    words = [word for word in words if len(word) >= 3 and word not in STOPWORDS]
    counter = Counter(words)
    return [word for word, _ in counter.most_common(max_keywords)]


def clean_title_part(text):
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.title()


def guess_product_phrase(transcript, product_category):
    keywords = extract_keywords_from_text(transcript)

    priority_words = []
    useful_terms = [
        "corner", "corners", "loading", "storage", "organizer", "kitchen", "rack", "holder",
        "cleaning", "brush", "bottle", "bag", "cover", "tray", "mat", "box", "stand",
        "lamp", "light", "fan", "charger", "cable", "container", "basket", "shelf",
        "bathroom", "bedroom", "home", "cute", "compact", "portable", "foldable",
    ]

    for word in keywords:
        if word in useful_terms:
            priority_words.append(word)

    if priority_words:
        phrase = " ".join(priority_words[:3])
    elif keywords:
        phrase = " ".join(keywords[:3])
    else:
        phrase = product_category

    return clean_title_part(phrase), keywords


def build_option3_seo(transcript):
    product_phrase, keywords = guess_product_phrase(transcript, PRODUCT_CATEGORY)

    if not product_phrase:
        product_phrase = clean_title_part(PRODUCT_CATEGORY)

    title_options = [
        f"{product_phrase} for Daily Home Use #Shorts",
        f"Useful {product_phrase} You Should Check #Shorts",
        f"Smart {clean_title_part(PRODUCT_CATEGORY)} Find for Indian Homes #Shorts",
        f"Budget Friendly {product_phrase} for Home #Shorts",
    ]

    youtube_title = title_options[0][:95]

    hashtags = [
        "#Shorts",
        "#ProductReview",
        "#HomeProducts",
        "#DailyUseProducts",
        "#OnlineShopping",
        "#IndiaShopping",
    ]

    tags = list(dict.fromkeys([
        product_phrase.lower(),
        PRODUCT_CATEGORY.lower(),
        "home products",
        "daily use product",
        "useful product",
        "online shopping india",
        "product shorts",
        "trending products india",
        "budget product",
        "smart home product",
        "home organization",
        "kitchen products",
        "useful things for home",
        BRAND_NAME.lower(),
        *keywords,
    ]))

    tags = [tag for tag in tags if tag.strip()][:35]

    description_lines = [
        youtube_title,
        "",
        f"A short product video for {TARGET_AUDIENCE}. This reel highlights a practical {PRODUCT_CATEGORY} that may be useful for daily home routine.",
        "",
        "Why people may like it:",
        "- Practical for daily use",
        "- Easy to understand from the demo",
        "- Useful product idea for home shoppers",
        "- Good for quick product discovery",
        "",
        f"Brand: {BRAND_NAME}",
    ]

    if WEBSITE_URL:
        description_lines.append(f"Website: {WEBSITE_URL}")

    if WHATSAPP_NUMBER:
        description_lines.append(f"WhatsApp: {WHATSAPP_NUMBER}")

    description_lines.extend([
        "",
        "Note: Please check product details, price, delivery, and return policy before ordering.",
        "",
        " ".join(hashtags),
    ])

    description = "\n".join(description_lines)

    thumbnail_text_options = [
        product_phrase.upper()[:28],
        "USEFUL HOME FIND",
        "DAILY USE PRODUCT",
        "SMART PRODUCT IDEA",
    ]

    return {
        "youtube_title": youtube_title,
        "title_options": title_options,
        "description": description,
        "hashtags": hashtags,
        "tags": tags,
        "thumbnail_text_options": thumbnail_text_options,
        "pinned_comment": "Would you use this product at home? Comment YES or NO 👇",
        "chapters": [
            {"time": "0:00", "title": "Product preview"},
            {"time": "0:03", "title": "Main use case"},
            {"time": "0:07", "title": "Final look"},
        ],
        "detected_product_phrase": product_phrase,
        "detected_keywords": keywords,
        "analyzer_mode": "option3_free_transcript_template",
        "note": "This free version uses transcript, category hint, and SEO templates. Extracted frames are saved for manual review.",
        "transcript": transcript,
        "mp4_metadata": {
            "title": youtube_title,
            "artist": BRAND_NAME,
            "comment": f"{product_phrase} | {BRAND_NAME}",
            "description": description[:900],
            "keywords": ", ".join(tags[:20]),
            "copyright": BRAND_NAME,
        },
    }


def write_youtube_seo_files(output_video_path, seo_data, frame_paths):
    json_path = output_video_path.with_name(f"{output_video_path.stem}_youtube_seo.json")
    txt_path = output_video_path.with_name(f"{output_video_path.stem}_youtube_seo.txt")

    data_to_save = dict(seo_data)
    data_to_save["extracted_frames"] = [str(path) for path in frame_paths]

    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(data_to_save, file, indent=2, ensure_ascii=False)

    txt_content = f"""
TITLE:
{seo_data["youtube_title"]}

TITLE OPTIONS:
{chr(10).join("- " + item for item in seo_data.get("title_options", []))}

DESCRIPTION:
{seo_data["description"]}

TAGS:
{", ".join(seo_data.get("tags", []))}

HASHTAGS:
{" ".join(seo_data.get("hashtags", []))}

THUMBNAIL TEXT OPTIONS:
{chr(10).join("- " + item for item in seo_data.get("thumbnail_text_options", []))}

PINNED COMMENT:
{seo_data.get("pinned_comment", "")}

CHAPTERS:
{chr(10).join(item.get("time", "") + " - " + item.get("title", "") for item in seo_data.get("chapters", []))}

DETECTED PRODUCT PHRASE:
{seo_data.get("detected_product_phrase", "")}

DETECTED KEYWORDS:
{", ".join(seo_data.get("detected_keywords", []))}

ANALYZER MODE:
{seo_data.get("analyzer_mode", "")}

NOTE:
{seo_data.get("note", "")}

EXTRACTED FRAMES FOR MANUAL REVIEW:
{chr(10).join(str(path) for path in frame_paths)}

TRANSCRIPT:
{seo_data.get("transcript", "")}
""".strip()

    with open(txt_path, "w", encoding="utf-8") as file:
        file.write(txt_content)

    return json_path, txt_path


# ============================================================
# VIDEO FILTERS
# ============================================================

def build_video_filter():
    patch_x = f"W-{WATERMARK_RIGHT}-{WATERMARK_WIDTH}"
    patch_y = f"{WATERMARK_TOP}"

    logo_x = f"W-{WATERMARK_RIGHT}-{WATERMARK_WIDTH}+({WATERMARK_WIDTH}-w)/2"
    logo_y = f"{WATERMARK_TOP}+({WATERMARK_HEIGHT}-h)/2"

    return (
        f"[0:v]split=2[base][wm];"
        f"[wm]crop={WATERMARK_WIDTH}:{WATERMARK_HEIGHT}:iw-{WATERMARK_RIGHT}-{WATERMARK_WIDTH}:{WATERMARK_TOP},"
        f"boxblur=18:2[blurpatch];"
        f"[base][blurpatch]overlay=x={patch_x}:y={patch_y}[patched];"
        f"[1:v]scale={MY_LOGO_WIDTH}:-1[logo];"
        f"[patched][logo]overlay=x={logo_x}:y={logo_y}[v]"
    )


# ============================================================
# PROCESSING
# ============================================================

def process_video(input_video):
    output_video = OUTPUT_DIR / f"{input_video.stem}_processed.mp4"

    duration = get_video_duration(input_video)
    final_duration = max(0.5, duration - TRIM_END_SECONDS)
    audio_exists = has_audio_stream(input_video)

    print(f"\nProcessing: {input_video.name}")
    print(f"Original duration: {duration:.2f}s")
    print(f"Final duration: {final_duration:.2f}s")
    print(f"Audio stream: {'yes' if audio_exists else 'no'}")

    transcript = ""
    mute_ranges = []

    if audio_exists:
        print("Analyzing audio transcript and mute words...")
        transcript, mute_ranges = transcribe_and_find_mute_ranges(
            input_video,
            mute_words=MUTE_WORDS,
            model_size=WHISPER_MODEL,
        )
    else:
        print("No audio found. Skipping audio analysis.")

    if mute_ranges:
        print("Mute ranges:")
        for start, end in mute_ranges:
            print(f"  {start:.2f}s - {end:.2f}s")
    else:
        print("No mute ranges found.")

    analysis_dir = OUTPUT_DIR / "_analysis" / input_video.stem
    print("Extracting keyframes for manual review...")
    frame_paths = extract_keyframes(input_video, analysis_dir, frame_count=ANALYSIS_FRAME_COUNT)

    seo_data = build_option3_seo(transcript=transcript)
    metadata = seo_data["mp4_metadata"]

    filter_parts = [build_video_filter()]

    command = [
        "ffmpeg",
        "-y",
        "-i", str(input_video),
        "-i", str(LOGO_PATH),
        "-t", str(final_duration),
    ]

    if audio_exists:
        filter_parts.append(build_audio_filter(mute_ranges))

    command.extend([
        "-filter_complex", ";".join(filter_parts),
        "-map", "[v]",
    ])

    if audio_exists:
        command.extend(["-map", "[a]"])

    command.extend([
        "-metadata", f"title={metadata['title']}",
        "-metadata", f"artist={metadata['artist']}",
        "-metadata", f"comment={metadata['comment']}",
        "-metadata", f"description={metadata['description']}",
        "-metadata", f"keywords={metadata['keywords']}",
        "-metadata", f"copyright={metadata['copyright']}",
        "-c:v", "libx264",
        "-preset", OUTPUT_PRESET,
        "-crf", OUTPUT_CRF,
    ])

    if audio_exists:
        command.extend(["-c:a", "aac", "-b:a", OUTPUT_AUDIO_BITRATE])

    command.extend([
        "-movflags", "+faststart",
        str(output_video),
    ])

    run_command(command)

    json_path, txt_path = write_youtube_seo_files(output_video, seo_data, frame_paths)

    print(f"Saved video: {output_video}")
    print(f"Saved SEO JSON: {json_path}")
    print(f"Saved SEO TXT: {txt_path}")
    print("Review extracted frames to manually improve title if needed:")
    for frame_path in frame_paths:
        print(f"  {frame_path}")


def main():
    check_ffmpeg()

    if not INPUT_DIR.exists():
        raise RuntimeError(f"Input folder not found: {INPUT_DIR}")

    if not LOGO_PATH.exists():
        raise RuntimeError(f"Logo file not found: {LOGO_PATH}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "_analysis").mkdir(parents=True, exist_ok=True)

    videos = [file for file in INPUT_DIR.iterdir() if file.suffix.lower() in VIDEO_EXTENSIONS]

    if not videos:
        print(f"No videos found in input folder: {INPUT_DIR}")
        return

    print(f"Found {len(videos)} video(s).")

    for video in videos:
        try:
            process_video(video)
        except Exception as error:
            print(f"Failed: {video.name}")
            print(error)


if __name__ == "__main__":
    main()
