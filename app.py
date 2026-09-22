import os
import re
import tempfile
import uuid

from flask import Flask, render_template, request, send_from_directory, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from core import process_clip, ExtractError
from i18n import get_translations, normalize_lang, DEFAULT_LANG

app = Flask(__name__)

# Rate limiting: prevents a single source from hammering the service and
# draining bandwidth/CPU.
# If running behind an nginx reverse proxy in production, set up
# X-Forwarded-For so the real client IP is detected — see the Nginx config
# example in the README (add proxy_set_header X-Real-IP $remote_addr;)
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["60 per hour"],
    storage_uri="memory://",  # For a shared quota across multiple machines/workers, switch to redis:// — see README
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


_FILENAME_UNSAFE_RE = re.compile(r'[\\/:*?"<>|]+')


def sanitize_filename_part(text: str, max_len: int = 40) -> str:
    """Strips characters invalid in Windows/Unix filenames and collapses whitespace"""
    text = _FILENAME_UNSAFE_RE.sub("-", text.strip())
    text = re.sub(r"\s+", "_", text)
    return text[:max_len].strip("_-") or "clip"


def build_download_filename(title: str, start_sec: float, end_sec: float, subtitle_lang: str) -> str:
    title_part = sanitize_filename_part(title, max_len=30)
    start_part = f"{start_sec:g}"
    end_part = f"{end_sec:g}"
    lang_part = subtitle_lang or "nosub"
    return f"{title_part}_{start_part}_{end_part}_{lang_part}.jpg"


def parse_time_to_seconds(raw: str) -> float:
    """Accepts plain seconds (90) or mm:ss / hh:mm:ss format"""
    raw = raw.strip()
    if re.fullmatch(r"\d+(\.\d+)?", raw):
        return float(raw)
    parts = raw.split(":")
    parts = [float(p) for p in parts]
    if len(parts) == 2:
        m, s = parts
        return m * 60 + s
    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s
    raise ValueError(f"Could not parse time format: {raw}")


@app.route("/", methods=["GET"])
def index():
    lang = normalize_lang(request.args.get("lang", DEFAULT_LANG))
    t = get_translations(lang)
    return render_template("index.html", t=t, lang=lang)


@app.route("/process", methods=["POST"])
@limiter.limit("10 per hour")  # This route runs yt-dlp + ffmpeg and is resource-intensive, so it's rate-limited more tightly
def process():
    lang = normalize_lang(request.form.get("lang", DEFAULT_LANG))
    t = get_translations(lang)

    youtube_url = request.form.get("youtube_url", "").strip()
    start_raw = request.form.get("start_time", "").strip()
    end_raw = request.form.get("end_time", "").strip()

    error = None
    result = None

    if not youtube_url or not start_raw or not end_raw:
        error = t["error_missing_fields"]
    else:
        try:
            start_sec = parse_time_to_seconds(start_raw)
            end_sec = parse_time_to_seconds(end_raw)
            data = process_clip(youtube_url, start_sec, end_sec, OUTPUT_DIR)

            frame_filename = os.path.basename(data["frame_path"])
            result = {
                "title": data["title"],
                "frame_url": url_for("serve_output", filename=frame_filename),
                "download_filename": build_download_filename(
                    data["title"], start_sec, end_sec, data["subtitle_lang"]
                ),
                "subtitle_text": data["subtitle_text"],
                "subtitle_lang": data["subtitle_lang"],
                "subtitle_is_auto": data["subtitle_is_auto"],
                "start_raw": start_raw,
                "end_raw": end_raw,
            }
        except (ExtractError, ValueError) as e:
            error = str(e)
        except Exception as e:
            error = t["error_unexpected"].format(error=e)

    return render_template(
        "index.html",
        t=t,
        lang=lang,
        error=error,
        result=result,
        youtube_url=youtube_url,
        start_time=start_raw,
        end_time=end_raw,
    )


@app.errorhandler(429)
def ratelimit_handler(e):
    lang = normalize_lang(request.values.get("lang", DEFAULT_LANG))
    t = get_translations(lang)
    return render_template(
        "index.html",
        t=t,
        lang=lang,
        error=t["error_rate_limit"],
    ), 429


@app.route("/outputs/<path:filename>")
def serve_output(filename):
    return send_from_directory(OUTPUT_DIR, filename)


if __name__ == "__main__":
    # For local development; use gunicorn in production (see README)
    app.run(host="0.0.0.0", port=5000, debug=False)
