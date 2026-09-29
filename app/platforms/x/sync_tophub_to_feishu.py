"""将 TopHub 实时热门题材智能转化并批量同步到飞书多维表格「推文备选题材库」."""

import os
import sys
import argparse
from typing import Dict, Any, List

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.platforms.x.tophub_crawler import TopHubCrawler
from app.platforms.x.posting_engine import XPostingEngine
from app.platforms.x.feishu_sync import XFeishuSync, TOPIC_TABLE_ID


def sync_hot_topics_to_feishu(
    limit_per_category: int = 10,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """采集 TopHub 热门题材，自动生成推文草稿并去重入库飞书."""
    crawler = TopHubCrawler()
    engine = XPostingEngine(crawler=crawler)
    sync = XFeishuSync()

    # 1. 抓取题材
    crawler.fetch_topics(force_refresh=force_refresh)

    categories = ["tech_ai", "workplace_career", "hot_buzz"]
    all_candidates: List[Dict[str, Any]] = []
    seen_titles = set()

    # 2. 读取飞书已有候选，避免重复添加
    existing_records = sync.get_candidate_topics(page_size=100)
    for rec in existing_records:
        title = rec.get("fields", {}).get("题材标题")
        if title:
            seen_titles.add(title.strip())

    print(f"[FeishuSync] 飞书现有题材记录: {len(seen_titles)} 条")

    # 3. 按分类提取 Top N
    for cat in categories:
        topics = crawler.get_topics_by_category(category=cat, limit=limit_per_category * 2)
        count = 0
        for t in topics:
            title = t.get("title", "").strip()
            if not title or title in seen_titles:
                continue

            seen_titles.add(title)
            # 生成推文草稿
            post_draft = engine.generate_post_from_topic(t)
            all_candidates.append({
                "title": title,
                "source": t.get("source", ""),
                "category": cat,
                "rank": t.get("rank", 0),
                "heat": t.get("heat", ""),
                "link": t.get("link", ""),
                "post_draft": post_draft,
                "status": "待选",
            })
            count += 1
            if count >= limit_per_category:
                break

    print(f"[FeishuSync] 本次新筛选出 {len(all_candidates)} 条精选备选题材，准备写入飞书...")

    # 4. 批量同步飞书
    if not all_candidates:
        return {"total": 0, "synced": 0, "message": "无新增题材需要同步"}

    res = sync.batch_record_candidate_topics(all_candidates)
    print(f"[FeishuSync] 同步完成: {res}")
    return res


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="同步 TopHub 热门题材到飞书多维表格")
    parser.add_argument("--limit", type=int, default=10, help="每个分类抽取的题材数量 (默认 10)")
    parser.add_argument("--refresh", action="store_true", help="强制刷新 TopHub 实时榜单")
    args = parser.parse_args()

    sync_hot_topics_to_feishu(limit_per_category=args.limit, force_refresh=args.refresh)
