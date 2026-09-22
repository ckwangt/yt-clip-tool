"""
core.py
Responsible for:
1. Using yt-dlp to resolve a YouTube video's direct streaming URL and subtitle track info
2. Downloading/parsing VTT subtitles, filtering to a given time range, and merging into one block of text
3. Using ffmpeg to seek to a given second and capture a single frame as a jpg
"""

import os
import re
import subprocess
import tempfile
import uuid
from urllib.parse import urlparse

import requests
import yt_dlp

# Subtitle language priority order (adjust as needed)
LANG_PRIORITY = ["zh-Hant", "zh-TW", "zh-Hans", "zh-CN", "zh", "en"]

# Only these domains are allowed, to prevent the service from being used as an open proxy
ALLOWED_HOST_SUFFIXES = (
    "youtube.com",
    "youtube-nocookie.com",
    "youtu.be",
)


class ExtractError(Exception):
    pass


def validate_youtube_url(url: str) -> str:
    """
    Validates that the URL's domain is YouTube, and returns the normalized URL.
    Raises ExtractError if invalid; callers don't need to check separately.
    """
    url = (url or "").strip()
    if not url:
        raise ExtractError("Please enter a YouTube URL")

    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url

    try:
        parsed = urlparse(url)
    except Exception:
        raise ExtractError("Invalid URL format")

    host = (parsed.hostname or "").lower()
    if not host:
        raise ExtractError("Invalid URL format")

    # After stripping subdomain prefixes like www., check whether the host matches an allowed domain (or its subdomain)
    is_allowed = any(
        host == suffix or host.endswith("." + suffix)
        for suffix in ALLOWED_HOST_SUFFIXES
    )
    if not is_allowed:
        raise ExtractError("Only YouTube URLs are accepted (youtube.com / youtu.be)")

    return url


def _pick_subtitle_url(info: dict):
    """From yt-dlp's info dict, pick a subtitle track URL by language priority (vtt preferred)"""
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}

    def find_in(track_dict, lang):
        entries = track_dict.get(lang)
        if not entries:
            return None
        # Prefer vtt format
        for e in entries:
            if e.get("ext") == "vtt":
                return e["url"]
        return entries[0].get("url")

    # Check manually uploaded subtitles first, then auto-generated ones
    for lang in LANG_PRIORITY:
        url = find_in(subs, lang)
        if url:
            return url, lang, False
    for lang in LANG_PRIORITY:
        url = find_in(auto, lang)
        if url:
            return url, lang, True

    # No priority language found, fall back to whatever's available
    if subs:
        lang = next(iter(subs))
        url = find_in(subs, lang)
        if url:
            return url, lang, False
    if auto:
        lang = next(iter(auto))
        url = find_in(auto, lang)
        if url:
            return url, lang, True

    return None, None, None


def get_video_info(youtube_url: str) -> dict:
    """Resolves the video and returns direct_url (streamable), title, subtitle URL, etc."""
    ydl_opts = {
        # Screenshots only need the video track, so prefer a video-only format
        # (no audio, no merging required) and fall back to a combined stream.
        # Excludes HLS (m3u8) since ffmpeg seeking against an HLS manifest can
        # hang/time out, and caps resolution at 1080p since screenshots don't
        # need more.
        "format": (
            "bv*[height<=1080][protocol!=m3u8][protocol!=m3u8_native][ext=mp4]"
            "/bv*[height<=1080][protocol!=m3u8][protocol!=m3u8_native]"
            "/bv*[ext=mp4]/bv*/best[ext=mp4]/best"
        ),
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
    except Exception as e:
        raise ExtractError(f"Could not resolve the video: {e}")

    direct_url = info.get("url")
    if not direct_url and info.get("requested_formats"):
        # Some cases split into separate audio/video tracks — take the video track
        direct_url = info["requested_formats"][0].get("url")
    if not direct_url:
        raise ExtractError("No usable video stream URL found (may be members-only / private / region-restricted)")

    sub_url, sub_lang, is_auto = _pick_subtitle_url(info)

    return {
        "title": info.get("title", ""),
        "duration": info.get("duration", 0),
        "direct_url": direct_url,
        "subtitle_url": sub_url,
        "subtitle_lang": sub_lang,
        "subtitle_is_auto": is_auto,
    }


def _timestamp_to_seconds(ts: str) -> float:
    """Converts a VTT timestamp (HH:MM:SS.mmm or MM:SS.mmm) to seconds"""
    parts = ts.strip().split(":")
    parts = [p.replace(",", ".") for p in parts]
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h = "0"
        m, s = parts
    else:
        raise ValueError(f"Could not parse timestamp: {ts}")
    return int(h) * 3600 + int(m) * 60 + float(s)


_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(text: str) -> str:
    text = _TAG_RE.sub("", text)
    text = text.replace("&nbsp;", " ").strip()
    return text


_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7a3]")


def _is_cjk_heavy(text: str) -> bool:
    """Determines whether text is predominantly CJK (whitespace tokenization doesn't apply to these languages)"""
    if not text:
        return False
    cjk_count = len(_CJK_RE.findall(text))
    return cjk_count >= max(1, len(text) * 0.3)


