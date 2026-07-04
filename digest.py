# -*- coding: utf-8 -*-
"""每日回顧：唯讀 bot 讀公開文字頻道近 24h 的人類訊息 →
   ① 今日懶人包（Gemini 摘要今天大家聊什麼）
   ② 今日聊天高手（發言最多）
   ③ 熱詞排行（jieba 斷詞，附一句真實聊天例子）
   ④ 今日神明裁決（實習神緣結的搞笑蓋章）
   貼到 📊每日回顧頻道。跑在 GitHub Actions，每天一次。只讀不發言（發用 webhook）。"""
import os, sys, io, json, time, re, base64, urllib.request, urllib.error, datetime
from collections import Counter, defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
# GitHub 自己的排程 cron 時間會飄 → 忽略它，只在被主動觸發(dispatch)時跑；由雲端定時器準時 23:30(台灣) 觸發
if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
    print("skip scheduled run（改由雲端 23:30 觸發）"); sys.exit(0)

TOK = os.environ["STATS_BOT_TOKEN"]
WH = os.environ["WEBHOOK_RECAP"]
GKEY = os.environ.get("GEMINI_API_KEY", "")
GUILD = "1518798030499877037"
API = "https://discord.com/api/v10"
UA = "DiscordBot (https://enishi.dev, 1.0)"

SKIP_PARENTS = {"1518812049289908334", "1518812064343265331", "1521527300208853172", "1518812057418338456"}
SKIP_CHANNELS = {"1521530855883804743", "1521545659944009898", "1521508650823192746",
                 "1521524009961783347", "1521532810576527403"}  # 表情榜/每日回顧/精華/御神籤/修行場

EMOJI_RE = re.compile(r"<a?:\w+:\d+>")
UNI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U0001F1E6-\U0001F1FF]")

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
            if e.code == 403:
                time.sleep(2); continue
            return None
        except Exception:
            return None
    return None

def post_wh(content):
    body = json.dumps({"content": content[:1990], "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(WH, data=body, headers={"Content-Type": "application/json", "User-Agent": UA})
    urllib.request.urlopen(req, timeout=30)

now = datetime.datetime.now(datetime.timezone.utc)
cutoff = now - datetime.timedelta(hours=24)

texts = []
msg_count = 0
active_users = set()
author_msg = defaultdict(int); author_name = {}

channels = get(f"/guilds/{GUILD}/channels") or []
for c in channels:
    if c.get("type") != 0:
        continue
    if c.get("parent_id") in SKIP_PARENTS or c["id"] in SKIP_CHANNELS:
        continue
    msgs = get(f"/channels/{c['id']}/messages?limit=100")
    if not msgs:
        continue
    for m in msgs:
        try:
            ts = datetime.datetime.fromisoformat(m["timestamp"])
        except Exception:
            continue
        if ts < cutoff:
            continue
        au = m.get("author", {})
        if au.get("bot"):
            continue
        content = (m.get("content") or "").strip()
        if not content:
            continue
        aid = au.get("id")
        msg_count += 1
        active_users.add(aid)
        author_msg[aid] += 1
        author_name[aid] = au.get("global_name") or au.get("username") or "?"
        texts.append(content)
    time.sleep(0.3)

if msg_count < 8:
    print(f"近 24h 訊息太少（{msg_count}），略過不發"); sys.exit(0)

def clean(s):
    s = EMOJI_RE.sub("", s); s = re.sub(r"https?://\S+", "", s); s = UNI_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()

# ---------- 今日社群關鍵詞（AI 濃縮，取代純詞頻的熱詞排行）----------
# 舊版 jieba 詞頻會抓到「不是/就是」這種無意義詞、也會被遊戲用語洗版。
# 改由 Gemini 讀當天聊天 → 抓 1~3 個真正有意義的社群用語/梗/話題 + 一句解釋 + 為何今天在講。

# ---------- Gemini ----------
def gemini(prompt, max_tokens=800):
    if not GKEY:
        return None
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.7, "maxOutputTokens": max_tokens,
                                            "thinkingConfig": {"thinkingBudget": 0}}}).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GKEY}"
    try:
        r = json.loads(urllib.request.urlopen(urllib.request.Request(url, data=body,
            headers={"Content-Type": "application/json"}), timeout=60).read())
        parts = r["candidates"][0]["content"].get("parts", [])
        return ("".join(p.get("text", "") for p in parts).strip()) or None
    except Exception as e:
        print("Gemini 失敗:", str(e)[:200]); return None

