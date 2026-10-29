# 🎬 Telegram Link → Video Bot

**Engine:** [seowebchecker.com video downloader](https://seowebchecker.com/video-downloader/from-any-url) — **site-only** (koi doosra downloader nahi).

Group me koi bhi video link bhejo →
Bot us link ko site par daalta hai → video download karke **GC me upload** karta hai (direct PLAY ▶️) + link wala message **DELETE** kar deta hai.

## Kaam kaise karta hai
```
User link  →  Bot → seowebchecker API (resolve)  →  direct video URL  →  download  →  Telegram GC me video
```
- Website ka API: `POST https://seowebchecker.com/video-downloader/api/download` (field `igUrl`)
- Har link isi site par jaata hai — Instagram, YouTube, TikTok, Facebook, X, Vimeo, Reddit, Dailymotion, koi bhi direct video URL…
- Site fail ho jaye to bot usi format ka **direct download link** user ko bhej deta hai (48MB se bada video bhi isi tarah)
- Yt-dlp code backup ke roop me pada hai par **default me band hai** (`DOWNLOAD_SOURCE=seowebchecker`)

## 1. Bot Token lo (2 min)
1. Telegram me `@BotFather` kholo
2. `/newbot` bhejo → naam do → username do (end me `bot` hona chahiye)
3. Jo token milega usko copy karo

## 2. Bot chalao (PC / Laptop)
```bash
pip install -r requirements.txt

# Windows:
copy .env.example .env
# .env kholo, BOT_TOKEN=... me apna token paste karo

python bot.py
```
> Windows pe YouTube ke liye **ffmpeg** chahiye (merge ke liye): `winget install ffmpeg`
> Docker/Koyeb/Render image me ffmpeg pehle se hai.

## 3. Group me lagao (IMPORTANT)
1. Bot ko group me **Add** karo
2. **Bot ko ADMIN banao** + ✅ `Delete Messages` permission ON karo
   - Nahi to bot link delete nahi kar payega (video phir bhi bhejega)
3. Test: koi bhi video link bhejo → video aa jayega

## 4. Env variables
| Variable | Default | Matlab |
|---|---|---|
| `BOT_TOKEN` | — | BotFather token (must) |
| `ALLOWED_GROUP_IDS` | khali | Sirf in group ids me chalega (comma se alag). Khali = sab jagah |
| `DOWNLOAD_SOURCE` | `seowebchecker` | `seowebchecker` = sirf ye site (default) / `auto` = fail par yt-dlp / `ytdlp` |
| `MAX_FILE_MB` | `48` | Telegram limit ~50MB, safe side 48 |
| `MAX_CONCURRENT` | `3` | Ek saath kitne download |
| `PORT` | `8000` | Health-check server port |

## 5. Free me 24x7 chalana hai? (Hosting)
- **Koyeb / Render / Railway / VPS**: ye folder upload karo
- Start command: `python bot.py`
- Env var: `BOT_TOKEN` (+ chahe to `ALLOWED_GROUP_IDS`)
- Koyeb guide: [`DEPLOY_KOYEB.md`](DEPLOY_KOYEB.md)

## Problem?
| Problem | Fix |
|---|---|
| `BOT_TOKEN nahi mila` | `.env` banaya? Token sahi paste kiya? |
| `link delete nahi ho raha` | Bot Admin hai? `Delete Messages` ON hai? |
| `video nahi mil paya` | Private account, ya site busy. Log me reason dikhega |
| `video 48MB se bada` | Bot direct link bhej dega — browser se download kar lo |
| YouTube fail | Site ke YouTube links sirf unke server IP par chalte hain → `DOWNLOAD_SOURCE=auto` karo (yt-dlp fallback ON) |

## Commands
- `/start` `/help` — help
- `/id` — chat id (group allowlist ke liye)

## Note
Sirf wahi content download karo jiska aapko haq hai (apna content, public domain, ya permission wala).
Copyright / platform terms ka zimmedar user hai.
