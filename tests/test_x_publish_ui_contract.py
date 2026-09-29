from pathlib import Path


def test_x_publish_form_is_platform_specific():
    index = Path("app/web/index.html").read_text(encoding="utf-8")
    js = Path("app/web/app.js").read_text(encoding="utf-8")

    assert 'id="pub-type-label"' in index
    assert 'id="pub-title-wrap"' in index
    assert 'id="pub-desc-label"' in index
    assert 'id="pub-queue-content-head"' in index

    assert '[["text", "纯文本"], ["images", "图片（1-4 张）"], ["video", "视频"]]' in js
    assert '[["article", "文章"], ["images", "贴图"], ["video", "视频"], ["podcast", "播客"]]' in js
    assert 'classList.toggle("hidden", isX)' in js
    assert '"帖子类型"' in js
    assert '"帖子内容（与话题合计 ≤ 280 字符）"' in js
    assert 'PLATFORM === "x" ? "发布纯文本、1-4 张图片或单个视频到 X"' in js


def test_custom_select_does_not_render_hidden_options():
    js = Path("app/web/app.js").read_text(encoding="utf-8")
    assert 'if (o.hidden || o.classList.contains("hidden")) return;' in js
