"""
core.py
負責:
1. 用 yt-dlp 解析 YouTube 影片,取得可直接串流的 URL 與字幕軌資訊
2. 下載 / 解析 VTT 字幕,篩出指定秒數範圍內的字幕並串接成一段文字
3. 用 ffmpeg 對指定秒數做 seek,擷取單一畫面存成 jpg
"""

import os
import re
import subprocess
import tempfile
import uuid
from urllib.parse import urlparse

import requests
import yt_dlp

# 依優先順序挑選字幕語言(可依需求增減)
LANG_PRIORITY = ["zh-Hant", "zh-TW", "zh-Hans", "zh-CN", "zh", "en"]

# 只允許這些網域,避免服務被拿來當代理伺服器抓取任意網址
ALLOWED_HOST_SUFFIXES = (
    "youtube.com",
    "youtube-nocookie.com",
    "youtu.be",
)


class ExtractError(Exception):
    pass


def validate_youtube_url(url: str) -> str:
    """
    驗證網址網域是否為 YouTube,並回傳正規化後的網址。
    不合法時丟出 ExtractError,呼叫端不需要另外檢查。
    """
    url = (url or "").strip()
    if not url:
        raise ExtractError("請輸入 YouTube 網址")

    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url

    try:
        parsed = urlparse(url)
    except Exception:
        raise ExtractError("網址格式不正確")

    host = (parsed.hostname or "").lower()
    if not host:
        raise ExtractError("網址格式不正確")

    # 去掉開頭的 www. 之類子網域前綴後,檢查是否命中允許的網域(或其子網域)
    is_allowed = any(
        host == suffix or host.endswith("." + suffix)
        for suffix in ALLOWED_HOST_SUFFIXES
    )
    if not is_allowed:
        raise ExtractError("只接受 YouTube 網址(youtube.com / youtu.be)")

    return url


def _pick_subtitle_url(info: dict):
    """從 yt-dlp 回傳的 info dict 中,依語言優先序挑一個字幕軌網址(vtt優先)"""
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}

    def find_in(track_dict, lang):
        entries = track_dict.get(lang)
        if not entries:
            return None
        # 優先找 vtt 格式
        for e in entries:
            if e.get("ext") == "vtt":
                return e["url"]
        return entries[0].get("url")

    # 先找人工上傳字幕,再找自動生成字幕
    for lang in LANG_PRIORITY:
        url = find_in(subs, lang)
        if url:
            return url, lang, False
    for lang in LANG_PRIORITY:
        url = find_in(auto, lang)
        if url:
            return url, lang, True

    # 都找不到指定語言,退而求其次抓任何一種
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
    """解析影片,回傳 direct_url(可直接串流)、標題、字幕網址等資訊"""
    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
    except Exception as e:
        raise ExtractError(f"無法解析影片:{e}")

    direct_url = info.get("url")
    if not direct_url and info.get("requested_formats"):
        # 有些情況會拆成分離的影音軌,取影像軌
        direct_url = info["requested_formats"][0].get("url")
    if not direct_url:
        raise ExtractError("找不到可用的影片串流網址(可能是會員限定/私人影片/地區限制)")

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
    """把 VTT 時間戳 (HH:MM:SS.mmm 或 MM:SS.mmm) 轉成秒數"""
    parts = ts.strip().split(":")
    parts = [p.replace(",", ".") for p in parts]
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h = "0"
        m, s = parts
    else:
        raise ValueError(f"無法解析時間戳: {ts}")
    return int(h) * 3600 + int(m) * 60 + float(s)


_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(text: str) -> str:
    text = _TAG_RE.sub("", text)
    text = text.replace("&nbsp;", " ").strip()
    return text


_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7a3]")


def _is_cjk_heavy(text: str) -> bool:
    """判斷文字是否以中日韓文字為主(此類語言用空白分詞沒有意義)"""
    if not text:
        return False
    cjk_count = len(_CJK_RE.findall(text))
    return cjk_count >= max(1, len(text) * 0.3)


def _merge_rolling_captions(cue_texts: list) -> str:
    """
    YouTube 自動字幕常見「逐字捲動」格式:每個 cue 跟前一個 cue 有部分文字重疊
    (例如 cue1='hello world', cue2='hello world how are', cue3='how are you today')。
    用 difflib 找出每個 cue 相對於前一個累積結果新增的部分,只把新增部分接上去,
    避免重複文字;對一般(無重疊)人工字幕則等同直接串接,不影響結果。

    中日韓文字沒有空白分詞,改用逐字比對;其餘語言用空白分詞後逐詞比對。
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

        # 只跟目前累積結果的「尾端一段」比對,避免整部影片字幕都拿來比對拖慢速度
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
    解析 VTT 內容,回傳 [start_sec, end_sec] 範圍內所有字幕行,
    合併 YouTube 自動字幕常見的逐字捲動重覆後,串接成一段文字。
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

        # 判斷這段字幕是否與 [start_sec, end_sec] 有重疊
        if b_end < start_sec or b_start > end_sec:
            continue

        lines = block.split("\n")
        # 第一行若是純數字(cue編號)就跳過,再跳過時間戳那行
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
    """用 ffmpeg 對直連影片網址做 seek,擷取單一畫面存成 jpg,回傳檔案路徑"""
    out_path = os.path.join(out_dir, f"frame_{uuid.uuid4().hex}.jpg")

    # -ss 放在 -i 之前可以用 input seeking,對遠端串流較快
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
        raise ExtractError(f"ffmpeg 擷取畫面失敗: {result.stderr[-800:]}")
    return out_path


def process_clip(youtube_url: str, start_sec: float, end_sec: float, out_dir: str) -> dict:
    if end_sec <= start_sec:
        raise ExtractError("結束秒數必須大於起始秒數")

    youtube_url = validate_youtube_url(youtube_url)

    info = get_video_info(youtube_url)

    if info["duration"] and end_sec > info["duration"]:
        raise ExtractError(
            f"結束秒數({end_sec})超過影片長度({info['duration']}秒)"
        )

    frame_path = capture_frame(info["direct_url"], start_sec, out_dir)

    subtitle_text = ""
    if info["subtitle_url"]:
        try:
            subtitle_text = fetch_subtitle_text(info["subtitle_url"], start_sec, end_sec)
        except Exception as e:
            subtitle_text = f"(字幕擷取失敗: {e})"
    else:
        subtitle_text = "(這部影片沒有可用的字幕)"

    return {
        "title": info["title"],
        "frame_path": frame_path,
        "subtitle_text": subtitle_text,
        "subtitle_lang": info["subtitle_lang"],
        "subtitle_is_auto": info["subtitle_is_auto"],
    }
