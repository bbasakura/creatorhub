import json
import re
from pathlib import Path

import pytest

from app.browser.manager import cookie_string_to_state
from app.platforms.x import (
    XPostingEngine,
    XReplyEngine,
    compose_x_text,
    normalize_tweet_ref,
    normalize_x_handle,
)
from app.services.platform_capabilities import capability_for, media_types_for


def test_x_capabilities_cover_unified_mixed_media_composer():
    cap = capability_for("x")
    assert set(media_types_for("x")) == {"text", "media", "images", "video"}
    assert cap.default_visibility == "public"
    assert cap.media["media"].max_media == 4
    assert cap.media["images"].max_media == 4
    assert cap.media["video"].max_media == 1


def test_x_cookie_fallback_uses_x_domain():
    state = json.loads(cookie_string_to_state("auth_token=abc; ct0=xyz", "x"))
    assert {row["domain"] for row in state["cookies"]} == {".x.com"}
    assert {row["name"] for row in state["cookies"]} == {"auth_token", "ct0"}


def test_compose_x_text_appends_unique_topics():
    text = compose_x_text("开头", "正文", "AI, ai, 创作")
    assert text == "开头\n\n正文\n\n#AI #创作"


def test_compose_x_text_rejects_empty_and_overflow():
    with pytest.raises(ValueError, match="不能为空"):
        compose_x_text()
    assert compose_x_text(allow_empty=True) == ""
    with pytest.raises(ValueError, match="280"):
        compose_x_text(desc="x" * 281)


def test_normalize_tweet_ref_accepts_x_and_twitter_urls():
    expected = ("1234567890", "https://x.com/i/web/status/1234567890")
    assert normalize_tweet_ref("1234567890") == expected
    assert normalize_tweet_ref("https://x.com/user/status/1234567890?s=20") == expected
    assert normalize_tweet_ref("https://twitter.com/user/status/1234567890") == expected
    with pytest.raises(ValueError):
        normalize_tweet_ref("https://example.com/status/123")


def test_normalize_x_handle_accepts_handle_and_profile_url():
    assert normalize_x_handle("@sakurakk730") == (
        "sakurakk730", "https://x.com/sakurakk730")
    assert normalize_x_handle("https://twitter.com/OpenAI") == (
        "OpenAI", "https://x.com/OpenAI")
    with pytest.raises(ValueError):
        normalize_x_handle("https://x.com/OpenAI/status/123")
    with pytest.raises(ValueError):
        normalize_x_handle("https://example.com/OpenAI")


def test_x_generators_stay_inside_short_post_contract():
    post = XPostingEngine().generate_post("daily_greeting")
    assert XPostingEngine.validate_post(post)["valid"] is True
    reply = XReplyEngine(target_daily_replies=20).generate_micro_reply("今天终于跑通了！")
    assert 1 <= len(reply) <= 15


