# YouTube 片段截圖 + 字幕擷取工具

貼上 YouTube 網址、指定起訖秒數,輸出:
1. 起始秒的畫面截圖
2. 該時間範圍內所有字幕行串接而成的文字

## 原理

- 用 `yt-dlp` 解析出影片的可直接串流網址(不下載整部影片),以及字幕軌(vtt)網址。
- 用 `ffmpeg` 對該串流網址做 seek,只擷取起始秒那一幀,存成 jpg。
- 下載 vtt 字幕檔,解析出落在 [起始秒, 結束秒] 範圍內的字幕行,去除自動字幕常見的重覆逐字捲動,串接成一段文字。

---

## 方式一:用 Docker 部署(建議)

```bash
docker compose up -d --build
```

啟動後開瀏覽器到 `http://你的伺服器IP:5000` 即可使用。

若要換掉預設的 5000 port,改 `docker-compose.yml` 裡的 `ports` 設定即可,例如改成 `"8080:5000"`。

---

## 方式二:直接在伺服器上跑(不用 Docker)

### 1. 安裝系統相依套件

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install -y python3 python3-pip python3-venv ffmpeg
```

### 2. 安裝 Python 套件

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 用 gunicorn 啟動(正式環境)

```bash
gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 app:app
```

### 4.(建議)搭配 systemd 常駐

建立 `/etc/systemd/system/yt-clip-tool.service`:

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

### 5.(建議)前面加 Nginx 反向代理 + HTTPS

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

再用 `certbot --nginx` 申請 SSL 憑證。

---

## 重要限制與注意事項

1. **yt-dlp 需要持續更新**:YouTube 常改動網頁結構,若某天突然抓不到影片,先執行 `pip install -U yt-dlp`(或重建 Docker image)。
2. **並非所有影片都有字幕**:若影片完全沒有字幕軌(人工或自動),欄位會顯示「這部影片沒有可用的字幕」。
3. **會員限定 / 私人 / 年齡限制影片可能失敗**:這類影片 yt-dlp 需要額外提供登入 cookies 才能解析,預設版本不支援,如果你有需求,需要在 `core.py` 的 `ydl_opts` 加上 `cookiefile` 參數。
4. **語言優先序**:目前依 `zh-Hant → zh-TW → zh-Hans → zh-CN → zh → en` 順序挑字幕,可在 `core.py` 的 `LANG_PRIORITY` 調整。
5. **使用條款**:請注意 YouTube 服務條款對下載/擷取內容有其規範,建議僅供個人研究、學習、內容二次創作前的素材整理等合理使用情境,不要用來大量重製他人受著作權保護的內容並公開散布。
6. **安全性(已內建)**:這個服務會依使用者輸入的網址去抓取外部內容,已加入以下防護:
   - **網域白名單**:只接受 `youtube.com` / `youtu.be` 網域(含子網域,如 `m.youtube.com`),擋掉任何嘗試把服務當代理伺服器打其他站台的請求。
   - **速率限制**:整體每小時 60 次一般請求;`/process`(實際跑 yt-dlp + ffmpeg、較吃資源)額外收緊為每小時 10 次。可在 `app.py` 的 `limiter` 設定調整數字。若之後架多台機器/多個 worker 想共用同一份限制額度,把 `storage_uri="memory://"` 換成 `storage_uri="redis://your-redis-host:6379"`(需另外部署 Redis)。
   - 若架在 Nginx 反向代理後面,要在 Nginx 設定加 `proxy_set_header X-Real-IP $remote_addr;`,否則速率限制會把所有人都當成同一個 IP。

---

## 檔案結構

```
yt-clip-tool/
├── app.py              # Flask 路由
├── core.py             # 核心邏輯:解析影片、字幕、截圖
├── templates/
│   └── index.html      # 前端頁面
├── outputs/             # 產生的截圖存放處(執行時自動建立)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```
