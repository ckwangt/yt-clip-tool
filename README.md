# YouTube Clip Screenshot + Subtitle Extractor

Paste a YouTube URL, specify a start/end time, and get:
1. A screenshot from the start second
2. All subtitle lines within that time range, merged into one block of text

## How it works

- Uses `yt-dlp` to resolve the video's direct streaming URL (without downloading the whole video) and its subtitle track (vtt).
- Uses `ffmpeg` to seek to the start second on that streaming URL and capture a single frame as a jpg.
- Downloads the vtt subtitle file and parses out the lines that fall within [start, end], merging YouTube's common "rolling" auto-caption duplication (via a diff-based algorithm) into one continuous block of text.

---

## Option 1: Deploy with Docker (recommended)

```bash
docker compose up -d --build
```

Once it's running, open `http://your-server-ip:5000` in a browser.

To change the default port from 5000, edit the `ports` setting in `docker-compose.yml`, e.g. change it to `"8080:5000"`.

---

## Option 2: Run directly on a server (no Docker)

### 1. Install system dependencies

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install -y python3 python3-pip python3-venv ffmpeg
```

### 2. Install Python packages

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Start with gunicorn (production)

```bash
gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 app:app
```

### 4. (Recommended) Keep it running with systemd

Create `/etc/systemd/system/yt-clip-tool.service`:

```ini
[Unit]
Description=YouTube Clip Tool
After=network.target

[Service]
User=www-data
WorkingDirectory=/path/to/yt-clip-tool
Environment="PATH=/path/to/yt-clip-tool/venv/bin"
ExecStart=/path/to/yt-clip-tool/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 --timeout 120 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now yt-clip-tool
```

### 5. (Recommended) Put Nginx + HTTPS in front

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Then get a free TLS certificate with `certbot --nginx`.

---

## Important notes & limitations

1. **yt-dlp needs to stay up to date**: YouTube frequently changes its page structure. If video resolution suddenly starts failing, run `pip install -U yt-dlp` (or rebuild the Docker image).
2. **Not every video has subtitles**: If a video has no subtitle track at all (manual or auto-generated), the field will show "no subtitles available for this video."
3. **Members-only / private / age-restricted videos may fail**: These require login cookies for yt-dlp to resolve, which isn't supported out of the box. If you need this, add a `cookiefile` parameter to the `ydl_opts` in `core.py`.
4. **Language priority**: Subtitles are currently picked in the order `zh-Hant → zh-TW → zh-Hans → zh-CN → zh → en`. Adjust `LANG_PRIORITY` in `core.py` as needed.
5. **Terms of use**: Be mindful that YouTube's Terms of Service place restrictions on downloading/extracting content. This project is intended for personal research, learning, and preparing source material for transformative/fair-use purposes — not for bulk reproduction and public redistribution of copyrighted content.
6. **Security (built in)**: Since this service fetches external content based on user-supplied URLs, it includes:
   - **Domain allowlist**: Only accepts `youtube.com` / `youtu.be` (including subdomains like `m.youtube.com`), blocking any attempt to use the service as an open proxy against other sites.
   - **Rate limiting**: 60 general requests/hour overall; `/process` (which actually runs yt-dlp + ffmpeg and is more resource-intensive) is further limited to 10 requests/hour. Adjust the numbers in the `limiter` config in `app.py`. If you scale to multiple machines/workers and want a shared rate-limit quota, switch `storage_uri="memory://"` to `storage_uri="redis://your-redis-host:6379"` (requires deploying Redis separately).
   - If running behind an Nginx reverse proxy, add `proxy_set_header X-Real-IP $remote_addr;` to your Nginx config, otherwise rate limiting will treat every visitor as the same IP.

---

## Project structure

```
yt-clip-tool/
├── app.py              # Flask routes
├── core.py             # Core logic: video/subtitle resolution, screenshot capture
├── templates/
│   └── index.html      # Frontend page
├── outputs/             # Generated screenshots (created automatically at runtime)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```
