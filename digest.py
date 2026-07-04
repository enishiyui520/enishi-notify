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
lines.append("（統計過去 24 小時公開頻道 ・ 一起把話題炒熱吧 🎀）")
post_wh("\n".join(lines))
print(f"✅ 已發每日回顧（{msg_count} 則、{len(active_users)} 人、聊天高手 {len(top_chat)}、關鍵詞 {len(terms)}、懶人包 {'有' if digest else '無'}、裁決 {'有' if verdict else '無'}）")

# ---------- 發「緣」：每則留言 +1，每日上限 30（批次、一天一次）----------
def grant_yuan(grants):
    grants = {u: v for u, v in grants.items() if v > 0}
    if not grants:
        return
    try:
        body = json.dumps({"grants": grants}).encode()
        req = urllib.request.Request("https://enishi-omikuji.enishi-yui.workers.dev/?loyalty=enishi-loyalty-2026",
                                     data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
        print("💫 發緣(留言):", json.loads(urllib.request.urlopen(req, timeout=30).read()))
    except Exception as e:
        print("發緣失敗:", str(e)[:150])
grant_yuan({uid: min(n, 30) for uid, n in author_msg.items()})

# ---------- 社群頭目：把當天閒聊懶人包 → 隔天共鬥頭目（安全 fail-closed）----------
_GEM_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GKEY}"

def _gem_json(prompt, temp=0.8, maxtok=600):
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": temp, "maxOutputTokens": maxtok,
                                            "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}}).encode()
    r = json.loads(urllib.request.urlopen(urllib.request.Request(_GEM_URL, data=body, headers={"Content-Type": "application/json"}), timeout=60).read())
    return json.loads("".join(p.get("text", "") for p in r["candidates"][0]["content"].get("parts", [])).strip())

def gen_community_boss(summary):
    if not GKEY or not summary:
        return
    prompt = (
        "你是「緣結」——可愛俏皮、中日混雜的實習結緣神 VTuber，帶社群打倒「心魔」。"
        "任務：把「昨天社群閒聊懶人包」變成「今天大家一起共鬥的頭目」。頭目＝把大家共通生活煩惱擬人化的笨萌小妖怪。\n"
        "【調性】頭目是『情緒/現象』擬人化，**永遠不是某個人**。命名用 XX魔/獸/君/醬。可愛療癒笨萌、不邪惡。對事不對人，選多數人有共感的煩惱（賴床/拖延/熬夜/爆肝/選擇困難/emo/社恐…）。緣結口吻俏皮、結尾溫柔，繁體台灣中文可少量日文語助詞(なの/だよ/よし)，禁中國大陸用語。\n"
        "【安全規則(最高優先)】絕不能變頭目：①點名或影射真實個人 ②社群吵架衝突公審糾紛 ③政治時事兩岸選舉宗教 ④色情低俗獵奇 ⑤仇恨歧視 ⑥自傷心理危機 ⑦個資隱私爆料 ⑧違法。\n"
        "★★最重要：**若這個煩惱是從『有人抱怨/嫌棄某人的行為』或『吵架』來的**（例如嫌某人遲到、某人做錯事、誰又怎樣）——**絕對不要做成那個行為的頭目**（那等於指著當事人罵）。這種情況要嘛抽象成**跟那件事完全無關**的通用煩惱、要嘛直接 safe=false。\n"
        "處理階梯：A.抽象化(首選)：剝掉人事時地、只留跟衝突無關的共通情緒。B.太敏感無法安全抽象化→safe=false。C.自傷或針對個人霸凌→safe=false 且 reason=need_human_review。絕不重述影射敏感原文。寧可頭目普通也不可傷人。\n"
        '只輸出JSON：{"boss_name":"","backstory":"80~150字緣結口吻故事","defeat_line":"被打倒台詞一句笨萌釋懷+溫柔收尾","safe":true或false,"reason":"safe=false時原因否則ok"}\n\n'
        "昨天閒聊懶人包：\n<<<\n" + summary + "\n>>>")
    try:
        d = _gem_json(prompt, temp=0.8, maxtok=600)
    except Exception as e:
        print("社群頭目生成失敗、改用隨機頭目:", str(e)[:150]); return
    if not d.get("safe") or not d.get("boss_name"):
        print("社群頭目未過自評(fail-closed)、改用隨機頭目:", d.get("reason", "?")); return
    # Gate 1：獨立審核（自評太寬鬆、再獨立判一次、fail-closed）
    try:
        rev = _gem_json("你是嚴格的內容安全審核員。判斷這個要公開到社群遊戲的頭目是否**可能**：①指向/影射某真實個人或某人的行為(即使沒點名) ②源自社群吵架/衝突/抱怨某人 ③涉政治/色情/仇恨/自傷/個資/違法。**只要它讀起來像在講「某個人做了什麼」而不是「大家共通的煩惱」，就 block**。寧可從嚴。只輸出JSON：{\"block\":true或false,\"why\":\"\"}\n"
                        f"頭目名：{d['boss_name']}\n故事：{d.get('backstory','')}\n彩蛋：{d.get('defeat_line','')}", temp=0, maxtok=150)
        if rev.get("block"):
            print("社群頭目 Gate1 擋下、改用隨機頭目:", rev.get("why", "?")); return
    except Exception as e:
        print("社群頭目 Gate1 審核失敗(fail-closed)、改用隨機頭目:", str(e)[:120]); return
    boss = {"name": d["boss_name"], "story": d.get("backstory", ""), "egg": d.get("defeat_line", "")}
    try:
        req = urllib.request.Request("https://enishi-omikuji.enishi-yui.workers.dev/?comboss=enishi-loyalty-2026",
                                     data=json.dumps(boss).encode(), headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
        print("🔮 社群頭目已生成:", boss["name"], "|", json.loads(urllib.request.urlopen(req, timeout=30).read()))
    except Exception as e:
        print("社群頭目 POST 失敗:", str(e)[:150])
gen_community_boss(digest)
