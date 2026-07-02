# -*- coding: utf-8 -*-
"""YouTube 會員贈禮排行（學圖奇 gift sub 精神）。
掃頻道最近的直播，從聊天室 replay 抓「會員贈禮」事件，累積每人每月送幾個（去重已掃過的影片），
然後把「本月榜 + 累積榜」推進 OBS 跑馬燈 Worker（不進 Discord，直播畫面動態呈現）。
跑在 GitHub Actions。狀態存 gift_state.json（commit 回 repo）。

前提：頻道需已開啟「會員 + 會員贈禮」(1000訂閱+YPP)。未開啟前會跑綠燈但 0 筆。"""
import os, sys, io, json, re, time, datetime, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

CH = os.environ["YT_CHANNEL_ID"].split("|")[0].strip()   # 可能夾帶 |APIKEY，只取頻道 ID
WORKER_URL = os.environ["WORKER_DONATE_URL"].rstrip("/")  # 例 https://enishi-donate.enishi-yui.workers.dev
DONATE_SECRET = os.environ["DONATE_SECRET"]
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

def push_to_overlay(month, month_rank, all_rank):
    """把贈禮榜推進 OBS 跑馬燈 Worker（不進 Discord）。"""
    body = json.dumps({"month": month, "monthRank": month_rank, "allRank": all_rank}).encode()
    req = urllib.request.Request(WORKER_URL + "/gift-hook", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "x-auth": DONATE_SECRET, "User-Agent": UA})
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

    # 本月榜 + 全期累積榜 → 推進 OBS 跑馬燈
    cur_month = tw_now().strftime("%Y-%m")
    y, mo = cur_month.split("-")
    month_label = f"{y}年{int(mo)}月"
    month_rank = sorted(months.get(cur_month, {}).items(), key=lambda kv: kv[1], reverse=True)[:20]
    all_acc = {}
    for mdict in months.values():
        for name, n in mdict.items():
            all_acc[name] = all_acc.get(name, 0) + n
    all_rank = sorted(all_acc.items(), key=lambda kv: kv[1], reverse=True)[:20]
    try:
        push_to_overlay(month_label, month_rank, all_rank)
        print(f"✅ 已推榜到跑馬燈：本月 {len(month_rank)} 人、累積 {len(all_rank)} 人")
    except Exception as e:
        print("推榜失敗:", str(e)[:120])

if __name__ == "__main__":
    harvest()