def hot_terms(sample_text):
    """AI 抓當天最有代表性的 1~3 個社群用語/梗 + 一句解釋（抓觀眾脈絡邏輯）。"""
    if not GKEY:
        return []
    prompt = ("以下是 VTuber 緣結 Discord 社群今天的聊天。找出今天最能代表社群的 1~3 個「關鍵用語/梗/話題」，"
              "要有意義：社群黑話、迷因梗、當天反覆出現的主題、動漫或遊戲哏都行。"
              "嚴禁選『不是/就是/這個/真的/哈哈/沒有』這種無意義常用詞。"
              "每個用一句話解釋它的意思＋為什麼今天大家在講（抓社群當下的脈絡邏輯）。"
              "若今天沒有明顯的社群用語，terms 給空陣列。只輸出 JSON：\n"
              '{"terms":[{"term":"用語","explain":"一句話解釋＋今天為何在講"}]}\n\n聊天：\n' + sample_text)
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.5, "maxOutputTokens": 600,
                                            "responseMimeType": "application/json",
                                            "thinkingConfig": {"thinkingBudget": 0}}}).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GKEY}"
    try:
        r = json.loads(urllib.request.urlopen(urllib.request.Request(url, data=body,
            headers={"Content-Type": "application/json"}), timeout=60).read())
        txt = "".join(p.get("text", "") for p in r["candidates"][0]["content"].get("parts", [])).strip()
        return (json.loads(txt).get("terms") or [])[:3]
    except Exception as e:
        print("社群關鍵詞 AI 失敗:", str(e)[:150]); return []

sample = "\n".join(texts)[:6000]
digest = gemini("以下是 VTuber 緣結 Discord 社群今天的聊天訊息（隨機節選）。"
                "請用繁體中文寫一段 100~150 字的「今日懶人包」，輕鬆親切口吻，"
                "整理今天大家主要聊了哪些話題、有什麼有趣的梗，讓沒空看的人快速跟上。"
                "只輸出懶人包本文，不要前言。\n\n訊息：\n" + sample)
verdict = gemini("你是結緣神社的實習神明『緣結』（可愛、俏皮、偶爾吐槽）。看完信徒今天的聊天，"
                 "用一句話（35 字內）幽默地下一個『今日神明裁決』，可以蓋章認證或吐槽今天的氣氛。"
                 "只輸出那句裁決本文，不要引號、不要前言。\n\n聊天：\n" + sample, 200)

terms = hot_terms(sample)

# ---------- 今日最佳梗圖 + 梗圖王（梗圖區）----------
MEME_CH = "1518812041220067419"
IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")

def explain_meme(img_url):
    """Gemini 視覺猜這張梗圖在玩什麼哏（只看得到圖、標明是猜測）。1 張/日 成本 ~$0.001。"""
    if not GKEY:
        return ""
    try:
        raw = urllib.request.urlopen(urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
        if len(raw) > 4_000_000:
            return ""
        low = img_url.lower().split("?")[0]
        mime = "image/jpeg" if (low.endswith(".jpg") or low.endswith(".jpeg")) else \
               "image/gif" if low.endswith(".gif") else "image/webp" if low.endswith(".webp") else "image/png"
        prompt = ("這是社群今天最多人按表情的梗圖。用繁體中文猜這張圖在玩什麼哏、為什麼好笑，2~3 句。"
                  "你只看得到圖、不知道當下語境，所以開頭要說明這是你的猜測。")
        body = json.dumps({"contents": [{"parts": [{"inline_data": {"mime_type": mime, "data": base64.b64encode(raw).decode()}}, {"text": prompt}]}],
                           "generationConfig": {"temperature": 0.6, "maxOutputTokens": 300, "thinkingConfig": {"thinkingBudget": 0}}}).encode()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GKEY}"
        r = json.loads(urllib.request.urlopen(urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}), timeout=60).read())
        return "".join(p.get("text", "") for p in r["candidates"][0]["content"].get("parts", [])).strip()
    except Exception as e:
        print("梗圖解讀失敗:", str(e)[:150]); return ""

