# -*- coding: utf-8 -*-
"""每日表情排行榜：唯讀 bot 讀各公開文字頻道近 24h 的表情互動 →
   ① 今日最熱門表情（reaction + 內文打的自訂/unicode emoji）
   ② 表情王（誰「按」別人最多表情）
   ③ 人氣王（誰的訊息「被按」最多表情）
   貼到排行榜頻道。跑在 GitHub Actions，每天一次。只讀不發（發用 webhook）。"""
import os, sys, io, json, time, re, urllib.request, urllib.error, datetime
from urllib.parse import quote
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
# GitHub 自己的排程 cron 時間會飄 → 忽略它，只在被主動觸發(dispatch)時跑；由雲端定時器準時 23:30(台灣) 觸發
if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
    print("skip scheduled run（改由雲端 23:30 觸發）"); sys.exit(0)

TOK = os.environ["STATS_BOT_TOKEN"]
WH = os.environ["WEBHOOK_LB"]
GUILD = "1518798030499877037"
API = "https://discord.com/api/v10"
UA = "DiscordBot (https://enishi.dev, 1.0)"

# 不掃描：工作區/會員/反省房/語音分類，及自動貼文/機器人頻道（排行榜/回顧/精華/御神籤/修行場）
SKIP_PARENTS = {"1518812049289908334", "1518812064343265331", "1521527300208853172", "1518812057418338456"}
SKIP_CHANNELS = {"1521530855883804743", "1521545659944009898", "1521508650823192746",
                 "1521524009961783347", "1521532810576527403"}
UNI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U0001F1E6-\U0001F1FF]")

def get(path):
    req = urllib.request.Request(API + path, headers={"Authorization": "Bot " + TOK, "User-Agent": UA})
    for _ in range(6):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    ra = float(json.loads(e.read().decode()).get("retry_after", 2))
                except Exception:
                    ra = 3
                time.sleep(min(ra + 0.5, 10)); continue
            if e.code in (403, 404):
                return None
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return None

def post_wh(content):
    body = json.dumps({"content": content[:1990], "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(WH, data=body, headers={"Content-Type": "application/json", "User-Agent": UA})
    urllib.request.urlopen(req, timeout=30)

now = datetime.datetime.now(datetime.timezone.utc)
cutoff = now - datetime.timedelta(hours=24)

author_recv = defaultdict(int); author_name = {}   # 被按最多
author_give = defaultdict(int); giver_name = {}     # 按別人最多
emoji_cnt = defaultdict(int)
_react_calls = 0
REACT_CALL_CAP = 200   # 保護：抓 reaction 使用者的呼叫上限

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
        # ---- reactions（別人按這則訊息）----
        for r in (m.get("reactions") or []):
            cnt = r.get("count", 0)
            em = r.get("emoji", {})
            if em.get("id"):
                key = f"<:{em.get('name')}:{em['id']}>"; ident = f"{em.get('name')}:{em['id']}"
            else:
                key = em.get("name") or "?"; ident = em.get("name") or ""
            emoji_cnt[key] += cnt
            if not au.get("bot"):
                aid = au.get("id"); author_recv[aid] += cnt
                author_name[aid] = au.get("global_name") or au.get("username") or "?"
            # 誰按的：抓 reaction 使用者
            if ident and _react_calls < REACT_CALL_CAP:
                _react_calls += 1
                users = get(f"/channels/{c['id']}/messages/{m['id']}/reactions/{quote(ident)}?limit=100")
                for u in (users or []):
                    if u.get("bot"):
                        continue
                    uid = u.get("id"); author_give[uid] += 1
                    giver_name[uid] = u.get("global_name") or u.get("username") or "?"
                time.sleep(0.25)
        # ---- 內文打的 emoji（只算真人）----
        if not au.get("bot"):
            ct = m.get("content") or ""
            for _n, _id in re.findall(r"<a?:(\w+):(\d+)>", ct):
                emoji_cnt[f"<:{_n}:{_id}>"] += 1
            for _e in UNI.findall(ct):
                emoji_cnt[_e] += 1
    time.sleep(0.4)

if not emoji_cnt and not author_give:
    print("近 24h 沒有表情互動，略過不發"); sys.exit(0)

medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
top_give = sorted(author_give.items(), key=lambda kv: kv[1], reverse=True)[:5]
top_recv = sorted(author_recv.items(), key=lambda kv: kv[1], reverse=True)[:5]
top_emoji = sorted(emoji_cnt.items(), key=lambda kv: kv[1], reverse=True)[:5]

date_str = (now + datetime.timedelta(hours=8)).strftime("%m/%d")
lines = [f"# 🏆 緣結會所・{date_str} 表情排行 🎀", ""]
if top_give:
    lines.append("**💞 今日表情王**（最會按表情捧場的人）")
    for i, (uid, n) in enumerate(top_give):
        lines.append(f"{medals[i]} {giver_name.get(uid, '?')} ・ 按了 {n} 個")
    lines.append("")
if top_recv:
    lines.append("**✨ 今日人氣王**（訊息被按最多表情）")
    for i, (aid, n) in enumerate(top_recv):
        lines.append(f"{medals[i]} {author_name.get(aid, '?')} ・ 收到 {n} 個")
    lines.append("")
if top_emoji:
    lines.append("**😎 今日最熱門表情**")
    for i, (k, n) in enumerate(top_emoji):
        lines.append(f"{medals[i]} {k} ・ {n} 次")
lines.append("\n（統計過去 24 小時 ・ 多按表情幫朋友上榜吧 🎀）")
post_wh("\n".join(lines))
print(f"✅ 已發表情排行（表情王 {len(top_give)}、人氣王 {len(top_recv)}、熱門表情 {len(top_emoji)}、reaction呼叫 {_react_calls}）")

# ---------- 發「緣」：給別人按一個表情 +1，每日上限 10（批次）----------
def grant_yuan(grants):
    grants = {u: v for u, v in grants.items() if v > 0}
    if not grants:
        return
    try:
        body = json.dumps({"grants": grants}).encode()
        req = urllib.request.Request("https://enishi-omikuji.enishi-yui.workers.dev/?loyalty=enishi-loyalty-2026",
                                     data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
        print("💫 發緣(表情):", json.loads(urllib.request.urlopen(req, timeout=30).read()))
    except Exception as e:
        print("發緣失敗:", str(e)[:150])
grant_yuan({uid: min(n, 10) for uid, n in author_give.items()})
