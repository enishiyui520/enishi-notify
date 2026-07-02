# -*- coding: utf-8 -*-
"""每日回顧：唯讀 bot 讀公開文字頻道近 24h 的人類訊息 →
   ① 今日懶人包（Gemini 摘要今天大家聊什麼）
   ② 今日聊天高手（發言最多）
   ③ 熱詞排行（jieba 斷詞，附一句真實聊天例子）
   ④ 今日神明裁決（實習神緣結的搞笑蓋章）
   貼到 📊每日回顧頻道。跑在 GitHub Actions，每天一次。只讀不發言（發用 webhook）。"""
import os, sys, io, json, time, re, urllib.request, urllib.error, datetime
from collections import Counter, defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

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

# ---------- 熱詞排行 ----------
STOP = set("的 了 是 我 你 他 她 也 在 就 都 而 及 與 著 或 一個 沒有 我們 你們 他們 自己 這個 那個 "
           "什麼 怎麼 這樣 那樣 可以 不會 真的 好像 但是 所以 因為 如果 還是 已經 一直 這麼 那麼 "
           "覺得 知道 應該 不要 不過 然後 現在 大家 有點 一下 喔 喎 啦 啊 嗎 呢 吧 唉 欸 哈哈 笑死 "
           "https http com www 圖片 貼圖 表情 一樣 比較 還有 為什麼 真是 有沒有".split())
try:
    import jieba
    jieba.setLogLevel(20)
    words = []
    for t in texts:
        for w in jieba.cut(clean(t)):
            w = w.strip()
            if len(w) < 2 or w in STOP:
                continue
            if re.fullmatch(r"[\W\d_]+", w):
                continue
            words.append(w)
    top_words = Counter(words).most_common(8)
except Exception as e:
    print("jieba 失敗:", str(e)[:120]); top_words = []

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

sample = "\n".join(texts)[:6000]
digest = gemini("以下是 VTuber 緣結 Discord 社群今天的聊天訊息（隨機節選）。"
                "請用繁體中文寫一段 100~150 字的「今日懶人包」，輕鬆親切口吻，"
                "整理今天大家主要聊了哪些話題、有什麼有趣的梗，讓沒空看的人快速跟上。"
                "只輸出懶人包本文，不要前言。\n\n訊息：\n" + sample)
verdict = gemini("你是結緣神社的實習神明『緣結』（可愛、俏皮、偶爾吐槽）。看完信徒今天的聊天，"
                 "用一句話（35 字內）幽默地下一個『今日神明裁決』，可以蓋章認證或吐槽今天的氣氛。"
                 "只輸出那句裁決本文，不要引號、不要前言。\n\n聊天：\n" + sample, 200)

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
if top_words:
    lines.append("## 🔥 今日熱詞 TOP")
    for i, (w, n) in enumerate(top_words):
        cands = [e for e in (clean(t) for t in texts if w in t) if len(e) >= 2]
        ex = (cands[0][:26] + "…") if cands and len(cands[0]) > 26 else (cands[0] if cands else "")
        lines.append(f"{medals[i]} **{w}** ・ {n} 次" + (f"　💬「{ex}」" if ex else ""))
    lines.append("")
if verdict:
    lines.append("## 🔮 今日神明裁決")
    lines.append("> " + verdict + "　― 緣結 🎀")
    lines.append("")
lines.append("（統計過去 24 小時公開頻道 ・ 一起把話題炒熱吧 🎀）")
post_wh("\n".join(lines))
print(f"✅ 已發每日回顧（{msg_count} 則、{len(active_users)} 人、聊天高手 {len(top_chat)}、熱詞 {len(top_words)}、懶人包 {'有' if digest else '無'}、裁決 {'有' if verdict else '無'}）")
