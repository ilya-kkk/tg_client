#!/usr/bin/env python3
"""Run deferred Telegram lead campaign analysis through the local API.

This script is intentionally conservative: it processes channels one by one and
stops on the first Telegram flood-wait response.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


FULL_HEADER = [
    "rank",
    "title",
    "username",
    "url",
    "subscribers_count",
    "median_views_30",
    "view_rate",
    "posts_per_week",
    "comments_enabled",
    "median_comments_30",
    "comment_rate",
    "unique_commenters_30",
    "niche",
    "niche_fit_score",
    "monetization_signal_score",
    "business_fit_score",
    "campaign_score",
    "recommended_action",
    "reason",
    "suggested_ai_product",
]

OPPORTUNITY_HEADER = [
    "channel_title",
    "channel_username",
    "post_url",
    "date",
    "views",
    "comments_count",
    "reactions_count",
    "post_relevance_score",
    "opportunity_score",
    "pain_markers",
    "suggested_angle",
    "text_preview",
]

SEGMENT_KEYS = [
    ("online_school", ["online", "school", "онлайн", "школ", "егэ", "огэ", "getcourse", "геткурс"]),
    ("telegram_monetization", ["telegram", "телеграм", "mini", "бот", "ads", "реклама", "монет"]),
    ("ai_business", ["ai", "ии", "нейро", "agent", "агент"]),
    ("english_learning", ["english", "англий"]),
    ("career", ["career", "карьер", "собесед", "hr"]),
    ("sales", ["sales", "продаж"]),
    ("fitness_nutrition", ["fitness", "фитнес", "нутриц", "питани"]),
    ("psychology", ["psychology", "психолог", "саморефлекс"]),
    ("general_business", ["business", "бизнес", "эксперт", "запуск", "личный бренд", "продюс"]),
]


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: int = 120,
) -> tuple[int, dict[str, Any]]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(base_url.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return error.code, payload
    except URLError as error:
        return 0, {"detail": str(error)}


def request_text(base_url: str, path: str, timeout: int = 120) -> tuple[int, str]:
    request = Request(base_url.rstrip("/") + path, headers={"Accept": "text/csv"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")
    except URLError as error:
        return 0, str(error)


def flood_wait_seconds(payload: dict[str, Any]) -> int | None:
    text = str(payload.get("detail") or payload.get("message") or payload)
    if not re.search(r"flood|слишком много|try again|wait", text, re.IGNORECASE):
        return None
    match = re.search(r"(\d+)", text)
    if match:
        return int(match.group(1))
    return 0


def normalize_username(value: str) -> str:
    return value.strip().lstrip("@")


def load_queue(path: Path, limit: int | None = None) -> list[str]:
    usernames: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            username = normalize_username(row.get("username", ""))
            if username:
                usernames.append(username)
    seen: set[str] = set()
    deduped = []
    for username in usernames:
        key = username.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(username)
    return deduped[:limit] if limit else deduped


def load_queue_from_api(base_url: str, min_lead_score: int, limit: int | None) -> list[str]:
    status, payload = request_json(base_url, "/api/leads")
    if status != 200:
        raise RuntimeError(f"Failed to load /api/leads: {status} {payload}")
    leads = payload.get("leads") or []
    leads.sort(
        key=lambda item: (
            int(item.get("lead_score") or 0),
            bool(item.get("has_comments")),
            int(item.get("subscribers") or 0),
        ),
        reverse=True,
    )
    usernames = [
        normalize_username(item.get("username") or "")
        for item in leads
        if int(item.get("lead_score") or 0) >= min_lead_score and item.get("username")
    ]
    return usernames[:limit] if limit else usernames


def refresh_channels(args: argparse.Namespace, usernames: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "attempted": 0,
        "refreshed": [],
        "errors": [],
        "flood_wait_seconds": None,
    }

    for index, username in enumerate(usernames, 1):
        if args.dry_run:
            print(f"DRY RUN refresh {index}/{len(usernames)} @{username}")
            continue

        path = (
            f"/channels/{quote('@' + username, safe='@')}/refresh-metrics?"
            + urlencode({"session_id": args.session_id})
        )
        status, payload = request_json(args.base_url, path, method="POST", timeout=args.timeout)
        result["attempted"] += 1
        wait_seconds = flood_wait_seconds(payload)
        if wait_seconds is not None:
            result["flood_wait_seconds"] = wait_seconds
            print(f"STOP flood wait after @{username}: {wait_seconds} seconds")
            break
        if status == 200 and payload.get("success", True):
            result["refreshed"].append(username)
            print(f"OK refresh {index}/{len(usernames)} @{username}")
        else:
            result["errors"].append({"username": username, "status": status, "payload": payload})
            print(f"ERROR refresh {index}/{len(usernames)} @{username}: {status} {payload}")
        time.sleep(args.sleep_seconds)

    return result


def get_ranked(base_url: str, min_score: float = 0.0, action: str | None = None) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"sort": "campaign_score", "min_score": min_score}
    if action:
        query["recommended_action"] = action
    status, payload = request_json(base_url, "/channels/ranked?" + urlencode(query))
    if status != 200:
        raise RuntimeError(f"Failed to load ranked channels: {status} {payload}")
    return payload.get("channels") or []


def write_csv(path: Path, header: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in header})


def ranked_to_full_rows(channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for rank, item in enumerate(channels, 1):
        rows.append(
            {
                "rank": rank,
                "title": item.get("title"),
                "username": "@" + normalize_username(item.get("username") or ""),
                "url": item.get("url"),
                "subscribers_count": item.get("subscribers_count"),
                "median_views_30": item.get("median_views_30"),
                "view_rate": item.get("view_rate"),
                "posts_per_week": item.get("posts_per_week"),
                "comments_enabled": item.get("comments_enabled"),
                "median_comments_30": item.get("median_comments_30"),
                "comment_rate": item.get("comment_rate"),
                "unique_commenters_30": item.get("unique_commenters_30"),
                "niche": item.get("niche"),
                "niche_fit_score": "",
                "monetization_signal_score": "",
                "business_fit_score": "",
                "campaign_score": item.get("campaign_score"),
                "recommended_action": item.get("recommended_action"),
                "reason": item.get("reason"),
                "suggested_ai_product": "",
            }
        )
    return rows


def export_csv_from_api(args: argparse.Namespace, output_dir: Path) -> None:
    exports = [
        ("telegram_lead_analysis_full.csv", {"format": "csv", "min_score": 0}),
        (
            "telegram_lead_analysis_test_now.csv",
            {"format": "csv", "min_score": 8, "recommended_action": "test_now"},
        ),
        (
            "telegram_lead_analysis_watchlist.csv",
            {"format": "csv", "min_score": 6.5, "recommended_action": "watch"},
        ),
    ]
    for filename, query in exports:
        status, text = request_text(
            args.base_url,
            "/channels/export-campaign-analysis?" + urlencode(query),
            timeout=args.timeout,
        )
        if status != 200:
            raise RuntimeError(f"Failed to export {filename}: {status} {text}")
        (output_dir / filename).write_text(text, encoding="utf-8")


def collect_opportunity_posts(args: argparse.Namespace, channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in channels:
        username = normalize_username(item.get("username") or "")
        if not username:
            continue
        path = (
            f"/channels/{quote('@' + username, safe='@')}/opportunity-posts?"
            + urlencode({"session_id": args.session_id})
        )
        status, payload = request_json(args.base_url, path, timeout=args.timeout)
        wait_seconds = flood_wait_seconds(payload)
        if wait_seconds is not None:
            print(f"STOP opportunity posts flood wait after @{username}: {wait_seconds} seconds")
            break
        if status != 200:
            print(f"ERROR opportunity posts @{username}: {status} {payload}")
            continue
        for post in payload.get("posts") or []:
            rows.append(
                {
                    "channel_title": item.get("title"),
                    "channel_username": "@" + username,
                    "post_url": post.get("post_url"),
                    "date": post.get("date"),
                    "views": post.get("views"),
                    "comments_count": post.get("comments_count"),
                    "reactions_count": post.get("reactions_count"),
                    "post_relevance_score": post.get("post_relevance_score"),
                    "opportunity_score": post.get("opportunity_score"),
                    "pain_markers": post.get("pain_markers"),
                    "suggested_angle": post.get("suggested_angle"),
                    "text_preview": post.get("text_preview"),
                }
            )
        time.sleep(args.sleep_seconds)
    rows.sort(key=lambda item: float(item.get("opportunity_score") or 0), reverse=True)
    return rows


def segment_for(item: dict[str, Any]) -> str:
    text = f"{item.get('niche') or ''} {item.get('title') or ''}".lower()
    for segment, keys in SEGMENT_KEYS:
        if any(key in text for key in keys):
            return segment
    return "other"


def write_segment_summary(output_dir: Path, channels: list[dict[str, Any]]) -> None:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in channels:
        buckets[segment_for(item)].append(item)

    rows = []
    for segment, items in buckets.items():
        scores = [float(item.get("campaign_score") or 0) for item in items]
        best = max(items, key=lambda item: float(item.get("campaign_score") or 0))
        rows.append(
            {
                "niche": segment,
                "channels_count": len(items),
                "avg_campaign_score": round(mean(scores), 2) if scores else 0,
                "median_campaign_score": round(median(scores), 2) if scores else 0,
                "test_now_count": sum(1 for item in items if item.get("recommended_action") == "test_now"),
                "watch_count": sum(1 for item in items if item.get("recommended_action") == "watch"),
                "manual_review_count": sum(
                    1 for item in items if item.get("recommended_action") == "manual_review"
                ),
                "skip_count": sum(1 for item in items if item.get("recommended_action") == "skip"),
                "best_channel": best.get("title"),
                "best_score": best.get("campaign_score"),
            }
        )
    rows.sort(key=lambda item: (item["avg_campaign_score"], item["channels_count"]), reverse=True)
    write_csv(
        output_dir / "telegram_lead_analysis_segment_summary.csv",
        [
            "niche",
            "channels_count",
            "avg_campaign_score",
            "median_campaign_score",
            "test_now_count",
            "watch_count",
            "manual_review_count",
            "skip_count",
            "best_channel",
            "best_score",
        ],
        rows,
    )


def write_report(output_dir: Path, channels: list[dict[str, Any]], opportunity_rows: list[dict[str, Any]]) -> None:
    actions = defaultdict(int)
    for item in channels:
        actions[item.get("recommended_action") or "manual_review"] += 1
    best = max(channels, key=lambda item: float(item.get("campaign_score") or 0), default={})
    top_segment = ""
    if channels:
        segment_counts: dict[str, int] = defaultdict(int)
        for item in channels:
            segment_counts[segment_for(item)] += 1
        top_segment = max(segment_counts.items(), key=lambda item: item[1])[0]

    def table(items: list[dict[str, Any]], keys: list[str]) -> str:
        lines = ["| " + " | ".join(keys) + " |", "| " + " | ".join(["---"] * len(keys)) + " |"]
        for item in items:
            values = [str(item.get(key, "")).replace("|", "/").replace("\n", " ")[:140] for key in keys]
            lines.append("| " + " | ".join(values) + " |")
        return "\n".join(lines)

    top10 = [
        {
            "rank": index,
            "title": item.get("title"),
            "username": item.get("username"),
            "campaign_score": item.get("campaign_score"),
            "action": item.get("recommended_action"),
            "niche": item.get("niche"),
        }
        for index, item in enumerate(channels[:10], 1)
    ]
    test_now = [
        {
            "rank": index,
            "title": item.get("title"),
            "username": item.get("username"),
            "campaign_score": item.get("campaign_score"),
            "niche": item.get("niche"),
        }
        for index, item in enumerate(
            [item for item in channels if item.get("recommended_action") == "test_now"][:20],
            1,
        )
    ]
    opp = opportunity_rows[:20]

    text = f"""# Telegram Lead Search Analysis Report

