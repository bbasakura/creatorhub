from pathlib import Path


def test_x_publish_form_is_platform_specific():
    index = Path("app/web/index.html").read_text(encoding="utf-8")
    js = Path("app/web/app.js").read_text(encoding="utf-8")

    assert 'id="pub-type-label"' in index
    assert 'id="pub-type-wrap"' in index
    assert 'id="pub-title-wrap"' in index
    assert 'id="pub-desc-label"' in index
    assert 'id="pub-queue-content-head"' in index

    assert '[["text", "无附件"], ["media", "媒体附件"]]' in js
    assert '[["article", "文章"], ["images", "贴图"], ["video", "视频"], ["podcast", "播客"]]' in js
    assert '$("pub-type-wrap").classList.toggle("hidden", isX)' in js
    assert '"帖子内容（与话题合计 ≤ 280 字符）"' in js
    assert '添加图片 / GIF / 视频（可选，合计最多 4 个）' in js
    assert 'function syncXPublishMediaType()' in js
    assert '请输入帖子内容或添加媒体' in js
    assert 'PLATFORM === "x" ? "写帖子内容，并可混合附加图片 / GIF / 视频，媒体合计最多 4 个"' in js


def test_custom_select_does_not_render_hidden_options():
    js = Path("app/web/app.js").read_text(encoding="utf-8")
    assert 'if (o.hidden || o.classList.contains("hidden")) return;' in js
