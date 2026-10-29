# Koyeb Free Deploy Guide (Hindi)

## 0. Token naya lo (IMPORTANT)
Purana token chat me leak ho gaya tha.
1. Telegram me `@BotFather` kholo
2. `/revoke` bhejo → apna bot select karo
3. Naya token copy karke rakho — ye kisi ko mat bhejo

## 1. GitHub repo banao
1. github.com → New repository → naam: `reel-link-bot` → Private → Create
2. Is folder `reel-link-to-video-bot` ki ye 5 files upload karo:
   - `bot.py`, `Dockerfile`, `requirements.txt`, `.gitignore`, `.dockerignore`
   - `.env` kabhi mat dalo (token leak ho jayega)

PowerShell se push karna hai to:
```powershell
cd "C:\Users\noubu\OneDrive\Documents\Default Project\reel-link-to-video-bot"
git init
git add bot.py Dockerfile requirements.txt .gitignore .dockerignore
git commit -m "reel bot for koyeb"
git branch -M main
git remote add origin https://github.com/TUMHARA_USERNAME/reel-link-bot.git
git push -u origin main
```

## 2. Koyeb me Service banao
1. koyeb.com → Sign up (GitHub se login) → **Create Service**
2. **Deploy from GitHub** → repo `reel-link-bot` → branch `main`
3. Builder: **Dockerfile** (default) — Dockerfile location: `./Dockerfile`
4. Instance type: **Free** (Eco Nano)
5. Region: **Singapore** (India ke liye sabse fast)
6. Port: `8000`, Health check: HTTP, Path: `/`
7. Environment variables (exact naam se):
   - `BOT_TOKEN` = BotFather wala NAYA token
   - `ALLOWED_GROUP_IDS` = `-1004451914143,-1004334916764`
   - `DOWNLOAD_SOURCE` = `auto` (pehle seowebchecker site, fail par yt-dlp)
8. **Deploy** dabao → Logs me `✅ Bot chal raha hai` dikhe to live hai

## 3. Group me test
1. Dono groups me bot ko Add → **Admin** banao → **Delete Messages** ON
2. Koi Insta Reel link bhejo → link delete + video aana chahiye
3. Na aaye to Koyeb → Service → Logs dekho, screenshot bhejo

## Koyeb Free limits
- Sleep nahi karta (Render jaisa band nahi hota)
- Monthly free hours fixed hain — 1 chhota bot aaram se chalता है
- Agar `Out of free quota` aaye to: purani unused service delete karo ya naya account / VPS lo
