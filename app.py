import os
import re
import tempfile
import uuid

from flask import Flask, render_template, request, send_from_directory, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from core import process_clip, ExtractError

app = Flask(__name__)

# 速率限制:避免服務被單一來源狂打導致頻寬/CPU被榨乾
# 正式環境若架在 nginx 反向代理後面,需要設定 X-Forwarded-For 才能抓到真實 IP,
# 詳見 README 的 Nginx 設定範例(要加 proxy_set_header X-Real-IP $remote_addr;)
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["60 per hour"],
    storage_uri="memory://",  # 多台機器/多worker共用限制的話,建議換成 redis://,見 README
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def parse_time_to_seconds(raw: str) -> float:
    """支援輸入純秒數(90)或 mm:ss / hh:mm:ss 格式"""
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
    raise ValueError(f"無法解析時間格式: {raw}")


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/process", methods=["POST"])
@limiter.limit("10 per hour")  # 這支路由會跑 yt-dlp + ffmpeg,較吃資源,額外收緊限制
def process():
    youtube_url = request.form.get("youtube_url", "").strip()
    start_raw = request.form.get("start_time", "").strip()
    end_raw = request.form.get("end_time", "").strip()

    error = None
    result = None

    if not youtube_url or not start_raw or not end_raw:
        error = "請完整填寫 YouTube 網址、起始秒數與結束秒數"
    else:
        try:
            start_sec = parse_time_to_seconds(start_raw)
            end_sec = parse_time_to_seconds(end_raw)
            data = process_clip(youtube_url, start_sec, end_sec, OUTPUT_DIR)

            frame_filename = os.path.basename(data["frame_path"])
            result = {
                "title": data["title"],
                "frame_url": url_for("serve_output", filename=frame_filename),
                "subtitle_text": data["subtitle_text"],
                "subtitle_lang": data["subtitle_lang"],
                "subtitle_is_auto": data["subtitle_is_auto"],
                "start_raw": start_raw,
                "end_raw": end_raw,
            }
        except (ExtractError, ValueError) as e:
            error = str(e)
        except Exception as e:
            error = f"發生未預期的錯誤: {e}"

    return render_template(
        "index.html",
        error=error,
        result=result,
        youtube_url=youtube_url,
        start_time=start_raw,
        end_time=end_raw,
    )


@app.errorhandler(429)
def ratelimit_handler(e):
    return render_template(
        "index.html",
        error="請求太頻繁了,請稍後再試(速率限制:每小時最多 10 次處理請求)",
    ), 429


@app.route("/outputs/<path:filename>")
def serve_output(filename):
    return send_from_directory(OUTPUT_DIR, filename)


if __name__ == "__main__":
    # 本機開發用;正式環境請用 gunicorn(見 README)
    app.run(host="0.0.0.0", port=5000, debug=False)
