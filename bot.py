"""
Telegram Link -> Video Bot
Powered by: https://seowebchecker.com/video-downloader/from-any-url

Kaam kaise karta hai:
1. Koi bhi link aate hi bot us link ko seowebchecker ke video-downloader API par bhejta hai
2. Wahan se direct video URL milta hai (1000+ sites: Insta, YT, TikTok, FB, X, Vimeo...)
3. Bot wahi video download karke Telegram me bhej deta hai (direct PLAY hoga)
4. Agar site fail ho jaye to fallback: yt-dlp se download

Setup:
1. pip install -r requirements.txt
2. .env.example ko .env me copy karo aur BOT_TOKEN dalo
3. Bot ko Group me ADD karo + ADMIN banao (Delete Messages permission ON)
4. python bot.py
"""

import asyncio
import logging
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Sirf in groups me chalega. Empty = sab jagah chalega.
# Render/Koyeb me Env Var: ALLOWED_GROUP_IDS=-1004451914143,-1004334916764
_raw_ids = os.getenv("ALLOWED_GROUP_IDS", "").strip()
try:
    ALLOWED_GROUP_IDS: set[int] = (
        {int(x.strip()) for x in _raw_ids.split(",") if x.strip()} if _raw_ids else set()
    )
except ValueError:
    ALLOWED_GROUP_IDS = set()

# Render/Koyeb health-check ke liye port (Web Service banoge to kaam ayega)
PORT = int(os.getenv("PORT", "8000"))

# Kitne video ek saath download ho (RAM/CPU bachane ke liye)
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "3"))

# Telegram Bot API limit 50MB -> safe side 48MB
MAX_FILE_MB = float(os.getenv("MAX_FILE_MB", "48"))
MAX_BYTES = int(MAX_FILE_MB * 1024 * 1024)

# Download engine:
#   seowebchecker = SIRF https://seowebchecker.com/video-downloader (default)
#   auto = pehle site, fail hone par yt-dlp
#   ytdlp = sirf yt-dlp
DOWNLOAD_SOURCE = os.getenv("DOWNLOAD_SOURCE", "seowebchecker").strip().lower()

# ---------- Website (download source) ----------
SWC_PAGE = "https://seowebchecker.com/video-downloader/from-any-url"
SWC_API = "https://seowebchecker.com/video-downloader/api/download"
SWC_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://seowebchecker.com",
    "Referer": SWC_PAGE,
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
}
MEDIA_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
log = logging.getLogger("reel-bot")

DL_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT)

# ---------- 1. Link detect ----------
# Website 1000+ sites support karti hai, isliye koi bhi http(s) link chalta hai.
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
# In links ka koi matlab nahi (bot khud, telegram invite etc.)
SKIP_HOSTS = ("t.me/", "telegram.me/", "telegram.dog/")

MAX_URL_LEN = 1500


def find_links(text: str) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    for m in URL_RE.finditer(text):
        url = m.group(0).rstrip(").>,!?;:'\"")
        if len(url) > MAX_URL_LEN:
            continue
        low = url.lower()
        if any(h in low for h in SKIP_HOSTS):
            continue
        out.append(url)
    return out


def platform_name(url: str) -> str:
    u = url.lower()
    table = (
        ("instagram", "Instagram"),
        ("instagr.am", "Instagram"),
        ("youtube", "YouTube"),
        ("youtu.be", "YouTube"),
        ("tiktok", "TikTok"),
        ("facebook", "Facebook"),
        ("fb.watch", "Facebook"),
        ("twitter", "X (Twitter)"),
        ("x.com", "X (Twitter)"),
        ("vimeo", "Vimeo"),
        ("dailymotion", "Dailymotion"),
        ("dai.ly", "Dailymotion"),
        ("reddit", "Reddit"),
        ("linkedin", "LinkedIn"),
        ("twitch", "Twitch"),
        ("mojapp", "Moj"),
        ("myjosh", "Josh"),
        ("sharechat", "ShareChat"),
    )
    for key, name in table:
        if key in u:
            return name
    return "Video"


def human_size(num: int | float | None) -> str:
    if not num:
        return ""
    size = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return ""


