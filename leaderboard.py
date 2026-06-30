# -*- coding: utf-8 -*-
"""每日表情排行榜：唯讀 bot 讀各文字頻道近 24h 訊息上的表情 → 統計 → 貼到排行榜頻道。
跑在 GitHub Actions，每天一次。只讀不發（發用 webhook）。"""
import os, sys, io, json, time, urllib.request, datetime
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

TOK = os.environ["STATS_BOT_TOKEN"]
WH = os.environ["WEBHOOK_LB"]
GUILD = "1518798030499877037"
API = "https://discord.com/api/v10"
UA = "Mozilla/5.0 (enishi-stats)"

def get(path):
    req = urllib.request.Request(API + path, headers={"Authorization": "Bot " + TOK, "User-Agent": UA})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception:
        return None

def post_wh(content):
    body = json.dumps({"content": content[:1990], "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(WH, data=body, headers={"Content-Type": "application/json", "User-Agent": UA})
    urllib.request.urlopen(req, timeout=30)

now = datetime.datetime.now(datetime.timezone.utc)
cutoff = now - datetime.timedelta(hours=24)

author_recv = defaultdict(int); author_name = {}
emoji_cnt = defaultdict(int)

channels = get(f"/guilds/{GUILD}/channels") or []
for c in channels:
    if c.get("type") != 0:
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
        for r in (m.get("reactions") or []):
            cnt = r.get("count", 0)
            if not au.get("bot"):
                aid = au.get("id")
                author_recv[aid] += cnt
                author_name[aid] = au.get("global_name") or au.get("username") or "?"
            em = r.get("emoji", {})
            key = f"<:{em.get('name')}:{em['id']}>" if em.get("id") else (em.get("name") or "?")
            emoji_cnt[key] += cnt
    time.sleep(0.3)

if not emoji_cnt:
    print("近 24h 沒有表情互動，略過不發"); sys.exit(0)

medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
top_users = sorted(author_recv.items(), key=lambda kv: kv[1], reverse=True)[:5]
top_emoji = sorted(emoji_cnt.items(), key=lambda kv: kv[1], reverse=True)[:5]
lines = ["# 🏆 緣結會所・今日表情排行 🎀", ""]
lines.append("**✨ 最受歡迎**（訊息被按最多表情）")
for i, (aid, n) in enumerate(top_users):
    lines.append(f"{medals[i]} {author_name.get(aid, '?')} ・ {n} 個")
lines.append("")
lines.append("**😎 今日最熱門表情**")
for i, (k, n) in enumerate(top_emoji):
    lines.append(f"{medals[i]} {k} ・ {n} 次")
lines.append("\n（統計過去 24 小時 ・ 多按表情幫朋友上榜吧 🎀）")
post_wh("\n".join(lines))
print("✅ 已發今日表情排行榜")
