# -*- coding: utf-8 -*-
"""直播自動精華：偵測到最新影片是「有聊天回放的直播 VOD」→ 抓聊天 → 找爆量時刻 →
熱門時間軸貼到 Discord。跑在 GitHub Actions，每支影片只發一次。聊天太少就跳過（等下次/不發）。"""
import os, sys, io, json, re, urllib.request
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from chat_downloader import ChatDownloader

CH = os.environ["YT_CHANNEL_ID"]
WH = os.environ["WEBHOOK_HL"]
STATE = "highlights_state.json"
WIN = 30        # 每 30 秒一格
TOPN = 8        # 取最熱 8 段
MIN_MSGS = 15   # 全場聊天少於這個就先不發（量太少不準）

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

try:
    state = json.load(open(STATE, encoding="utf-8"))
except Exception:
    state = {}

# 最新影片
xml = get(f"https://www.youtube.com/feeds/videos.xml?channel_id={CH}")
ent = re.search(r"<entry>(.*?)</entry>", xml, re.S)
if not ent:
    print("沒有影片"); sys.exit(0)
e = ent.group(1)
vid = re.search(r"<yt:videoId>([\w-]+)</yt:videoId>", e).group(1)
import html as _html
title = _html.unescape((re.search(r"<title>(.*?)</title>", e) or [None, ""]).group(1)) if re.search(r"<title>(.*?)</title>", e) else ""

if state.get("posted_video") == vid:
    print("已發過精華:", vid); sys.exit(0)

url = f"https://www.youtube.com/watch?v={vid}"
# 還在直播中就先別抓（即時聊天會串流卡住 workflow），等播完有 VOD 再抓
try:
    page = get(url)
    if '"isLiveNow":true' in page:
        print("還在直播中，等播完再抓"); sys.exit(0)
except Exception:
    pass
bins = defaultdict(int)
samples = defaultdict(list)
n = 0
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
    print("抓聊天失敗（可能還沒生成 VOD/聊天回放，稍後重試）:", str(ex)[:120]); sys.exit(0)

if n < MIN_MSGS:
    print(f"聊天太少（{n} 則），先不發、等下次"); sys.exit(0)

ranked = sorted(bins.items(), key=lambda kv: kv[1], reverse=True)[:TOPN]
ranked = sorted(ranked, key=lambda kv: kv[0])
lines = ["# 🌟 緣結直播・熱門時間軸 🎀", f"**{title}**", ""]
for b, c in ranked:
    start = b * WIN
    samp = " / ".join(samples[b])[:48]
    lines.append(f"🔥 [`{fmt(start)}`](<{url}&t={start}s>) ・ {c} 則" + (f"　{samp}" if samp else ""))
lines.append(f"\n（共 {n} 則聊天 ・ 訊息爆量＝精彩時刻，點時間跳轉）")
post("\n".join(lines))
state["posted_video"] = vid
json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
print(f"✅ 已發精華 {vid}（{n} 則聊天）")