def duration_seconds(value: str | int | None) -> int:
    """'10:35' / '1:02:03' / 635 -> seconds."""
    if not value:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    try:
        parts = [int(p) for p in str(value).split(":")]
    except ValueError:
        return 0
    secs = 0
    for p in parts:
        secs = secs * 60 + p
    return secs


# ---------- 2. Website se video link nikalna ----------
@dataclass
class Media:
    """Result of a fetch attempt."""

    path: Path | None = None
    title: str = ""
    owner: str = ""
    platform: str = "Video"
    duration: int = 0
    thumbnail: str = ""
    source: str = ""
    fallback_url: str = ""  # direct link (bade file ke liye user ko dene ke liye)
    too_big: bool = False
    note: str = ""


def _swc_resolve(url: str) -> dict | None:
    """Website ke API se formats nikalta hai (blocking call)."""
    try:
        resp = requests.post(
            SWC_API,
            files={"igUrl": (None, url)},
            headers=SWC_HEADERS,
            timeout=(15, 180),
        )
    except Exception as e:
        log.warning("site api fail %s : %s", url, e)
        return None

    if resp.status_code != 200:
        log.warning("site api status %s for %s", resp.status_code, url)
        return None
    try:
        payload = resp.json()
    except Exception:
        log.warning("site api ne json nahi diya for %s", url)
        return None

    if not payload.get("success") or not payload.get("data"):
        log.info("site api: %s -> %s", url, payload.get("message"))
        return None
    return payload["data"]


def _pick_candidates(formats: list[dict], max_bytes: int) -> tuple[list[dict], dict | None]:
    """Best-first download candidates (size limit ke andar) + sabse chhota oversize link."""
    video: list[dict] = []
    audio: list[dict] = []
    for fmt in formats or []:
        if not fmt.get("url"):
            continue
        label = str(fmt.get("label") or "").upper()
        (audio if label in {"MP3", "M4A", "AUDIO", "WEBM AUDIO"} else video).append(fmt)

    def score(fmt: dict) -> int:
        size = fmt.get("filesize") or 0
        label = str(fmt.get("label") or "").upper()
        bonus = 1 if label == "MP4" else 0
        return (1 if size else 0, size, bonus)

    pool = video or audio
    fitting = [
        f for f in pool if not f.get("filesize") or int(f["filesize"]) <= max_bytes
    ]
    oversize = sorted(
        [f for f in pool if f.get("filesize") and int(f["filesize"]) > max_bytes],
        key=lambda f: int(f["filesize"]),
    )

    # Bada = better quality, par sirf jab size pata ho
    fitting.sort(key=score, reverse=True)
    return fitting, (oversize[0] if oversize else None)


