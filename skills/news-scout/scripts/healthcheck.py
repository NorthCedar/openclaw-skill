#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新闻源健康巡检 (News Source Health Check)
==========================================
功能：定期检查 RSS 源健康状态、安全性、多样性
输出：巡检报告 JSON + 可选的自动修复

使用方法:
    python3 healthcheck.py                    # 完整巡检
    python3 healthcheck.py --fix              # 巡检 + 自动禁用失效源
    python3 healthcheck.py --report-only      # 只输出报告不修改

巡检维度:
    1. 可用性 — 源是否返回有效内容（非 404/403/超时）
    2. 安全性 — 是否被投毒（异常内容比例、非 HTTPS、可疑域名）
    3. 多样性 — 地区/语言/类型分布是否均衡
"""

import json
import os
import sys
import time
import socket
from datetime import datetime, timezone
from collections import Counter

try:
    import feedparser
except ImportError:
    print(json.dumps({"error": "缺少 feedparser", "solution": "pip3 install feedparser"}))
    sys.exit(1)

# 配置
SOCKET_TIMEOUT = 10  # 秒
# 安全性检查：可疑关键词（标题中出现这些词比例过高则标记）
SPAM_KEYWORDS = [
    "casino", "viagra", "crypto airdrop", "free money", "click here",
    "赌博", "彩票", "代开发票", "刷单", "兼职日结"
]

# 多样性目标
DIVERSITY_TARGETS = {
    "region": {"global": 0.3, "china": 0.2, "us": 0.3},  # 最低比例
    "language": {"en": 0.4, "zh": 0.2},
}


def check_feed_health(feed_info):
    """检查单个源的健康状态"""
    result = {
        "name": feed_info["name"],
        "url": feed_info["url"],
        "status": "unknown",
        "response_time": None,
        "entries_count": 0,
        "http_status": None,
        "issues": [],
    }

    # HTTPS 检查
    if not feed_info["url"].startswith("https://"):
        result["issues"].append("non_https")

    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(SOCKET_TIMEOUT)

    start = time.time()
    try:
        d = feedparser.parse(feed_info["url"])
        elapsed = time.time() - start
        result["response_time"] = round(elapsed, 2)
        result["http_status"] = d.get("status", None)
        result["entries_count"] = len(d.entries)

        # 判断状态
        status_code = d.get("status", 0)
        if status_code in (404, 410):
            result["status"] = "dead"
            result["issues"].append("http_404_410")
        elif status_code == 403:
            result["status"] = "blocked"
            result["issues"].append("http_403")
        elif d.bozo and len(d.entries) == 0:
            result["status"] = "broken"
            result["issues"].append("parse_error")
        elif len(d.entries) == 0:
            result["status"] = "empty"
            result["issues"].append("no_entries")
        elif elapsed > 8:
            result["status"] = "slow"
            result["issues"].append("slow_response")
        else:
            result["status"] = "healthy"

        # 安全性检查：内容投毒检测
        if d.entries:
            spam_count = 0
            for entry in d.entries[:10]:
                title = (entry.get("title", "") or "").lower()
                if any(kw in title for kw in SPAM_KEYWORDS):
                    spam_count += 1
            spam_ratio = spam_count / min(len(d.entries), 10)
            if spam_ratio > 0.3:
                result["status"] = "poisoned"
                result["issues"].append(f"spam_ratio_{spam_ratio:.0%}")

    except socket.timeout:
        elapsed = time.time() - start
        result["response_time"] = round(elapsed, 2)
        result["status"] = "timeout"
        result["issues"].append("socket_timeout")
    except Exception as e:
        elapsed = time.time() - start
        result["response_time"] = round(elapsed, 2)
        result["status"] = "error"
        result["issues"].append(f"exception:{type(e).__name__}")
    finally:
        socket.setdefaulttimeout(old_timeout)

    return result


def check_diversity(sources_config):
    """检查源的多样性分布"""
    report = {"balanced": True, "issues": [], "distribution": {}}

    for category, feeds in sources_config.get("rss_feeds", {}).items():
        if not feeds:
            continue

        total = len(feeds)
        regions = Counter(f.get("region", "unknown") for f in feeds)
        languages = Counter(f.get("language", "unknown") for f in feeds)
        priorities = Counter(f.get("priority", "P2") for f in feeds)

        cat_report = {
            "total": total,
            "regions": dict(regions),
            "languages": dict(languages),
            "priorities": dict(priorities),
            "warnings": [],
        }

        # 检查地区集中度
        for region, count in regions.items():
            ratio = count / total
            if ratio > 0.7:
                cat_report["warnings"].append(
                    f"region_concentration: {region} = {ratio:.0%} (>70%)"
                )
                report["balanced"] = False

        # 检查语言集中度
        for lang, count in languages.items():
            ratio = count / total
            if ratio > 0.8:
                cat_report["warnings"].append(
                    f"language_concentration: {lang} = {ratio:.0%} (>80%)"
                )
                report["balanced"] = False

        # 检查是否缺少某个地区
        if category == "ai":
            if "china" not in regions:
                cat_report["warnings"].append("missing_region: china (AI应有国内视角)")
                report["balanced"] = False
            if "global" not in regions:
                cat_report["warnings"].append("missing_region: global (AI应有国际视角)")
                report["balanced"] = False
        elif category == "investing":
            if "us" not in regions:
                cat_report["warnings"].append("missing_region: us (投资应有美股视角)")
                report["balanced"] = False
            if "china" not in regions:
                cat_report["warnings"].append("missing_region: china (投资应有A股/港股视角)")
                report["balanced"] = False

        report["distribution"][category] = cat_report
        if cat_report["warnings"]:
            report["issues"].extend(
                [f"[{category}] {w}" for w in cat_report["warnings"]]
            )

    return report


def run_healthcheck(config_path, fix=False, report_only=False):
    """执行完整巡检"""
    # 加载配置
    with open(config_path, "r", encoding="utf-8") as f:
        sources = json.load(f)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config_path": config_path,
        "summary": {},
        "feeds": {},
        "diversity": {},
        "actions_taken": [],
    }

    # 1. 逐源健康检查
    all_results = {}
    for category, feeds in sources.get("rss_feeds", {}).items():
        category_results = []
        for feed in feeds:
            result = check_feed_health(feed)
            category_results.append(result)
            # 进度输出
            icon = {"healthy": "✅", "dead": "💀", "blocked": "🚫",
                    "broken": "⚠️", "empty": "📭", "slow": "🐌",
                    "timeout": "⏰", "poisoned": "☠️", "error": "❌"
                    }.get(result["status"], "?")
            print(
                f'{icon} {result["response_time"]:>5}s | {result["http_status"] or "N/A":>3} '
                f'| {result["entries_count"]:>3} entries | [{category}] {result["name"]}',
                file=sys.stderr,
            )
        all_results[category] = category_results

    # 2. 汇总统计
    total_feeds = 0
    healthy_count = 0
    unhealthy = []
    for category, results in all_results.items():
        for r in results:
            total_feeds += 1
            if r["status"] == "healthy":
                healthy_count += 1
            else:
                unhealthy.append(r)

    report["summary"] = {
        "total_feeds": total_feeds,
        "healthy": healthy_count,
        "unhealthy": len(unhealthy),
        "health_rate": f"{healthy_count/total_feeds:.0%}" if total_feeds else "N/A",
    }
    report["feeds"] = all_results

    # 3. 多样性检查
    report["diversity"] = check_diversity(sources)

    # 4. 自动修复（如果启用）
    if fix and not report_only:
        modified = False
        for category, results in all_results.items():
            feeds = sources["rss_feeds"][category]
            to_remove = []
            for r in results:
                if r["status"] in ("dead", "poisoned"):
                    to_remove.append(r["url"])
                    report["actions_taken"].append(
                        f"REMOVED [{category}] {r['name']} ({r['status']})"
                    )

            if to_remove:
                sources["rss_feeds"][category] = [
                    f for f in feeds if f["url"] not in to_remove
                ]
                modified = True

        if modified:
            # 更新 last_updated
            sources["_last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(sources, f, indent=4, ensure_ascii=False)
            report["actions_taken"].append(
                f"CONFIG UPDATED: {config_path}"
            )

    # 输出报告
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def main():
    import argparse

    parser = argparse.ArgumentParser(description="新闻源健康巡检")
    parser.add_argument("--fix", action="store_true", help="自动移除失效/投毒源")
    parser.add_argument("--report-only", action="store_true", help="只输出报告")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "resources", "news_sources.json")

    if not os.path.exists(config_path):
        print(json.dumps({"error": f"配置文件不存在: {config_path}"}))
        sys.exit(1)

    run_healthcheck(config_path, fix=args.fix, report_only=args.report_only)


if __name__ == "__main__":
    main()
