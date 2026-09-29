from pathlib import Path

from app.platforms.x.client import _x_count


def test_x_profile_count_parser_supports_common_compact_formats():
    assert _x_count("1,234 Followers") == 1234
    assert _x_count("12.5K") == 12_500
    assert _x_count("3.2万") == 32_000
    assert _x_count("") == 0


def test_x_account_hub_frontend_is_wired():
    index = Path("app/web/index.html").read_text(encoding="utf-8")
    js = Path("app/web/app.js").read_text(encoding="utf-8")

    assert 'data-tab="hub"' in index
    assert 'id="x-engagement-card"' not in index
    assert 'id="hub-dm-hint"' in index
    assert 'id="dm-composer"' in index
    assert 'id="stats-view-head"' in index
    assert 'PLATFORM === "x" ? "https://x.com/messages"' in js
    assert 'if (platform === "x") return "https://x.com/i/web/status/" + id;' in js
    assert 'w.platform === "x"' in js
    assert 'api("/api/x/relationship"' in js
    assert 'PLATFORM === "douyin" || PLATFORM === "x"' in js
    assert 'https://x.com/messages/${encodeURIComponent(DM_CONV)}' in js
    assert '$("dm-composer").classList.toggle("hidden", isX)' in js


def test_x_account_hub_backend_is_wired():
    main = Path("app/main.py").read_text(encoding="utf-8")
    client = Path("app/platforms/x/client.py").read_text(encoding="utf-8")

    assert "fetch_x_my_works" in main
    assert "fetch_x_relationships" in main
    assert "fetch_x_dm_conversations" in main
    assert "fetch_x_dm_history" in main
    assert 'if platform == "x":' in main
    assert 'OperationKind.READ_LIGHT' in main
    assert 'async def fetch_x_my_works' in client
    assert 'async def fetch_x_relationships' in client
    assert 'async def fetch_x_dm_conversations' in client
    assert 'async def fetch_x_dm_history' in client