def _direct_download(fmt_url: str, outdir: Path, max_bytes: int) -> tuple[Path | None, str]:
    """Direct media URL ko file me save karta hai. (path, reason)."""
    try:
        resp = requests.get(
            fmt_url,
            headers={
                "User-Agent": MEDIA_UA,
                "Accept": "*/*",
                "Referer": SWC_PAGE,
            },
            stream=True,
            timeout=(20, 120),
            allow_redirects=True,
        )
    except Exception as e:
        return None, f"connect fail: {e}"

    with resp:
        if resp.status_code != 200:
            return None, f"http {resp.status_code}"

        ctype = (resp.headers.get("Content-Type") or "").lower()
        if ctype.startswith("text/") or "html" in ctype:
            return None, f"html aaya ({ctype})"

        length = resp.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > max_bytes:
            return None, "file bada hai"

        if "audio" in ctype:
            ext = ".m4a" if "mp4" in ctype else ".mp3"
        elif "webm" in ctype:
            ext = ".webm"
        else:
            ext = ".mp4"

        path = outdir / f"{uuid.uuid4().hex[:10]}{ext}"
        written = 0
        try:
            with open(path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > max_bytes:
                        fh.close()
                        path.unlink(missing_ok=True)
                        return None, "file bada hai"
                    fh.write(chunk)
        except Exception as e:
            path.unlink(missing_ok=True)
            return None, f"write fail: {e}"

    if written < 20 * 1024:
        path.unlink(missing_ok=True)
        return None, "file bahut chhoti / khaali"
    return path, ""


def _fetch_from_site(url: str, outdir: Path) -> Media | None:
    """seowebchecker se resolve + download (blocking)."""
    data = _swc_resolve(url)
    if not data:
        return None

    formats = data.get("formats") or []
    detected = platform_name(url)
    media = Media(
        title=(data.get("caption") or "").strip().split("\n")[0][:200],
        owner=(data.get("owner") or "").strip(),
        platform=detected if detected != "Video" else ((data.get("media_type") or "").strip() or "Video"),
        duration=duration_seconds(data.get("duration")),
        thumbnail=(data.get("thumbnail") or "").strip(),
        source="site",
    )
    if not formats:
        return None

    candidates, oversize = _pick_candidates(formats, MAX_BYTES)
    best_link = (candidates[0] if candidates else oversize or formats[0]).get("url", "")

    reasons: list[str] = []
    too_big = False
    for fmt in candidates:
        link = fmt["url"]
        # YouTube ke googlevideo links sirf site ke server IP par chalte hain
        if "googlevideo.com" in link:
            reasons.append("ip-locked")
            continue
        path, reason = _direct_download(link, outdir, MAX_BYTES)
        if path:
            media.path = path
            return media
        if reason == "file bada hai":
            too_big = True
        reasons.append(reason)
        log.info("site download fail (%s): %s", reason, url)

    if not candidates and oversize:
        too_big = True

    # Kuch bhi download nahi hua -> user ko direct link de sakte hain
    media.fallback_url = best_link
    media.too_big = too_big
    media.note = "; ".join(dict.fromkeys(r for r in reasons if r))
    return media


# ---------- 3. Fallback: yt-dlp ----------
def _fetch_with_ytdlp(url: str, outdir: Path) -> Media | None:
    import yt_dlp

    uid = uuid.uuid4().hex[:8]
    ydl_opts = {
        # Pehle single (progressive) mp4 try karo - ffmpeg ki zarurat nahi padti
        "format": (
            "b[ext=mp4][height<=720]"
            "/b[height<=720]"
            "/bv*[ext=mp4][height<=720]+ba"
            "/bv*[height<=720]+ba"
            "/b"
        ),
        "outtmpl": str(outdir / f"{uid}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "max_filesize": MAX_BYTES,
        "retries": 2,
        "socket_timeout": 30,
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info))
            if not path.exists():
                files = sorted(outdir.glob(f"{uid}.*"), key=lambda p: p.stat().st_mtime)
                path = files[-1] if files else None
    except Exception as e:
        log.warning("yt-dlp fail %s : %s", url, e)
        return None

    if not path or not path.exists() or path.stat().st_size > MAX_BYTES:
        return None

    return Media(
        path=path,
        title=(info.get("title") or "")[:200],
        owner=(info.get("uploader") or info.get("channel") or "").strip(),
        platform=info.get("extractor_key") or platform_name(url),
        duration=int(info.get("duration") or 0),
        thumbnail=info.get("thumbnail") or "",
        source="yt-dlp",
        fallback_url=info.get("webpage_url") or url,
    )


# ---------- 4. Ek link ka pura kaam ----------
async def fetch_media(url: str, outdir: Path) -> Media | None:
    loop = asyncio.get_running_loop()
    media: Media | None = None

    if DOWNLOAD_SOURCE in ("auto", "seowebchecker", "site"):
        media = await loop.run_in_executor(None, _fetch_from_site, url, outdir)
        if media and media.path:
            log.info("ok (site) %s -> %s", url, media.path.name)
            return media
        if DOWNLOAD_SOURCE != "auto":
            return media  # user ne sirf site mangai hai

    if DOWNLOAD_SOURCE in ("auto", "ytdlp", "yt-dlp"):
        media2 = await loop.run_in_executor(None, _fetch_with_ytdlp, url, outdir)
        if media2 and media2.path:
            log.info("ok (yt-dlp) %s -> %s", url, media2.path.name)
            return media2

    return media if media and (media.fallback_url or media.note) else None


def _thumb_file(url: str, outdir: Path) -> Path | None:
    """Thumbnail local save karo (Telegram ko dene ke liye). Fail ho to chhod do."""
    if not url.lower().startswith("http"):
        return None
    try:
        r = requests.get(url, headers={"User-Agent": MEDIA_UA}, timeout=15)
        if r.status_code != 200 or not r.content or len(r.content) > 2 * 1024 * 1024:
            return None
        if not r.headers.get("Content-Type", "").startswith("image/"):
            return None
        path = outdir / "thumb.jpg"
        path.write_bytes(r.content)
        return path
    except Exception:
        return None


def build_caption(media: Media, user_name: str) -> str:
    bits = [f"🎬 {media.platform}"]
    if media.owner:
        bits.append(f"@{media.owner.lstrip('@')}" if " " not in media.owner else media.owner)
    bits.append(f"By {user_name}")
    return " | ".join(bits)


# ---------- 5. Handlers ----------
HELP_TEXT = (
    "👋 Namaste! Main Link-to-Video Bot hun.\n\n"
    "Koi bhi video link bhejo — main use seowebchecker.com ke video downloader se "
    "download karke yahin bhej dunga ▶️\n"
    "Instagram Reel, YouTube, TikTok, Facebook, X, Vimeo, Reddit… 1000+ sites\n\n"
    "• Private chat me direct kaam karta hun\n"
    "• Group me: mujhe ADMIN banao + Delete Messages ON karo,\n"
    "  taaki link wala message delete karke video aa jaye\n\n"
    f"⚙️ Source: seowebchecker.com video downloader (site-only)\n"
    f"📦 Max size: {MAX_FILE_MB:.0f} MB (Telegram limit)\n\n"
    "Commands:\n/start - ye help\n/help - ye help\n/id - chat id dekho"
)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_cmd(update, context)


async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Chat ID: `{update.effective_chat.id}`", parse_mode="Markdown"
    )


