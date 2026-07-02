# -*- coding: utf-8 -*-
"""直播自動精華＋懶人包：偵測剛結束的直播 VOD →
 ・Gemini 讀逐字稿 → 本場摘要（懶人包）
 ・聊天爆量時刻 → 熱門時間軸
合併貼到 Discord。跑在 GitHub Actions，每支只發一次。全程免費。"""
import os, sys, io, json, re, urllib.request, html as _html, subprocess, glob, tempfile, shutil, time
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if shutil.which("yt-dlp") is None:   # 自動裝 yt-dlp（不用改 workflow）
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "yt-dlp"], timeout=240)
from chat_downloader import ChatDownloader

CH = os.environ["YT_CHANNEL_ID"]
WH = os.environ["WEBHOOK_HL"]
GKEY = os.environ.get("GEMINI_API_KEY", "")
STATE = "highlights_state.json"
WIN = 30; TOPN = 8

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (enishi-notify)"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")

def post(content):
    body = json.dumps({"content": content[:1990]}).encode()
    req = urllib.request.Request(WH, data=body, headers={
        "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (enishi-notify)"})
    urllib.request.urlopen(req, timeout=30)

def fmt(sec):
    sec = int(sec); h = sec // 3600; m = (sec % 3600) // 60; s = sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def fetch_transcript(vid):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception:
        return None
    langs = ['ja', 'zh-Hant', 'zh-Hans', 'zh', 'en']
    try:  # 新版 API
        fetched = YouTubeTranscriptApi().fetch(vid, languages=langs)
        return " ".join(getattr(s, 'text', '') for s in fetched)
    except Exception:
        pass
    try:  # 舊版 API
        segs = YouTubeTranscriptApi.get_transcript(vid, languages=langs)
        return " ".join(s['text'] for s in segs)
    except Exception as e:
        print("transcript_api 失敗:", str(e)[:100])
    return fetch_transcript_ytdlp(vid)   # 機房 IP 被擋 → 改用 yt-dlp 自動字幕

def fetch_transcript_ytdlp(vid):
    """yt-dlp 抓自動字幕（機房 IP 可靠）→ 解析 vtt 純文字。"""
    try:
        tmp = tempfile.mkdtemp()
        subprocess.run(["yt-dlp", "-q", "--no-warnings", "--skip-download",
                        "--write-auto-sub", "--write-sub", "--sub-lang", "ja,zh-Hant,zh,en",
                        "--sub-format", "vtt", "-o", f"{tmp}/s.%(ext)s",
                        f"https://youtu.be/{vid}"], capture_output=True, text=True, timeout=180)
        vtts = glob.glob(f"{tmp}/*.vtt")
        if not vtts:
            print("yt-dlp 也無字幕"); return None
        seen = set(); words = []
        for line in open(vtts[0], encoding="utf-8"):
            line = line.strip()
            if not line or "-->" in line or line.startswith(("WEBVTT", "Kind:", "Language:")):
                continue
            line = re.sub(r"<[^>]+>", "", line)
            if line and line not in seen:
                seen.add(line); words.append(line)
        txt = " ".join(words)
        print(f"yt-dlp 字幕 {len(txt)} 字")
        return txt or None
    except Exception as e:
        print("yt-dlp 字幕失敗:", str(e)[:100]); return None

def gemini_summary(text):
    if not GKEY or not text:
        return None
    prompt = ("你是緣結直播的懶人包小編。根據以下直播逐字稿，用繁體中文寫一段「本場重點摘要」，"
              "150 字內、口語、像朋友轉述、不分行不條列不加前綴。只寫實際發生的內容，嚴禁捏造。\n\n逐字稿：\n" + text[:200000])
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.4, "maxOutputTokens": 400}}).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GKEY}"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=120).read())
        return r["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print("Gemini 摘要失敗:", str(e)[:120]); return None

try:
    state = json.load(open(STATE, encoding="utf-8"))
except Exception:
    state = {}

# RSS 抓最新影片（機房 IP 偶發 404 → 重試幾次；RSS 不含未來排程的佔位直播，剛好）
xml = None
for attempt in range(4):
    try:
        xml = get(f"https://www.youtube.com/feeds/videos.xml?channel_id={CH}"); break
    except Exception as ex:
        print(f"RSS 第{attempt+1}次失敗:", str(ex)[:60]); time.sleep(3)
if not xml:
    print("RSS 取不到，等下次重試"); sys.exit(0)
ent = re.search(r"<entry>(.*?)</entry>", xml, re.S)
if not ent:
    print("沒有影片"); sys.exit(0)
e = ent.group(1)
vid = re.search(r"<yt:videoId>([\w-]+)</yt:videoId>", e).group(1)
tm = re.search(r"<title>(.*?)</title>", e)
title = _html.unescape(tm.group(1)) if tm else ""

if state.get("posted_video") == vid:
    print("已發過:", vid); sys.exit(0)

url = f"https://www.youtube.com/watch?v={vid}"
# yt-dlp live_status 判斷（機房 IP 爬網頁抓不到 isLiveContent）
try:
    r = subprocess.run(["yt-dlp", "-q", "--no-warnings", "--skip-download", "--print", "%(live_status)s",
                        f"https://youtu.be/{vid}"], capture_output=True, text=True, timeout=120)
    ls = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
except Exception as ex:
    print("live_status err:", ex); ls = ""
print("latest =", vid, "| live_status =", ls)
if ls == "is_live":
    print("還在直播中，等播完"); sys.exit(0)
if ls not in ("was_live", "post_live"):   # 一般上片(非直播) → 略過精華
    print(f"不是直播(live_status={ls})，略過精華"); state["posted_video"] = vid
    json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False); sys.exit(0)

# 已結束的直播 → 產懶人包 + 時間軸
summary = gemini_summary(fetch_transcript(vid))

bins = defaultdict(int); samples = defaultdict(list); n = 0
try:
    for m in ChatDownloader().get_chat(url):
        t = m.get("time_in_seconds")
        if t is None or t < 0:
            continue
        b = int(t // WIN); bins[b] += 1
        msg = (m.get("message") or "").strip()
        if msg and len(samples[b]) < 3:
            samples[b].append(msg)
        n += 1
except Exception as ex:
    print("抓聊天失敗:", str(ex)[:120])

if not summary and n == 0:
    print("摘要和聊天都還沒好，等下次重試"); sys.exit(0)

parts = ["# 🌟 緣結直播・懶人包 🎀", f"**{title}**", ""]
if summary:
    parts += ["📝 " + summary, ""]
if n > 0:
    parts.append("🔥 **熱門時間軸**")
    ranked = sorted(bins.items(), key=lambda kv: kv[1], reverse=True)[:TOPN]
    for b, c in sorted(ranked, key=lambda kv: kv[0]):
        start = b * WIN
        samp = " / ".join(samples[b])[:40]
        parts.append(f"🔥 [`{fmt(start)}`](<{url}&t={start}s>) ・ {c} 則" + (f"　{samp}" if samp else ""))
    parts.append(f"（共 {n} 則聊天 ・ 爆量＝精彩，點時間跳轉）")
post("\n".join(parts))
state["posted_video"] = vid
json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
print(f"✅ 已發懶人包+精華 {vid}（摘要:{bool(summary)} 聊天:{n}）")
