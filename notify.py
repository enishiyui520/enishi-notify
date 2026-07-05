# -*- coding: utf-8 -*-
"""緣結 YouTube 通知：用公開 RSS 偵測新片、用 /live 頁偵測開台 → 發到 Discord Webhook。
跑在 GitHub Actions（免費），狀態存 state.json。第一次跑只記錄不發（避免洗舊內容）。"""
import os, sys, json, re, html, urllib.request, subprocess, shutil

# 確保 yt-dlp 可用（不改 workflow 就自動裝；workflow 本來每次就會 pip install，成本相同）
if shutil.which("yt-dlp") is None:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "yt-dlp"], timeout=240)

# YT_CHANNEL_ID 可為「UCxxx」或「UCxxx|APIKEY」(把 Data API key 夾帶進來，免改 workflow)
_cid = os.environ["YT_CHANNEL_ID"]
CH = _cid.split("|")[0].strip()
YT_KEY = (os.environ.get("YT_API_KEY", "").strip()
          or (_cid.split("|", 1)[1].strip() if "|" in _cid else ""))
WH_LIVE = os.environ["WEBHOOK_LIVE"]
WH_UPLOAD = os.environ["WEBHOOK_UPLOAD"]
PING_LIVE = os.environ.get("PING_LIVE", "").strip()
STATE = "state.json"

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (enishi-notify)"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")

def post(webhook, content):
    body = json.dumps({"content": content, "allowed_mentions": {"parse": ["roles"]}}).encode()
    req = urllib.request.Request(webhook, data=body, headers={
        "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (enishi-notify)"})
    urllib.request.urlopen(req, timeout=30)

try:
    state = json.load(open(STATE, encoding="utf-8"))
except Exception:
    state = {}
first_run = not state
sys.exit(0)   # ← 開台/新片偵測已改由 enishi-cron worker(notifyCheck) 專責、更可靠；此腳本跳過避免重複通知

# --- 開台偵測 ---
# 首選 YouTube Data API（機房 IP 也可靠）；沒 key 才退回 yt-dlp（機房常被擋）
live_now = None
if YT_KEY:
    try:
        import yt_api
        live_now = yt_api.find_live(CH, YT_KEY)
        print("live check (Data API):", live_now or "(no live)")
    except Exception as e:
        print("Data API live check err:", str(e)[:120])
else:
    try:
        r = subprocess.run(["yt-dlp", "-q", "--no-warnings", "--skip-download", "--playlist-items", "1",
                            "--print", "%(id)s\t%(live_status)s",
                            f"https://www.youtube.com/channel/{CH}/live"],
                           capture_output=True, text=True, timeout=120)
        for line in r.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) == 2 and parts[1] == "is_live":
                live_now = parts[0]; break
        print("live check (yt-dlp fallback):", r.stdout.strip()[:120] or "(no live)")
    except Exception as e:
        print("live check err:", e)

if live_now:
    if state.get("live_video") != live_now:
        if not first_run:
            ping = (PING_LIVE + " ") if PING_LIVE else ""
            post(WH_LIVE, f"{ping}🔴 **緣結開台了！** 快來看～ 🎀\nhttps://www.youtube.com/watch?v={live_now}")
            print("LIVE posted", live_now)
        state["live_video"] = live_now
else:
    state["live_video"] = None

# --- 新片偵測（RSS）---
try:
    xml = get(f"https://www.youtube.com/feeds/videos.xml?channel_id={CH}")
    entries = re.findall(r"<entry>(.*?)</entry>", xml, re.S)
    if entries:
        e = entries[0]
        vid = re.search(r"<yt:videoId>([\w-]+)</yt:videoId>", e).group(1)
        tm = re.search(r"<title>(.*?)</title>", e)
        title = html.unescape(tm.group(1)) if tm else ""
        if state.get("last_video") != vid:
            if not first_run and vid != live_now:   # live 的不重複發
                post(WH_UPLOAD, f"🎬 **緣結上新片了！** 🎀\n{title}\nhttps://www.youtube.com/watch?v={vid}")
                print("UPLOAD posted", vid)
            state["last_video"] = vid
except Exception as e:
    print("upload check err:", e)

json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
print("done. first_run =", first_run, "| state =", state)