def is_allowed(chat_id: int, chat_type: str) -> bool:
    if chat_type == "private":
        return True
    if not ALLOWED_GROUP_IDS:
        return True
    return chat_id in ALLOWED_GROUP_IDS


REASON_TEXT = {
    "ip-locked": "YouTube ka link sirf site ke server se chalta hai",
    "file bada hai": f"video {MAX_FILE_MB:.0f}MB se bada hai",
    "html aaya": "site ne video ke bajaye page bheja",
    "file bahut chhoti / khaali": "khaali file aayi",
}


def _pretty_reason(note: str) -> str:
    if not note:
        return ""
    parts = []
    for chunk in note.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        key = next((k for k in REASON_TEXT if chunk.startswith(k)), None)
        if key:
            parts.append(REASON_TEXT[key])
        elif chunk.startswith("http"):
            parts.append(f"site error ({chunk})")
        else:
            parts.append(chunk)
    return ", ".join(dict.fromkeys(parts))


async def _send_fallback_message(msg, media: Media | None, url: str, name: str):
    """Download na ho paye to user ko saaf message + direct link."""
    reason = _pretty_reason(media.note if media else "") or "private account / link support nahi / site busy"
    if media and media.fallback_url and media.too_big:
        text = (
            f"📥 {name}, ye video {MAX_FILE_MB:.0f}MB se bada hai — Telegram pe nahi bhej sakta.\n"
            f"Direct download link (browser me kholo):\n{media.fallback_url}"
        )
    elif media and media.fallback_url:
        text = (
            f"⚠️ {name}, video mil gaya par download nahi ho paya ({reason}).\n"
            f"Direct link try karo:\n{media.fallback_url}"
        )
    else:
        text = (
            f"❌ {name}, ye video nahi mil paya.\n"
            f"Reason: {reason}\n🔗 {url}"
        )
    try:
        await msg.reply_text(text[:4000], disable_web_page_preview=True)
    except Exception:
        pass


