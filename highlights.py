# -*- coding: utf-8 -*-
"""直播自動精華＋懶人包：偵測剛結束的直播 VOD →
 ・Gemini 讀逐字稿 → 本場摘要（懶人包）
 ・聊天爆量時刻 → 熱門時間軸
合併貼到 Discord。跑在 GitHub Actions，每支只發一次。全程免費。"""
import os, sys, io, json, re, urllib.request, html as _html, subprocess, glob, tempfile, shutil, time
if os.name == "nt":  # Windows 本機排程用 pythonw 時，讓所有子程序(yt-dlp)不彈黑視窗
    _sprun = subprocess.run
    def _run_nw(*a, **k):
        k["creationflags"] = k.get("creationflags", 0) | 0x08000000  # CREATE_NO_WINDOW
        return _sprun(*a, **k)
    subprocess.run = _run_nw
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

def _post_one(content):
    body = json.dumps({"content": content[:1990]}).encode()
    req = urllib.request.Request(WH, data=body, headers={
        "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (enishi-notify)"})
    urllib.request.urlopen(req, timeout=30)

def post(content):
    # 超過 1900 字就依行分段多發（避免被截斷）
    buf = ""
    for line in content.split("\n"):
        if len(buf) + len(line) + 1 > 1900:
            if buf: _post_one(buf); time.sleep(0.6)
            buf = line
        else:
            buf = (buf + "\n" + line) if buf else line
    if buf: _post_one(buf)

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

def gemini_recap(transcript, chat_sample, title):
    """回 {summary, learned[]}。有逐字稿用逐字稿；沒有就用聊天室推測。"""
    if not GKEY:
        return {}
    ctx = ("背景：緣結是一位中日混雜的日本 VTuber（會中文也會日文、常常中日夾雜），觀眾中日都有。"
           f"這場直播標題：{title}。**請完全依照下面的逐字稿／聊天內容，判斷她今天實際在做什麼**（可能是雜談、歌回、玩某款遊戲、閒聊…）。"
           "絕對不要預設任何遊戲或主題、不要腦補沒發生的事——標題有『歌』多半是歌回、有明確遊戲名才是玩該遊戲，一切以實際內容為準。"
           "逐字稿與聊天可能中日混雜，這是正常的、不要當亂碼。")
    if transcript:
        src = "【逐字稿（緣結說的話，可能中日夾雜）】\n" + transcript[:120000]
    else:
        src = "（這場沒抓到逐字稿，改用聊天室內容推測本場氛圍與內容）\n【聊天室片段】\n" + (chat_sample or "")[:20000]
    prompt = (ctx + "\n\n只輸出 JSON（繁體中文），格式：\n"
              '{"summary":"本場總結，150字內、口語像朋友轉述、只寫實際發生的、嚴禁捏造",'
              '"learned":["這場學到/出現的重點，3~5條，例如日文詞或用法、遊戲劇情、雙語有趣點、梗，每條15字內"]}\n\n'
              + src)
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.4, "maxOutputTokens": 900,
                                            "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}}).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GKEY}"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=120).read())
        return json.loads(r["candidates"][0]["content"]["parts"][0]["text"].strip())
    except Exception as e:
        print("Gemini recap 失敗:", str(e)[:150]); return {}

try:
    state = json.load(open(STATE, encoding="utf-8"))
except Exception:
    state = {}

# 找最近一支「已結束直播」。首選 YouTube Data API（機房 IP 可靠）；沒 key 退回 yt-dlp
vid = title = ""
if os.environ.get("HL_VID"):   # 指定影片重發（修正版用）
    vid = os.environ["HL_VID"]
    try:
        import yt_api
        st_ = yt_api.video_status([vid], YT_KEY).get(vid, {}); title = st_.get("title", "")
    except Exception: pass
    print("HL_VID 指定重發:", vid, "|", (title or "")[:40])
elif YT_KEY:
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

if state.get("posted_video") == vid and not os.environ.get("HL_VID"):
    print("已發過:", vid); sys.exit(0)

url = f"https://www.youtube.com/watch?v={vid}"
print("處理直播:", vid, "|", (title or "")[:40])

# 已結束的直播 → 產懶人包（總結+今天學到什麼）+ 時間軸

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

bins = defaultdict(int); samples = defaultdict(list); chat_all = []; n = 0
try:
    for m in yt_live_chat(vid):
        t = m.get("time_in_seconds")
        if t is None or t < 0:
            continue
        b = int(t // WIN); bins[b] += 1
        msg = (m.get("message") or "").strip()
        if msg and len(samples[b]) < 3:
            samples[b].append(msg)
        if msg and (n % 8 == 0) and len(chat_all) < 400:   # 抽樣給 Gemini 當背景
            chat_all.append(msg)
        n += 1
except Exception as ex:
    print("抓聊天失敗:", str(ex)[:120])

recap = gemini_recap(fetch_transcript(vid), " / ".join(chat_all), title)
summary = recap.get("summary"); learned = recap.get("learned") or []

if not summary and n == 0:
    fk = "fail_" + vid
    state[fk] = int(state.get(fk, 0)) + 1
    if state[fk] >= 3:   # 連續 3 次抓不到 → 放棄這支、防 yt-dlp+Gemini 每次 run 重試迴圈燒錢
        state["posted_video"] = vid; state.pop(fk, None)
        json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
        print("連續 3 次失敗、放棄這支 VOD"); sys.exit(0)
    json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"摘要和聊天都還沒好（第 {state[fk]} 次），等下次重試"); sys.exit(0)

import datetime as _dt
_today = (_dt.datetime.utcnow() + _dt.timedelta(hours=8)).strftime("%Y/%m/%d")
parts = ["# 🌟 緣結直播・懶人包 🎀", f"**{title}**", f"📅 {_today}", f"▶️ **完整回放**：{url}", ""]   # 連結一律標示(聊天抓失敗沒時間軸時也要有)
if summary:
    parts += ["📝 **本場總結**", summary, ""]
if learned:
    parts += ["📚 **今天學到了什麼**"] + [f"・{x}" for x in learned[:5]] + [""]
if n > 0:
    parts.append("🔥 **熱門時間軸**")
    ranked = sorted(bins.items(), key=lambda kv: kv[1], reverse=True)[:TOPN]
    for b, c in sorted(ranked, key=lambda kv: kv[0]):
        start = b * WIN
        samp = " / ".join(samples[b])[:36]
        parts.append(f"🔥 [{fmt(start)}](<{url}&t={start}s>) ・ {c} 則" + (f"　{samp}" if samp else ""))
    parts.append(f"（共 {n} 則聊天 ・ 爆量＝精彩，點時間跳轉）")
post("\n".join(parts))
state["posted_video"] = vid
json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
print(f"✅ 已發懶人包+精華 {vid}（總結:{bool(summary)} 學到:{len(learned)} 聊天:{n}）")
