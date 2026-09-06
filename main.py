import os
import re
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import requests

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

# 最新のバカゲー・ホラゲー・単発ヒット作を拾うための検索ワード
SEARCH_KEYWORDS = [
    "バカゲー 実況",
    "ホラーゲーム 単発",
    "Steam 新作 実況",
    "異変探し 実況",
    "短編ホラー 実況",
]

# タイトル抽出時に除外する無駄な単語リスト
EXCLUDE_WORDS = [
    "切り抜き",
    "きりぬき",
    "切抜",
    "実況",
    "単発",
    "新作",
    "閲覧注意",
    "爆爆",
    "神ゲー",
    "バカゲー",
    "ホラゲー",
    "ホラーゲーム",
    "前編",
    "後編",
    "完結",
    "無料",
    "Steam",
    "ゲーム",
    "まとめ",
]


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

    filtered_items = []
    for item in video_items:
        title = item["snippet"]["title"]
        if not any(
            clip_word in title
            for clip_word in ["切り抜き", "きりぬき", "切抜", "【切抜】"]
        ):
            filtered_items.append(item)

    if not filtered_items:
        return []

    video_ids = [item["id"]["videoId"] for item in filtered_items]
    channel_ids = list(
        set([item["snippet"]["channelId"] for item in filtered_items])
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

        # 登録者数を超える動画だけを抽出
        if sub_count > 0 and view_count > sub_count:
            # 投稿日（PublishedAt）を取得
            pub_at_str = v_item["snippet"].get("publishedAt", "")
            is_recent = False
            if pub_at_str:
                pub_date = datetime.strptime(
                    pub_at_str, "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)
                # 直近3日以内の投稿であれば「超最新バズ」と判定
                if datetime.now(timezone.utc) - pub_date <= timedelta(days=3):
                    is_recent = True

            v_item["sub_count"] = sub_count
            v_item["view_count"] = view_count
            v_item["ratio"] = round(view_count / sub_count, 1)
            v_item["is_recent"] = is_recent
            viral_videos.append(v_item)

    return viral_videos


def extract_game_data(video_items):
    game_stats = defaultdict(
        lambda: {"count": 0, "ratios": [], "recent_count": 0}
    )

    for item in video_items:
        title = item["snippet"]["title"]
        matches = re.findall(r"[『【](.*?)[』】]", title)
        for match in matches:
            if not any(ex in match for ex in EXCLUDE_WORDS) and len(match) > 1:
                game_stats[match]["count"] += 1
                game_stats[match]["ratios"].append(item["ratio"])
                if item.get("is_recent"):
                    game_stats[match]["recent_count"] += 1

    # 検出件数の多い上位5個のゲームを抽出
    sorted_games = sorted(
        game_stats.items(), key=lambda x: x[1]["count"], reverse=True
    )[:5]
    return sorted_games


def send_discord_notification(trending_games):
    if not trending_games:
        content = "🎮 **YouTube 注目ゲーム通知**\n直近で「登録者数を超える再生数」を記録した注目のゲームタイトルは見つかりませんでした。"
    else:
        game_list_items = []
        for game, data in trending_games:
            count = data["count"]
            avg_ratio = round(sum(data["ratios"]) / len(data["ratios"]), 1)
            recent_count = data["recent_count"]

            # 理由（判定ラベル）の設定
            if recent_count > 0:
                reason = "💡 **【話題の新作・急上昇】** 直近投稿で一気に再生数が跳ねている注目の最新作です！"
            else:
                reason = "💡 **【定番ロングヒット】** 発売後も検索や関連動画で伸び続けている安定企画系ゲームです。"

            encoded_game = urllib.parse.quote(game)
            steam_url = f"https://store.steampowered.com/search/?term={encoded_game}"

            item_str = (
                f"・**{game}** (バズ判定: {count}件)\n"
                f"  └ 📊 再生/登録者数: **平均 {avg_ratio}倍**\n"
                f"  └ {reason}\n"
                f"  └ 🔗 [Steam/ストアで見る]({steam_url})"
            )
            game_list_items.append(item_str)

        game_list_str = "\n\n".join(game_list_items)

        content = (
            f"🔥 **【YouTube】今バズっているゲームタイトル（登録者超え抽出）**\n\n"
            f"直近1週間で**「チャンネル登録者数以上の再生数を出している動画（※切り抜き除外）」**から検出したタイトルです：\n\n"
            f"{game_list_str}\n\n"
            f"*※「話題の新作」は即動画化、「定番ロングヒット」は単発の穴場企画として重宝します！*"
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

    top_games = extract_game_data(viral_video_pool)
    send_discord_notification(top_games)


if __name__ == "__main__":
    main()
