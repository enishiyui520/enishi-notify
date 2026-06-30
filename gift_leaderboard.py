# -*- coding: utf-8 -*-
"""YouTube 會員贈禮排行（學圖奇 gift sub 精神）。
MODE=harvest：掃頻道最近的直播，從聊天室 replay 抓「會員贈禮」事件，累積每人每月送幾個（去重已掃過的影片）。
MODE=post   ：每月 1 號發「上個月」的贈禮排行榜到 Discord，然後該月封存。
跑在 GitHub Actions。狀態存 gift_state.json（commit 回 repo）。

前提：頻道需已開啟「會員 + 會員贈禮」(1000訂閱+YPP)。未開啟前會跑綠燈但 0 筆。"""
import os, sys, io, json, re, time, datetime, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

MODE = os.environ.get("MODE", "harvest")
CH = os.environ["YT_CHANNEL_ID"]
WH = os.environ["WEBHOOK_GIFT"]
STATE_FILE = "gift_state.json"
UA = "Mozilla/5.0 (enishi-gift)"

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"processed": [], "months": {}}

def save_state(s):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)

def tw_now():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)

def post_wh(content):
    body = json.dumps({"content": content[:1990], "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(WH, data=body, headers={"Content-Type": "application/json", "User-Agent": UA})
    urllib.request.urlopen(req, timeout=30)

def recent_video_ids():
    """用 uploads RSS（免 API 配額）拿最近 ~15 支影片 ID。"""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={CH}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    xml = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    return re.findall(r"<yt:videoId>([\w-]+)</yt:videoId>", xml)

# 從贈禮訊息文字抽出「送幾個」：支援 "Gifted 5 memberships" / "5 件" / "5 個" 等
def parse_gift_count(text):
    if not text:
        return 1
    m = re.search(r"(\d+)", text.replace(",", ""))
    return int(m.group(1)) if m else 1

def harvest():
    from chat_downloader import ChatDownloader
    state = load_state()
    processed = set(state["processed"])
    months = state["months"]
    vids = recent_video_ids()
    new_done = 0
    for vid in vids:
        if vid in processed:
            continue
        url = f"https://www.youtube.com/watch?v={vid}"
        gifts_in_vid = 0
        try:
            chat = ChatDownloader().get_chat(url, message_groups=["sponsorships"], max_attempts=3)
            for m in chat:
                if m.get("message_type") != "sponsorships_gift_purchase_announcement":
                    continue
                gifter = (m.get("author") or {}).get("name") or "匿名"
                cnt = parse_gift_count(m.get("message") or "")
                # 用訊息時間決定歸到哪個月（台灣月）
                ts = m.get("timestamp")
                if ts:
                    dt = datetime.datetime.fromtimestamp(ts / 1e6, datetime.timezone.utc) + datetime.timedelta(hours=8)
                else:
                    dt = tw_now()
                mk = dt.strftime("%Y-%m")
                months.setdefault(mk, {})
                months[mk][gifter] = months[mk].get(gifter, 0) + cnt
                gifts_in_vid += cnt
        except Exception as e:
            # 非直播 / 無 replay / members-only → 跳過，仍標記已處理避免每天重掃
            msg = str(e)[:80]
            if "membership" in msg.lower() or "private" in msg.lower():
                pass
            print(f"  skip {vid}: {msg}")
        processed.add(vid)
        new_done += 1
        if gifts_in_vid:
            print(f"  ✅ {vid}: +{gifts_in_vid} 贈禮")
        time.sleep(1)
    state["processed"] = list(processed)[-300:]  # 只留最近 300 支避免無限長
    state["months"] = months
    save_state(state)
    print(f"harvest 完成：本次掃 {new_done} 支新影片。累積月份：{ {k: sum(v.values()) for k,v in months.items()} }")

def post():
    state = load_state()
    # 上個月
    now = tw_now()
    first = now.replace(day=1)
    last_month = (first - datetime.timedelta(days=1)).strftime("%Y-%m")
    data = state["months"].get(last_month, {})
    if not data:
        print(f"{last_month} 無贈禮資料，不發（可能會員/贈禮尚未開啟或當月無人贈禮）")
        return
    ranking = sorted(data.items(), key=lambda kv: kv[1], reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    total = sum(data.values())
    y, mo = last_month.split("-")
    lines = [f"# 🎁 結緣神社・{y}年{int(mo)}月 會員贈禮排行 ⛩️", ""]
    lines.append(f"上個月共有 **{total}** 份會員贈禮，感謝以下大恩人的結緣之力 ✨")
    lines.append("")
    for i, (name, n) in enumerate(ranking):
        lines.append(f"{medals[i]} **{name}** ・ 贈禮 {n} 份")
    lines.append("\n（每月 1 號結算上月 ・ 會員贈禮是緣結最大的支持 🎀）")
    post_wh("\n".join(lines))
    print(f"✅ 已發 {last_month} 贈禮排行（{len(ranking)} 人、{total} 份）")

if __name__ == "__main__":
    print(f"MODE={MODE}")
    if MODE == "post":
        post()
    else:
        harvest()
