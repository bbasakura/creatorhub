from pathlib import Path


def test_douyin_verification_timeout_is_uncertain_after_submit():
    source = Path("app/platforms/douyin/publish.py").read_text(encoding="utf-8")
    assert "write_uncertain: 已进入抖音提交边界后触发人工验证" in source
    assert "禁止自动重试" in source
