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

asyncio.run(main())
