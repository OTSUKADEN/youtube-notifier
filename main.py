import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
import requests

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

SEARCH_KEYWORDS = ["バカゲー 実況", "ホラゲー 実況", "ホラーゲーム 実況"]
GAMING_CATEGORY_ID = "20"


def get_one_week_ago_iso():
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    return one_week_ago.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_trending_videos(keyword, max_results=25):
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet",
        "q": keyword,
        "type": "video",
        "videoCategoryId": GAMING_CATEGORY_ID,
        "order": "viewCount",
        "publishedAfter": get_one_week_ago_iso(),
        "maxResults": max_results,
        "regionCode": "JP",
    }
    res = requests.get(url, params=params).json()
    return res.get("items", [])


def get_video_and_channel_details(video_items):
    if not video_items:
        return []

    video_ids = [item["id"]["videoId"] for item in video_items]
    channel_ids = list(
        set([item["snippet"]["channelId"] for item in video_items])
    )

    v_url = "https://www.googleapis.com/youtube/v3/videos"
    v_params = {
        "key": YOUTUBE_API_KEY,
        "part": "statistics,snippet",
        "id": ",".join(video_ids),
    }
    v_res = requests.get(v_url, params=v_params).json()

    c_url = "https://www.googleapis.com/youtube/v3/channels"
    c_params = {
        "key": YOUTUBE_API_KEY,
        "part": "statistics",
        "id": ",".join(channel_ids),
    }
    c_res = requests.get(c_url, params=c_params).json()

    channel_sub_map = {}
    for c_item in c_res.get("items", []):
        stats = c_item.get("statistics", {})
        sub_count = int(stats.get("subscriberCount", 0))
        channel_sub_map[c_item["id"]] = sub_count

    viral_videos = []
    for v_item in v_res.get("items", []):
        view_count = int(v_item["statistics"].get("viewCount", 0))
        channel_id = v_item["snippet"]["channelId"]
        sub_count = channel_sub_map.get(channel_id, 0)

        if sub_count > 0 and view_count > sub_count:
            viral_videos.append(v_item)

    return viral_videos


def extract_game_titles(video_items):
    titles = []
    exclude_words = [
        "実況",
        "単発",
        "新作",
        "閲覧注意",
        "爆笑",
        "神ゲー",
        "バカゲー",
        "ホラゲー",
        "前編",
        "後編",
        "完結",
        "無料",
    ]

    for item in video_items:
        title = item["snippet"]["title"]
        matches = re.findall(r"[『【](.*?)[』】]", title)
        for match in matches:
            if not any(ex in match for ex in exclude_words) and len(match) > 1:
                titles.append(match)
    return titles


def send_discord_notification(trending_games):
    if not trending_games:
        content = "🎮 **YouTube 穴場・バズゲーム通知**\n直近で「チャンネル登録者数を超える再生数」を出している注目ゲームは見つかりませんでした。"
    else:
        game_list_str = "\n".join(
            [
                f"・**{game}** (バズ判定件数: {count}件)"
                for game, count in trending_games
            ]
        )
        content = (
            f"🔥 **【YouTube】登録者数超えのヒット・バズゲームタイトル**\n\n"
            f"直近1週間で**「チャンネル登録者数よりも再生回数が多く回っている動画」**から自動抽出したおすすめタイトルです：\n\n"
            f"{game_list_str}\n\n"
            f"*※登録者数以上の再生数を記録している企画・ゲーム性の高いタイトルです。*"
        )

    requests.post(DISCORD_WEBHOOK_URL, json={"content": content})


def main():
    if not YOUTUBE_API_KEY or not DISCORD_WEBHOOK_URL:
        print("エラー: 環境変数が設定されていません。")
        return

    viral_video_pool = []

    for kw in SEARCH_KEYWORDS:
        search_results = fetch_trending_videos(kw)
        viral_videos = get_video_and_channel_details(search_results)
        viral_video_pool.extend(viral_videos)

    game_candidates = extract_game_titles(viral_video_pool)
    top_games = Counter(game_candidates).most_common(5)

    send_discord_notification(top_games)


if __name__ == "__main__":
    main()