async def link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not (msg.text or msg.caption):
        return

    chat = update.effective_chat
    if chat and not is_allowed(chat.id, chat.type):
        return

    urls = find_links(msg.text or msg.caption or "")
    if not urls:
        return

    url = urls[0]
    plat = platform_name(url)
    user = msg.from_user
    name = (
        f"@{user.username}"
        if user and user.username
        else (user.first_name if user else "Someone")
    )

    try:
        await context.bot.send_chat_action(chat_id=msg.chat_id, action=ChatAction.UPLOAD_VIDEO)
    except Exception:
        pass

    status = None
    try:
        status = await msg.reply_text(
            f"⏳ {plat} site se download ho raha hai… thoda ruko {name}\n"
            f"🔗 {url}",
            disable_web_page_preview=True,
        )
    except Exception:
        pass

    async with DL_SEMAPHORE:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp)
            started = time.time()
            media = await fetch_media(url, outdir)
            elapsed = time.time() - started

            if not media or not media.path:
                if status:
                    try:
                        await status.delete()
                    except Exception:
                        pass
                await _send_fallback_message(msg, media, url, name)
                return

            if plat != "Video":
                media.platform = plat
            elif not media.platform or media.platform.lower() == "generic":
                media.platform = "Video"
            caption = build_caption(media, name)

            thumb = _thumb_file(media.thumbnail, outdir) if media.thumbnail else None
            is_audio = media.path.suffix in (".mp3", ".m4a")

            # Video pehle bhejo, delete baad me (taaki fail ho to link bacha rahe)
            last_err: Exception | None = None
            sent = False
            for use_thumb in ([thumb, None] if thumb else [None]):
                try:
                    await context.bot.send_chat_action(
                        chat_id=msg.chat_id,
                        action=ChatAction.UPLOAD_VOICE if is_audio else ChatAction.UPLOAD_VIDEO,
                    )
                    with open(media.path, "rb") as fh:
                        if is_audio:
                            await context.bot.send_audio(
                                chat_id=msg.chat_id,
                                audio=fh,
                                title=media.title or None,
                                performer=media.owner or None,
                                duration=media.duration or None,
                                caption=caption,
                                thumbnail=use_thumb,
                            )
                        else:
                            await context.bot.send_video(
                                chat_id=msg.chat_id,
                                video=fh,
                                caption=caption,
                                duration=media.duration or None,
                                supports_streaming=True,
                                thumbnail=use_thumb,
                            )
                    sent = True
                    break
                except Exception as e:  # thumbnail galat ho to bina thumb retry
                    last_err = e
                    log.warning("send fail (thumb=%s): %s", bool(use_thumb), e)

            if sent:
                log.info(
                    "sent %s | %s | %s | %.1fs",
                    plat,
                    human_size(media.path.stat().st_size),
                    media.source,
                    elapsed,
                )
                # Ab link wala message delete karo (bot admin ho to)
                try:
                    await msg.delete()
                except Exception as e:
                    log.warning("delete fail (bot admin + Delete Messages ON?): %s", e)
            else:
                try:
                    await context.bot.send_message(
                        chat_id=msg.chat_id,
                        text=f"❌ Video bhejne me error: {last_err}\n🔗 {url}",
                        disable_web_page_preview=True,
                    )
                except Exception:
                    pass
            if status:
                try:
                    await status.delete()
                except Exception:
                    pass


# ---------- 6. Main ----------
def _start_health_server():
    """Render/Koyeb health-check: chhota HTTP server."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"OK - reel bot alive ({DOWNLOAD_SOURCE})".encode())

        def log_message(self, *a):
            pass

    def _serve():
        try:
            HTTPServer(("0.0.0.0", PORT), Health).serve_forever()
        except Exception as e:
            log.warning("health server band: %s", e)

    threading.Thread(target=_serve, daemon=True).start()


def main():
    import sys as _sys

    try:
        _sys.stdout.reconfigure(encoding="utf-8")
        _sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        print("❌ BOT_TOKEN nahi mila!")
        print("   1. @BotFather se token lo")
        print("   2. .env.example ko .env naam se copy karo")
        print("   3. .env me BOT_TOKEN=... likho")
        print("   4. phir: python bot.py")
        raise SystemExit(1)

    _start_health_server()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("id", id_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, link_handler))
    app.add_handler(MessageHandler(filters.CAPTION & ~filters.COMMAND, link_handler))

    print(f"✅ Bot chal raha hai... source={DOWNLOAD_SOURCE} | max={MAX_FILE_MB:.0f}MB")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
