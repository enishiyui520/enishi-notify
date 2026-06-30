# -*- coding: utf-8 -*-
"""每日回顧：唯讀 bot 讀公開文字頻道近 24h 的人類訊息 →
   ① 熱詞排行（jieba 斷詞 + 停用詞過濾）
   ② 每日懶人包（Gemini 摘要「今天大家聊了什麼」）
   貼到 📊每日回顧頻道。跑在 GitHub Actions，每天一次。只讀不發言（發用 webhook）。"""
import os, sys, io, json, time, re, urllib.request, datetime
from collections import Counter
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

TOK = os.environ["STATS_BOT_TOKEN"]
WH = os.environ["WEBHOOK_RECAP"]
GKEY = os.environ.get("GEMINI_API_KEY", "")
GUILD = "1518798030499877037"
API = "https://discord.com/api/v10"
UA = "DiscordBot (https://enishi.dev, 1.0)"

# 不掃描的分類（工作區 / 會員專屬 / 反省房 / 語音）與自動貼文頻道
SKIP_PARENTS = {"1518812049289908334", "1518812064343265331", "1521527300208853172", "1518812057418338456"}
SKIP_CHANNELS = {"1521530855883804743", "1521545659944009898", "1521508650823192746",
                 "1521524009961783347"}  # 表情榜/每日回顧/精華/御神籤

def get(path):
    req = urllib.request.Request(API + path, headers={"Authorization": "Bot " + TOK, "User-Agent": UA})
    for _ in range(4):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
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

texts = []           # 給 Gemini 的原文樣本
msg_count = 0
active_users = set()

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
        msg_count += 1
        active_users.add(au.get("id"))
        texts.append(content)
    time.sleep(0.3)

if msg_count < 8:
    print(f"近 24h 訊息太少（{msg_count}），略過不發"); sys.exit(0)

# ---------- 熱詞排行 ----------
STOP = set("的 了 是 我 你 他 她 也 在 就 都 而 及 與 著 或 一個 沒有 我們 你們 他們 自己 這個 那個 "
           "什麼 怎麼 這樣 那樣 可以 不會 真的 好像 但是 所以 因為 如果 還是 已經 一直 這麼 那麼 "
           "覺得 知道 應該 不要 不過 然後 現在 大家 有點 一下 喔 喎 啦 啊 嗎 呢 吧 唉 欸 哈哈 笑死 "
           "https http com www 圖片 貼圖 表情 一樣 比較 還有 為什麼 真是 還有 有沒有".split())
try:
    import jieba
    jieba.setLogLevel(20)
    words = []
    for t in texts:
        t = re.sub(r"https?://\S+", "", t)
        for w in jieba.cut(t):
            w = w.strip()
            if len(w) < 2 or w in STOP:
                continue
            if re.fullmatch(r"[\W\d_]+", w):
                continue
            words.append(w)
    top_words = Counter(words).most_common(8)
except Exception as e:
    print("jieba 失敗:", str(e)[:120]); top_words = []

# ---------- Gemini 懶人包 ----------
def gemini_digest(sample):
    if not GKEY:
        return None
    prompt = ("以下是 VTuber 緣結 Discord 社群今天的聊天訊息（隨機節選）。"
              "請用繁體中文寫一段 100~150 字的「今日懶人包」，輕鬆親切口吻，"
              "整理出今天大家主要聊了哪些話題、有什麼有趣的梗或討論，"
              "讓沒空看的人快速跟上。只輸出懶人包本文，不要前言。\n\n訊息：\n" + sample[:6000])
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.6, "maxOutputTokens": 400}}).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GKEY}"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=60).read())
        return r["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print("Gemini 摘要失敗:", str(e)[:160]); return None

sample = "\n".join(texts)
digest = gemini_digest(sample)

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
if top_words:
    lines.append("## 🔥 今日熱詞 TOP")
    for i, (w, n) in enumerate(top_words):
        lines.append(f"{medals[i]} **{w}** ・ {n} 次")
    lines.append("")
lines.append("（統計過去 24 小時公開頻道 ・ 一起把話題炒熱吧 🎀）")
post_wh("\n".join(lines))
print(f"✅ 已發每日回顧（{msg_count} 則訊息、{len(active_users)} 人、熱詞 {len(top_words)}）")
