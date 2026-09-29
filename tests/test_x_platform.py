import json
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


def test_x_capabilities_cover_text_images_and_video():
    cap = capability_for("x")
    assert set(media_types_for("x")) == {"text", "images", "video"}
    assert cap.default_visibility == "public"
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
    assert "X 互动" in index
    assert 'loginStartUrl("/api/login/x/start"' in js
    assert 'api("/api/x/reply"' in js
    assert 'api("/api/x/relationship"' in js
    assert "xRelationship('follow')" in index
    assert "xRelationship('unfollow')" in index
    assert "/api/x/timeline?account_id=" in js
    main = Path("app/main.py").read_text(encoding="utf-8")
    assert '"x": "x.com"' in main
    assert "https://x.com/home" in main
    assert 'classList.toggle("hidden", textOnly)' in js