## 1. Executive Summary

- всего каналов проанализировано: {len(channels)}
- test_now: {actions['test_now']}
- watch: {actions['watch']}
- manual_review: {actions['manual_review']}
- skip: {actions['skip']}
- лучший сегмент: {top_segment}
- лучший канал: {best.get('title', '')}
- лучший campaign_score: {best.get('campaign_score', '')}
- главный вывод: отчет построен из рассчитанных `/channels/ranked` метрик.

## 2. Top 10 Channels

{table(top10, ['rank', 'title', 'username', 'campaign_score', 'action', 'niche'])}

## 3. Channels to Test Now

{table(test_now, ['rank', 'title', 'username', 'campaign_score', 'niche'])}

## 4. Watchlist

См. `telegram_lead_analysis_watchlist.csv`.

## 5. Best Opportunity Posts

{table(opp, ['channel_title', 'channel_username', 'post_url', 'opportunity_score', 'suggested_angle'])}

## 6. Segment Insights

См. `telegram_lead_analysis_segment_summary.csv`.

## 7. Risks and Notes

- Возможны Telegram flood waits во время сбора.
- Комментарии могут быть отключены после расчета.
- Рекламные посты и старые просмотры могут искажать scoring.

## 8. Recommended Next Actions

1. Выбрать 10 каналов из `test_now`.
2. Выбрать по 2-3 opportunity posts на канал.
3. Подготовить черновики комментариев.
4. Запустить маленький тест.
5. Измерить переходы в профиль, реакции и ответы.
6. Обновить scoring после фактических результатов.
"""
    (output_dir / "telegram_lead_analysis_report.md").write_text(text, encoding="utf-8")


def export_analysis(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print("DRY RUN skip exports")
        return

    channels = get_ranked(args.base_url, min_score=0)
    export_csv_from_api(args, output_dir)

    full_rows = ranked_to_full_rows(channels)
    write_csv(output_dir / "telegram_lead_analysis_full.csv", FULL_HEADER, full_rows)

    skip_rows = [row for row in full_rows if row.get("recommended_action") == "skip"]
    write_csv(
        output_dir / "telegram_lead_analysis_skip.csv",
        ["title", "username", "url", "niche", "campaign_score", "main_reject_reason"],
        [
            {
                "title": row.get("title"),
                "username": row.get("username"),
                "url": row.get("url"),
                "niche": row.get("niche"),
                "campaign_score": row.get("campaign_score"),
                "main_reject_reason": row.get("reason"),
            }
            for row in skip_rows
        ],
    )

    manual_rows = [row for row in full_rows if row.get("recommended_action") == "manual_review"]
    write_csv(
        output_dir / "telegram_lead_analysis_manual_review.csv",
        ["title", "username", "url", "campaign_score", "missing_data", "why_manual_review", "what_to_check_manually"],
        [
            {
                "title": row.get("title"),
                "username": row.get("username"),
                "url": row.get("url"),
                "campaign_score": row.get("campaign_score"),
                "missing_data": "",
                "why_manual_review": row.get("reason"),
                "what_to_check_manually": "review latest posts/comments manually",
            }
            for row in manual_rows
        ],
    )

    opportunity_channels = [
        item for item in channels if item.get("recommended_action") in {"test_now", "watch"}
    ]
    opportunity_rows = collect_opportunity_posts(args, opportunity_channels)
    write_csv(output_dir / "telegram_lead_analysis_opportunity_posts.csv", OPPORTUNITY_HEADER, opportunity_rows)
    write_segment_summary(output_dir, channels)
    write_report(output_dir, channels, opportunity_rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--session-id", default="an")
    parser.add_argument("--queue-file", default="data/exports/telegram_lead_analysis_refresh_queue.csv")
    parser.add_argument("--output-dir", default="data/exports")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-lead-score", type=int, default=7)
    parser.add_argument("--sleep-seconds", type=float, default=10.0)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--export-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    queue_path = Path(args.queue_file)

    if args.export_only:
        export_analysis(args)
        return 0

    if queue_path.exists():
        usernames = load_queue(queue_path, args.limit)
    else:
        usernames = load_queue_from_api(args.base_url, args.min_lead_score, args.limit)

    if not usernames:
        print("No channels to refresh")
        return 0

    print(f"Channels queued: {len(usernames)}")
    result = refresh_channels(args, usernames)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result["flood_wait_seconds"] is None:
        export_analysis(args)
    else:
        print("Exports skipped because Telegram returned flood wait.")

    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