best_meme = None
meme_post = defaultdict(int); meme_name = {}
for m in (get(f"/channels/{MEME_CH}/messages?limit=100") or []):
    try:
        ts = datetime.datetime.fromisoformat(m["timestamp"])
    except Exception:
        continue
    if ts < cutoff:
        continue
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
    aid = au.get("id"); meme_post[aid] += 1
    meme_name[aid] = au.get("global_name") or au.get("username") or "?"
    rc = sum(r.get("count", 0) for r in (m.get("reactions") or []))
    if best_meme is None or rc > best_meme["rc"]:
        best_meme = {"rc": rc, "img": img, "jump": f"https://discord.com/channels/{GUILD}/{MEME_CH}/{m['id']}", "by": meme_name[aid]}

# ---------- 組訊息 ----------
medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]
date_str = (now + datetime.timedelta(hours=8)).strftime("%m/%d")
lines = [f"# 📊 緣結會所・{date_str} 每日回顧 🎀", ""]
lines.append(f"昨天 **{len(active_users)}** 位信徒、聊了 **{msg_count}** 則訊息 ✨")
lines.append("")
if digest:
    lines.append("## 📝 今日懶人包")
    lines.append(digest)
    lines.append("")
top_chat = sorted(author_msg.items(), key=lambda kv: kv[1], reverse=True)[:5]
if top_chat:
    lines.append("## 🗣️ 今日聊天高手")
    for i, (aid, n) in enumerate(top_chat):
        lines.append(f"{medals[i]} {author_name.get(aid, '?')} ・ {n} 則")
    lines.append("")
if terms:
    lines.append("## 🗣️ 今日社群關鍵詞")
    for t in terms:
        term = (t.get("term") or "").strip(); ex = (t.get("explain") or "").strip()
        if term:
            lines.append(f"**「{term}」** ― {ex}" if ex else f"**「{term}」**")
    lines.append("")
if verdict:
    lines.append("## 🔮 今日神明裁決")
    lines.append("> " + verdict + "　― 緣結 🎀")
    lines.append("")
if best_meme and best_meme["rc"] > 0:
    lines.append("## 🏆 今日最佳梗圖")
    lines.append(f"由 **{best_meme['by']}** 提供 ・ 被按 **{best_meme['rc']}** 個表情 🔥")
    lines.append(best_meme["jump"])
    ex = explain_meme(best_meme["img"])
    if ex:
        lines.append(f"🤖 {ex}")
    lines.append("")
if meme_post:
    king = max(meme_post.items(), key=lambda kv: kv[1])
    lines.append("## 🎨 今日梗圖王")
    lines.append(f"感謝 **{meme_name[king[0]]}** 今天貢獻 **{king[1]}** 張梗圖，讓大家笑不停 🎉")
    lines.append("")
lines.append("（統計過去 24 小時公開頻道 ・ 一起把話題炒熱吧 🎀）")
post_wh("\n".join(lines))
print(f"✅ 已發每日回顧（{msg_count} 則、{len(active_users)} 人、聊天高手 {len(top_chat)}、關鍵詞 {len(terms)}、懶人包 {'有' if digest else '無'}、裁決 {'有' if verdict else '無'}）")
