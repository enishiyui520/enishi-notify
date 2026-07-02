# -*- coding: utf-8 -*-
"""YouTube Data API v3 helper（機房 IP 也可靠，取代被擋的網頁爬取/yt-dlp 抽取）。
需要環境變數 YT_API_KEY（Google Cloud 建的 YouTube Data API v3 金鑰）。
配額：uploads playlist(1) + videos.list(1) ≈ 2 units/次，每 5 分鐘跑 << 10000/日。"""
import json, urllib.request, urllib.parse

def _api(endpoint, params, key):
    params["key"] = key
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "enishi-notify"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

def recent_video_ids(ch, key, n=6):
    uploads = "UU" + ch[2:]   # 頻道上傳清單 = UC→UU
    d = _api("playlistItems", {"part": "contentDetails", "playlistId": uploads, "maxResults": n}, key)
    return [i["contentDetails"]["videoId"] for i in d.get("items", [])]

def video_status(ids, key):
    if not ids:
        return {}
    d = _api("videos", {"part": "snippet,liveStreamingDetails", "id": ",".join(ids)}, key)
    out = {}
    for i in d.get("items", []):
        sn = i.get("snippet", {}); lsd = i.get("liveStreamingDetails", {})
        out[i["id"]] = {
            "live": sn.get("liveBroadcastContent"),   # live / upcoming / none
            "title": sn.get("title", ""),
            "ended": bool(lsd.get("actualEndTime")),
            "is_stream": bool(lsd),
        }
    return out

def find_live(ch, key):
    """回傳正在直播中的 video id，沒有則 None。"""
    ids = recent_video_ids(ch, key)
    st = video_status(ids, key)
    for vid in ids:
        if st.get(vid, {}).get("live") == "live":
            return vid
    return None

def find_latest_ended_stream(ch, key):
    """回傳最近一支『已結束直播』(vid, title)，沒有則 (None, None)。ids 為新到舊。"""
    ids = recent_video_ids(ch, key)
    st = video_status(ids, key)
    for vid in ids:
        s = st.get(vid, {})
        if s.get("ended") and s.get("live") == "none":
            return vid, s.get("title", "")
    return None, None