def _merge_rolling_captions(cue_texts: list) -> str:
    """
    YouTube auto-captions commonly use a "rolling" format where each cue partially
    overlaps the previous one's text
    (e.g. cue1='hello world', cue2='hello world how are', cue3='how are you today').
    Uses difflib to find the part of each cue that's new relative to the accumulated
    result so far, and appends only that new part, avoiding duplicated text; for
    ordinary (non-overlapping) manual subtitles this is equivalent to a plain
    concatenation and doesn't change the result.

    CJK text has no whitespace tokenization, so it's compared character-by-character;
    other languages are tokenized by whitespace and compared word-by-word.
    """
    import difflib

    is_cjk = any(_is_cjk_heavy(t) for t in cue_texts[:5]) if cue_texts else False

    def tokenize(text):
        return list(text) if is_cjk else text.split()

    def join(tokens):
        return "".join(tokens) if is_cjk else " ".join(tokens)

    merged_tokens = []
    for text in cue_texts:
        tokens = tokenize(text)
        if not tokens:
            continue
        if not merged_tokens:
            merged_tokens.extend(tokens)
            continue

        # Only compare against the "tail" of the accumulated result so far, to avoid comparing against the whole video's subtitles and slowing things down
        tail_window = merged_tokens[-max(len(tokens) * 3, 30):]
        matcher = difflib.SequenceMatcher(a=tail_window, b=tokens, autojunk=False)
        match = matcher.find_longest_match(0, len(tail_window), 0, len(tokens))

        if match.size >= 1:
            new_part = tokens[match.b + match.size:]
        else:
            new_part = tokens

        merged_tokens.extend(new_part)

    return join(merged_tokens)


def parse_vtt_range(vtt_text: str, start_sec: float, end_sec: float) -> str:
    """
    Parses VTT content and returns all subtitle lines within [start_sec, end_sec],
    merging YouTube's common rolling auto-caption duplication and joining them
    into one block of text.
    """
    blocks = re.split(r"\n\s*\n", vtt_text.replace("\r\n", "\n"))
    time_re = re.compile(
        r"(\d{1,2}:\d{2}(?::\d{2})?\.\d{3})\s*-->\s*(\d{1,2}:\d{2}(?::\d{2})?\.\d{3})"
    )

    cue_texts = []

    for block in blocks:
        m = time_re.search(block)
        if not m:
            continue
        b_start = _timestamp_to_seconds(m.group(1))
        b_end = _timestamp_to_seconds(m.group(2))

        # Check whether this cue overlaps [start_sec, end_sec]
        if b_end < start_sec or b_start > end_sec:
            continue

        lines = block.split("\n")
        # Skip the cue-number line if the first line is purely numeric, and skip the timestamp line
        text_lines = []
        for line in lines:
            if time_re.search(line):
                continue
            if line.strip().isdigit():
                continue
            cleaned = _clean_text(line)
            if cleaned:
                text_lines.append(cleaned)

        text = " ".join(text_lines).strip()
        if text:
            cue_texts.append(text)

    return _merge_rolling_captions(cue_texts)


def fetch_subtitle_text(subtitle_url: str, start_sec: float, end_sec: float) -> str:
    resp = requests.get(subtitle_url, timeout=20)
    resp.raise_for_status()
    return parse_vtt_range(resp.text, start_sec, end_sec)


def capture_frame(direct_video_url: str, at_second: float, out_dir: str) -> str:
    """Uses ffmpeg to seek the direct video URL and capture a single frame as a jpg, returning the file path"""
    out_path = os.path.join(out_dir, f"frame_{uuid.uuid4().hex}.jpg")

    # Placing -ss before -i enables input seeking, which is faster for remote streams
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(max(at_second, 0)),
        "-i", direct_video_url,
        "-frames:v", "1",
        "-q:v", "2",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0 or not os.path.exists(out_path):
        raise ExtractError(f"ffmpeg failed to capture the frame: {result.stderr[-800:]}")
    return out_path


def process_clip(youtube_url: str, start_sec: float, end_sec: float, out_dir: str) -> dict:
    if end_sec <= start_sec:
        raise ExtractError("End time must be later than start time")

    youtube_url = validate_youtube_url(youtube_url)

    info = get_video_info(youtube_url)

    if info["duration"] and end_sec > info["duration"]:
        raise ExtractError(
            f"End time ({end_sec}) exceeds the video's duration ({info['duration']}s)"
        )

    frame_path = capture_frame(info["direct_url"], start_sec, out_dir)

    subtitle_text = ""
    if info["subtitle_url"]:
        try:
            subtitle_text = fetch_subtitle_text(info["subtitle_url"], start_sec, end_sec)
        except Exception as e:
            subtitle_text = f"(Failed to fetch subtitles: {e})"
    else:
        subtitle_text = "(No subtitles available for this video)"

    return {
        "title": info["title"],
        "frame_path": frame_path,
        "subtitle_text": subtitle_text,
        "subtitle_lang": info["subtitle_lang"],
        "subtitle_is_auto": info["subtitle_is_auto"],
    }
