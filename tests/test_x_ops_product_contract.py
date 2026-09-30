import re
import tempfile
from pathlib import Path

import app.db as db
from app.services.x_ops_settings import (
    get_x_ops_target_count,
    normalize_x_ops_target_count,
    save_x_ops_target_count,
)


def _init_tmp():
    previous = db._engine
    tmp = tempfile.TemporaryDirectory()
    db.init_db(str(Path(tmp.name) / "x-ops-product.db"))
    return previous, tmp


def _restore(previous, tmp):
    if db._engine is not None:
        db._engine.dispose()
    db._engine = previous
    tmp.cleanup()


def test_x_ops_target_count_is_backend_persisted_and_clamped():
    previous, tmp = _init_tmp()
    try:
        assert get_x_ops_target_count(8) == 100
        assert save_x_ops_target_count(8, 37) == 37
        assert get_x_ops_target_count(8) == 37
        assert save_x_ops_target_count(8, 0) == 1
        assert save_x_ops_target_count(8, 999999) == 10000
        assert normalize_x_ops_target_count("bad") == 100
    finally:
        _restore(previous, tmp)


def test_x_ops_page_has_exactly_four_unified_actions_and_clean_relationship_pages():
    root = Path(__file__).resolve().parents[1]
    html = (root / "app/web/index.html").read_text(encoding="utf-8")

    ops_start = html.index('data-hubpanel="ops"')
    works_start = html.index('data-hubpanel="myworks"')
    following_start = html.index('data-hubpanel="following"')
    fans_start = html.index('data-hubpanel="fans"')
    dm_start = html.index('data-hubpanel="dm"')
    ops_html = html[ops_start:works_start]
    following_html = html[following_start:fans_start]
    fans_html = html[fans_start:dm_start]

    action_ids = re.findall(
        r'class="x-ops-action [^"]+" id="([^"]+)"', ops_html)
    assert action_ids == [
        "x-ops-growth-btn",
        "x-ops-remind-btn",
        "x-ops-visit-btn",
        "x-ops-post-btn",
    ]
    for label in ("一键浇友", "一键催关", "一键串门", "一键发帖"):
        assert label in ops_html

    for label in ("一键浇友", "一键催关", "一键串门", "一键发帖"):
        assert label not in following_html
    assert "一键回关" not in following_html

    for label in ("一键浇友", "一键催关", "一键串门", "一键发帖"):
        assert label not in fans_html
    assert 'id="x-fan-followback-all"' in fans_html
    assert "一键回关" in fans_html


def test_x_ops_target_controls_four_actions_but_not_remind():
    root = Path(__file__).resolve().parents[1]
    html = (root / "app/web/index.html").read_text(encoding="utf-8")
    js = (root / "app/web/app.js").read_text(encoding="utf-8")
    api = (root / "app/api/x.py").read_text(encoding="utf-8")
    main = (root / "app/main.py").read_text(encoding="utf-8")

    assert "一键催关不受限制" in html
    assert 'id="x-ops-target-count"' in html
    assert "/api/x/ops/settings" in js
    assert "creatorhub-x-oneclick-target" not in js
    assert "creatorhub-x-visit-target" not in js

    assert 'body: JSON.stringify({ account_id: +HUB_ACC, target_count: target })' in js
    assert "target_count: target" in js
    assert "const candidates = allCandidates.slice(0, target)" in js
    assert "const ids = sourceIds.slice(0, target)" in js

    assert "save_x_ops_target_count(body.account_id, body.target_count)" in api
    assert "[:target_count]" in api
    assert "_save_x_ops_target_count(body.account_id, body.target_count)" in main
    assert "len(specs) >= target_count" in main

    remind_start = js.index("async function startXRemindAll")
    remind_end = js.index("async function startXOneClickPost", remind_start)
    remind_js = js[remind_start:remind_end]
    assert "target_count" not in remind_js
    assert 'body: JSON.stringify({ account_id: +HUB_ACC })' in remind_js


def test_x_page_state_is_backend_authoritative_and_safe_mode_is_gone():
    root = Path(__file__).resolve().parents[1]
    html = (root / "app/web/index.html").read_text(encoding="utf-8")
    js = (root / "app/web/app.js").read_text(encoding="utf-8")
    api = (root / "app/api/x.py").read_text(encoding="utf-8")
    main = (root / "app/main.py").read_text(encoding="utf-8")
    monitor = (root / "app/engine/monitor.py").read_text(encoding="utf-8")
    intel = (root / "app/web/x_intel.js").read_text(encoding="utf-8")

    assert "/api/x/ops/state?account_id=" in js
    assert 'id="x-ops-state-source"' in html
    assert "状态来源：后端" in js
    assert "X_OPS_STATE.disabled" in js
    assert "refreshXOpsState(false)" in js

    assert '@router.get("/ops/state")' in api
    assert '"source": "backend"' in api
    assert '"disabled": {' in api
    assert '"growth": {' in api
    assert '"remind": remind_state' in api
    assert '"visit": {' in api
    assert '"post": {' in api
    assert '"followback": followback' in api

    combined = "\n".join((html, js, api, main, monitor, intel)).lower()
    assert "safe_mode" not in combined
    assert "safe mode" not in combined
