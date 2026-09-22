"""
i18n.py
Simple static translation dictionary for the two supported UI languages.
Not a full i18n framework — just enough for this app's small set of strings.
"""

TRANSLATIONS = {
    "en": {
        "title": "YouTube Clip Screenshot + Subtitle Extractor",
        "heading": "🎬 YouTube Clip Screenshot + Subtitle Extractor",
        "subtitle_note": "Paste a YouTube URL and a time range to get a screenshot from the start second plus the full subtitle text for that range.",
        "label_url": "YouTube video URL",
        "placeholder_url": "https://www.youtube.com/watch?v=...",
        "label_start": "Start time",
        "placeholder_start": "e.g. 90 or 1:30",
        "label_end": "End time",
        "placeholder_end": "e.g. 120 or 2:00",
        "hint_time": "Enter plain seconds (e.g. 90) or mm:ss / hh:mm:ss format (e.g. 1:30)",
        "button_submit": "Generate screenshot & subtitles",
        "label_result_subtitle": "Subtitle text",
        "button_copy": "Copy subtitle text",
        "button_save_image": "Save image as...",
        "alert_copied": "Subtitle text copied",
        "meta_lang_prefix": "Subtitle language:",
        "meta_auto_suffix": " (YouTube auto-generated)",
        "alt_screenshot": "Video screenshot",
        "error_missing_fields": "Please fill in the YouTube URL, start time, and end time",
        "error_unexpected": "An unexpected error occurred: {error}",
        "error_rate_limit": "Too many requests — please try again later (rate limit: 10 processing requests per hour)",
    },
    "zh": {
        "title": "YouTube 片段截圖 + 字幕擷取工具",
        "heading": "🎬 YouTube 片段截圖 + 字幕擷取工具",
        "subtitle_note": "貼上 YouTube 網址與時間範圍,取得起始畫面截圖與該區間的完整字幕文字。",
        "label_url": "YouTube 影片網址",
        "placeholder_url": "https://www.youtube.com/watch?v=...",
        "label_start": "起始時間",
        "placeholder_start": "例如 90 或 1:30",
        "label_end": "結束時間",
        "placeholder_end": "例如 120 或 2:00",
        "hint_time": "可輸入純秒數(如 90)或 mm:ss / hh:mm:ss 格式(如 1:30)",
        "button_submit": "產生截圖與字幕",
        "label_result_subtitle": "字幕內容",
        "button_copy": "複製字幕文字",
        "button_save_image": "另存新檔",
        "alert_copied": "已複製字幕文字",
        "meta_lang_prefix": "字幕語言:",
        "meta_auto_suffix": "(YouTube 自動生成)",
        "alt_screenshot": "影片截圖",
        "error_missing_fields": "請完整填寫 YouTube 網址、起始秒數與結束秒數",
        "error_unexpected": "發生未預期的錯誤:{error}",
        "error_rate_limit": "請求太頻繁了,請稍後再試(速率限制:每小時最多 10 次處理請求)",
    },
}

DEFAULT_LANG = "en"


def get_translations(lang: str) -> dict:
    """Returns the translation dict for a language code, falling back to the default if unrecognized."""
    return TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANG])


def normalize_lang(lang: str) -> str:
    """Returns a valid language code, falling back to the default if the input isn't supported."""
    return lang if lang in TRANSLATIONS else DEFAULT_LANG
