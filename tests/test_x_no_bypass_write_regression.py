import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LOW_LEVEL_WRITERS = {
    "publish_x": {
        "app/engine/monitor.py",
        "app/platforms/x/client.py",
    },
    "reply_x": {
        "app/engine/monitor.py",
        "app/platforms/x/client.py",
    },
    "set_x_following": {
        "app/engine/monitor.py",
        "app/platforms/x/relationship.py",
    },
}


def _runtime_python_files():
    for root in (ROOT / "app", ROOT / "scripts"):
        if root.exists():
            yield from root.rglob("*.py")


def test_low_level_x_writers_are_only_called_from_canonical_worker_or_adapter():
    violations = []
    for path in _runtime_python_files():
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            name = node.func.id
            allowed = LOW_LEVEL_WRITERS.get(name)
            if allowed is not None and rel not in allowed:
                violations.append(f"{rel}:{node.lineno}:{name}")
    assert violations == [], "direct X write bypass detected: " + ", ".join(violations)


def test_legacy_x_javascript_has_no_direct_send_controls():
    forbidden = ("tweetButtonInline", "sendBtn.click()", "postBtn.click()")
    for path in sorted((ROOT / "app" / "platforms" / "x").glob("*.js")):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path.relative_to(ROOT)} contains {token}"


def test_legacy_success_stamps_fail_closed():
    batch = (ROOT / "app" / "platforms" / "x" / "batch_replier.py").read_text(encoding="utf-8")
    stream = (ROOT / "app" / "platforms" / "x" / "stream_replier.py").read_text(encoding="utf-8")
    runner = (ROOT / "app" / "platforms" / "x" / "runner.py").read_text(encoding="utf-8")
    legacy_runner = (ROOT / "app" / "platforms" / "x" / "runner_unreciprocated.js").read_text(encoding="utf-8")

    assert "legacy X success stamping is disabled" in batch
    assert "legacy X success stamping is disabled" in stream
    assert "legacy X success hook is disabled" in runner
    assert "unreciprocated_manager.py record" not in legacy_runner