def test_x_frontend_contract_is_wired():
    index = Path("app/web/index.html").read_text(encoding="utf-8")
    js = Path("app/web/app.js").read_text(encoding="utf-8")
    assert "data-pf=\"x\"" in index
    assert "startXLogin()" in index
    assert 'data-tab="hub"' in index
    assert 'id="x-engagement-card"' not in index
    assert 'loginStartUrl("/api/login/x/start"' in js
    assert 'api("/api/x/reply"' in js
    assert 'api("/api/x/relationship"' in js
    assert "f.verified" in js
    assert "X 蓝V认证" in js
    assert 'id="x-following-verified"' in index
    assert 'id="x-following-mutual"' in index
    assert 'id="x-fan-following"' in index
    assert 'id="x-fan-followback-all"' in index
    assert 'id="x-followback-batches"' in index
    assert "startXFollowBackAll" in js
    assert 'action: "follow"' in js
    assert "selectFilteredFollows('following')" in index
    assert "selectFilteredFollows('fan')" in index
    assert "clearFollowSelection('fan')" in index
    assert 'id="x-fan-selected-count"' in index
    assert '(direction === "following" || direction === "fan")' in js
    assert "batchUnfollowSelected()" in index
    assert 'api("/api/account-actions/batch"' in js
    assert 'id="x-following-pagination"' in index
    assert 'id="x-fan-pagination"' in index
    assert "changeFollowPage('following',-1)" in index
    assert "setFollowPageSize('following',this.value)" in index
    assert "const FOLLOW_PAGE_SIZE = { following: 50, fan: 50 }" in js
    assert "pageRows = rows.slice(start, start + size)" in js
    assert 'id="x-unfollow-batches"' in index
    assert "/api/x/relationship-batches?account_id=" in js
    assert "controlXRelationshipBatch" in js
    assert 'id="x-growth-toggle"' not in index
    assert 'id="x-growth-status"' in index
    assert 'id="x-ops-growth-btn"' in index
    assert 'id="x-ops-remind-btn"' in index
    assert "toggleXGrowthCampaign" in js
    assert "/api/x/growth-campaign/start" in js
    assert "/api/x/growth-campaign/stop" in js
    assert "/api/x/growth-campaign?account_id=" in js
    assert 'data-hubtab="ops"' in index
    assert 'data-hubpanel="ops"' in index
    assert 'id="x-ops-dropdown"' not in index
    assert index.index('data-hubtab="stats"') < index.index('data-hubtab="ops"')
    assert "一键浇友" in index
    assert "一键催关" in index
    assert "一键串门" in index
    assert "一键发帖" in index
    assert "x-ops-action growth" in index
    assert "x-ops-action remind" in index
    assert "x-ops-action visit" in index
    assert "x-ops-action post" in index
    ops_start = index.index('data-hubpanel="ops"')
    works_start = index.index('data-hubpanel="myworks"')
    following_start = index.index('data-hubpanel="following"')
    fans_start = index.index('data-hubpanel="fans"')
    assert ops_start < index.index('id="x-growth-status"') < works_start
    assert ops_start < index.index('id="x-remind-status"') < works_start
    following_html = index[following_start:fans_start]
    assert "一键浇友" not in following_html
    assert "一键催关" not in following_html
    assert 'id="x-remind-status"' not in following_html
    assert "runXHubTool" in js
    assert "/api/x/post/one-click" in js
    assert 'id="x-ops-target-count"' in index
    assert "一键目标数" in index
    assert "一键催关不受限制" in index
    assert "getXOpsTargetCount" in js
    assert "target_count: target" in js
    assert "edge_ids: allCandidates.map" in js
    assert "slice(0, target)" in js
    assert "slice(0, 50)" not in js
    monitor = Path("app/engine/monitor.py").read_text(encoding="utf-8")
    assert 'batch.status != "active"' in monitor
    assert "should_pause_relationship_batch" in monitor
    assert 'SchedulerStage("x_growth", self._process_x_growth_campaigns)' in monitor
    assert 'SchedulerStage("x_post_campaign", self._process_x_post_campaigns)' in monitor
    assert "fetch_x_for_you_timeline" in monitor
    assert "growth_task_metadata" in monitor
    assert "_X_GROWTH_GAP_RANGE = (50, 70)" in monitor
    assert "_X_FOLLOWBACK_GAP_RANGE = (75, 105)" in monitor
    assert "_X_UNFOLLOW_GAP_RANGE = (50, 70)" in monitor
    assert "_X_REMIND_GAP_RANGE = (50, 70)" in monitor
    assert "_X_VISIT_GAP_RANGE = (270, 330)" in monitor
    assert "require_verified=bool(growth_meta.get(\"require_verified\"))" in monitor
    assert 'PLATFORM === "x"' in js
    assert "/api/x/timeline?account_id=" in js
    assert "handle: edge.sec_uid || edge.uid" in js
    main = Path("app/main.py").read_text(encoding="utf-8")
    assert '"x": "x.com"' in main
    assert "https://x.com/home" in main
    assert 'function syncXPublishMediaType()' in js


def test_x_sidebar_uses_growth_workflow_information_architecture():
    root = Path(__file__).resolve().parents[1]
    index = (root / "app/web/index.html").read_text(encoding="utf-8")
    js = (root / "app/web/app.js").read_text(encoding="utf-8")

    assert 'id="x-primary-nav"' in index
    assert 'data-tab="x-intel"' in index
    assert 'data-tab="x-ops"' in index
    assert 'data-tab="x-data"' in index
    assert index.index('data-tab="x-intel"') < index.index('data-tab="x-ops"')
    assert index.index('data-tab="x-ops"') < index.index('data-tab="queue"')
    assert index.index('data-tab="queue"') < index.index('data-tab="publish"')
    assert index.index('data-tab="publish"') < index.index('data-tab="hub"')
    assert index.index('data-tab="hub"') < index.index('data-tab="x-data"')
    assert index.count('class="card x-data-card"') == 4
    assert index.count('class="card x-intel-card"') >= 9
    assert 'data-hubtab="ops"' in index
    assert 'class="tab hidden" data-hubtab="ops"' in index
    assert 'id="hub-stats-tab"' in index
    assert 'const actualPanel = name === "x-data" ? "x-intel" : name === "x-ops" ? "hub" : name;' in js
    assert '["x-intel", "x-ops", "x-data"]' in js
    assert 'document.querySelectorAll(".nonx-only")' in js

    action_block = js[
        js.index("const X_TASK_QUEUE_ACTION_OPTIONS"):
        js.index("const X_TASK_QUEUE_STATUS_OPTIONS")
    ]
    status_block = js[
        js.index("const X_TASK_QUEUE_STATUS_OPTIONS"):
        js.index("const GENERIC_TASK_QUEUE_TYPE_OPTIONS")
    ]
    action_labels = re.findall(r'\["[^"]*", "([^"]+)"\]', action_block)
    status_labels = re.findall(r'\["[^"]*", "([^"]+)"\]', status_block)
    assert action_labels == [
        "全部任务", "一键浇友", "一键催关", "一键串门",
        "一键发帖", "一键回关", "一键取关", "其他任务",
    ]
    assert status_labels == [
        "活动任务", "等待执行", "正在执行", "正常冷却", "任务阻塞",
        "待审任务", "结果待定", "执行失败", "执行完成", "任务取消", "全部状态",
    ]
    assert all(len(label) == 4 for label in action_labels + status_labels)
