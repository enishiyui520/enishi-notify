# -*- coding: utf-8 -*-
"""X(推特)新推文 → Discord。用 twscrape + 小號 cookie（X 砍了訪客存取，必須登入）。
跑在 GitHub Actions，狀態存 x_state.json。第一次只記錄不發。"""
import asyncio, os, sys, io, json, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from twscrape import API

WH = os.environ["WEBHOOK_SNS"]
CK = os.environ["X_COOKIES"]
XUSER = os.environ["X_USERNAME"]
TARGET = os.environ.get("X_TARGET", "enishi_yui")
STATE = "x_state.json"

def post(content):
    body = json.dumps({"content": content}).encode()
    req = urllib.request.Request(WH, data=body, headers={
        "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (enishi-notify)"})
    urllib.request.urlopen(req, timeout=30)

def is_original(t):
    if getattr(t, "retweetedTweet", None): return False
    if getattr(t, "inReplyToTweetIdStr", None) or getattr(t, "inReplyToTweetId", None): return False
    return True

async def main():
    try:
        state = json.load(open(STATE, encoding="utf-8"))
    except Exception:
        state = {}
    first_run = not state

    api = API("x_accounts.db")
    try:
        await api.pool.add_account(XUSER, "x", "x@x.com", "x", cookies=CK)
    except Exception as e:
        print("add_account note:", e)
    try:
        await api.pool.login_all()
    except Exception:
        pass

    u = await api.user_by_login(TARGET)
    if not u:
        print("❌ 抓不到帳號（cookie 失效或被擋）"); return
    tweets = []
    async for t in api.user_tweets(u.id, limit=10):
        tweets.append(t)
    if not tweets:
        print("沒抓到推文"); return

    maxid = max(int(t.id) for t in tweets)
    if first_run:
        state["last_tweet"] = str(maxid)
        json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
        print("first run, recorded", maxid); return

    last = int(state.get("last_tweet", 0))
    new = sorted([t for t in tweets if int(t.id) > last], key=lambda t: int(t.id))
    posted = 0
    for t in new:
        if not is_original(t):
            continue
        txt = (t.rawContent or "").strip()[:300]
        post(f"🐦 **緣結發推了！** 🎀\n{txt}\nhttps://x.com/{TARGET}/status/{t.id}")
        posted += 1
    state["last_tweet"] = str(maxid)
    json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"done. 新推 {len(new)} 則，發出 {posted} 則")

# 11-23：twscrape 遇到 X 限流會「睡到解封」（實測一睡 45 分～1 小時以上），整個 workflow 卡住，
# 後面每 15 分 dispatch 的都排隊被取消（狂寄 cancelled 信），懶人包步驟也跟著延後。最多等 2 分鐘，抓不到就下輪再抓。
async def guarded():
    try:
        await asyncio.wait_for(main(), timeout=120)
    except asyncio.TimeoutError:
        print("⏱ X 抓取超過 2 分鐘（多半是被限流），這輪跳過，下輪再抓")

# 11-23：X 對 GitHub 機房 IP 一律回 403（同一組 cookie、同版 twscrape 在家用網路正常），
# 推特通知改由業主電腦的排程跑（緣結DC自動建置\tools\推特通知_本機.py）。這裡在 GitHub 上直接跳過：
# 不重複發、也不讓機房 IP 每 15 分打 403 害新 cookie 被標記。
if os.environ.get("GITHUB_ACTIONS"):
    print("推特通知已改由本機排程跑，GitHub 這步跳過"); sys.exit(0)

# 第二道保險：就算卡在不讓出控制權的同步呼叫（wait_for 等不到），3 分鐘一到整支程序直接結束、exit 0 不擋後面步驟
import threading
threading.Timer(180, lambda: (print("⏱ X 抓取 3 分鐘硬上限，強制結束"), sys.stdout.flush(), os._exit(0))).start()
asyncio.run(guarded())
os._exit(0)
