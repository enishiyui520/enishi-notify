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

# YT_CHANNEL_ID 可為「UCxxx」或「UCxxx|APIKEY」(夾帶 Data API key，免改 workflow)
_cid = os.environ["YT_CHANNEL_ID"]
CH = _cid.split("|")[0].strip()
YT_KEY = (os.environ.get("YT_API_KEY", "").strip()
          or (_cid.split("|", 1)[1].strip() if "|" in _cid else ""))
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

# 找最近一支「已結束直播」。首選 YouTube Data API（機房 IP 可靠）；沒 key 退回 yt-dlp
vid = title = ""
if YT_KEY:
    try:
        import yt_api
        vid, title = yt_api.find_latest_ended_stream(CH, YT_KEY)
        print("latest ended stream (Data API):", vid, "|", (title or "")[:40])
    except Exception as ex:
        print("Data API 查直播失敗:", str(ex)[:120])
if not vid:   # 退回 yt-dlp：flat 列 ID + --ignore-errors 批次查 live_status
    ids = []
    try:
        r = subprocess.run(["yt-dlp", "-q", "--no-warnings", "--flat-playlist", "-I", "1:6", "--print", "%(id)s",
                            f"https://www.youtube.com/channel/{CH}/streams"],
                           capture_output=True, text=True, timeout=120)
        ids = [x for x in r.stdout.strip().splitlines() if x]
    except Exception as ex:
        print("列出直播失敗:", str(ex)[:100])
    try:
        if ids:
            r = subprocess.run(["yt-dlp", "-q", "--no-warnings", "--ignore-errors", "--skip-download",
                                "--print", "%(id)s\t%(live_status)s\t%(title)s", *ids],
                               capture_output=True, text=True, timeout=220)
            for line in r.stdout.strip().splitlines():
                p = line.split("\t")
                if len(p) >= 2 and p[1] in ("was_live", "post_live"):
                    vid, title = p[0], (p[2] if len(p) > 2 else ""); break
    except Exception as ex:
        print("yt-dlp 查直播狀態失敗:", str(ex)[:100])
if not vid:
    print("目前沒有已結束的直播（可能還在直播中或只有排程/機房被擋），略過"); sys.exit(0)

if state.get("posted_video") == vid:
    print("已發過:", vid); sys.exit(0)

url = f"https://www.youtube.com/watch?v={vid}"
print("處理直播:", vid, "|", (title or "")[:40])

# 已結束的直播 → 產懶人包 + 時間軸
summary = gemini_summary(fetch_transcript(vid))

def yt_live_chat(_vid):
    """用 yt-dlp 下載 live chat replay（住宅 IP 可靠、chat_downloader 已壞）→ yield {time_in_seconds, message}。"""
    d = tempfile.mkdtemp()
    try:
        subprocess.run([sys.executable, "-m", "yt_dlp", "-q", "--no-warnings", "--skip-download",
                        "--write-subs", "--sub-langs", "live_chat",
                        "-o", os.path.join(d, "%(id)s.%(ext)s"),
                        f"https://www.youtube.com/watch?v={_vid}"], timeout=600)
        fs = glob.glob(os.path.join(d, "*.live_chat.json"))
        if not fs:
            return
        for line in open(fs[0], encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            rc = o.get("replayChatItemAction") or {}
            off = rc.get("videoOffsetTimeMsec")
            if off is None:
                continue
            ts = int(off) / 1000.0
            for a in rc.get("actions", []):
                item = (a.get("addChatItemAction") or {}).get("item") or {}
                r = item.get("liveChatTextMessageRenderer")
                if not r:
                    continue
                runs = (r.get("message") or {}).get("runs", [])
                mtext = "".join(run.get("text", "") for run in runs).strip()
                yield {"time_in_seconds": ts, "message": mtext}
    finally:
        shutil.rmtree(d, ignore_errors=True)

bins = defaultdict(int); samples = defaultdict(list); n = 0
try:
    for m in yt_live_chat(vid):
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
