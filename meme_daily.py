# -*- coding: utf-8 -*-
"""今日最佳梗圖 + 梗圖王 → 只發到梗圖頻道（不進每日回顧）。
   用法: python meme_daily.py [YYYY-MM-DD 台灣日期]   不填=過去24h
   環境: BOT_TOKEN（要能在梗圖頻道發言）, GEMINI_API_KEY（視覺猜哏，可省）"""
import os, sys, io, json, time, base64, datetime, urllib.request, urllib.error
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

TOK = os.environ["BOT_TOKEN"]
GKEY = os.environ.get("GEMINI_API_KEY", "")
GUILD = "1518798030499877037"
MEME_CH = "1518812041220067419"
API = "https://discord.com/api/v10"
UA = "DiscordBot (https://enishi.dev, 1.0)"
IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
TW = datetime.timezone(datetime.timedelta(hours=8))

# ---- 時間窗 ----
if len(sys.argv) > 1:
    d = datetime.date.fromisoformat(sys.argv[1])
    lo = datetime.datetime(d.year, d.month, d.day, tzinfo=TW).astimezone(datetime.timezone.utc)
    hi = lo + datetime.timedelta(days=1)
    label = d.strftime("%m/%d")
else:
    hi = datetime.datetime.now(datetime.timezone.utc)
    lo = hi - datetime.timedelta(hours=24)
    label = (hi.astimezone(TW)).strftime("%m/%d")

def get(path):
    req = urllib.request.Request(API + path, headers={"Authorization": "Bot " + TOK, "User-Agent": UA})
    for _ in range(5):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try: time.sleep(min(float(json.loads(e.read().decode()).get("retry_after", 2)) + 0.5, 10))
                except Exception: time.sleep(3)
                continue
            return None
        except Exception:
            time.sleep(1)
    return None

def bot_post(ch, content):
    body = json.dumps({"content": content[:1990], "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(f"{API}/channels/{ch}/messages", data=body,
                                 headers={"Authorization": "Bot " + TOK, "Content-Type": "application/json", "User-Agent": UA})
    urllib.request.urlopen(req, timeout=30)

def explain_meme(img_url):
    if not GKEY:
        return ""
    try:
        raw = urllib.request.urlopen(urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
        if len(raw) > 4_000_000:
            return ""
        low = img_url.lower().split("?")[0]
        mime = "image/jpeg" if low.endswith((".jpg", ".jpeg")) else "image/gif" if low.endswith(".gif") else \
               "image/webp" if low.endswith(".webp") else "image/png"
        prompt = ("這是社群這天最多人按表情的梗圖。用繁體中文猜這張圖在玩什麼哏、為什麼好笑，2~3 句。"
                  "你只看得到圖、不知道當下語境，所以開頭要說明這是你的猜測。")
        body = json.dumps({"contents": [{"parts": [{"inline_data": {"mime_type": mime, "data": base64.b64encode(raw).decode()}}, {"text": prompt}]}],
                           "generationConfig": {"temperature": 0.6, "maxOutputTokens": 300, "thinkingConfig": {"thinkingBudget": 0}}}).encode()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GKEY}"
        r = json.loads(urllib.request.urlopen(urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}), timeout=60).read())
        return "".join(p.get("text", "") for p in r["candidates"][0]["content"].get("parts", [])).strip()
    except Exception as e:
        print("梗圖解讀失敗:", str(e)[:150]); return ""

# ---- 掃梗圖頻道（往回翻頁涵蓋整個時間窗）----
best = None
count = {}; name = {}
before = None
for _ in range(6):   # 最多 6 頁 = 600 則
    q = f"/channels/{MEME_CH}/messages?limit=100" + (f"&before={before}" if before else "")
    msgs = get(q)
    if not msgs:
        break
    stop = False
    for m in msgs:
        try:
            ts = datetime.datetime.fromisoformat(m["timestamp"])
        except Exception:
            continue
        if ts >= hi:
            continue
        if ts < lo:
            stop = True; continue
        au = m.get("author", {})
        if au.get("bot"):
            continue
        img = None
        for a in (m.get("attachments") or []):
            if (a.get("content_type") or "").startswith("image") or (a.get("filename") or "").lower().endswith(IMG_EXT):
                img = a.get("url"); break
        if not img:
            for e in (m.get("embeds") or []):
                if (e.get("image") or {}).get("url"):
                    img = e["image"]["url"]; break
        if not img:
            continue
        aid = au.get("id"); count[aid] = count.get(aid, 0) + 1
        name[aid] = au.get("global_name") or au.get("username") or "?"
        rc = sum(r.get("count", 0) for r in (m.get("reactions") or []))
        if best is None or rc > best["rc"]:
            best = {"rc": rc, "img": img, "jump": f"https://discord.com/channels/{GUILD}/{MEME_CH}/{m['id']}", "by": name[aid]}
    before = msgs[-1]["id"]
    if stop or len(msgs) < 100:
        break

if not count:
    print(f"{label} 梗圖區沒有圖，略過"); sys.exit(0)

lines = []
if best and best["rc"] > 0:
    lines.append(f"# 🏆 {label} 最佳梗圖 🎀")
    lines.append(f"由 **{best['by']}** 提供 ・ 被按 **{best['rc']}** 個表情 🔥")
    lines.append(best["jump"])
    ex = explain_meme(best["img"])
    if ex:
        lines.append(f"🤖 {ex}")
    lines.append("")
king = max(count.items(), key=lambda kv: kv[1])
lines.append(f"## 🎨 {label} 梗圖王")
lines.append(f"感謝 **{name[king[0]]}** 這天貢獻 **{king[1]}** 張梗圖，讓大家笑不停 🎉")
bot_post(MEME_CH, "\n".join(lines))
print(f"✅ 已發 {label} 梗圖榜（最佳:{best['rc'] if best else 0}表情 by {best['by'] if best else '-'} ・ 梗圖王 {name[king[0]]} {king[1]}張）")
