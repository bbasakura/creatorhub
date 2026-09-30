from app.platforms.x.feishu_sync import XFeishuSync


def test_record_post_accepts_runtime_account_identity():
    sync = XFeishuSync(cfg_path="unused")
    captured = {}
    sync._api_request = lambda path, method="GET", body=None: (
        captured.update({"path": path, "method": method, "body": body})
        or {"code": 0}
    )
    assert sync.record_post(
        "hello", "https://x.com/test/status/1",
        account_nick="Tester", account_handle="tester",
    ) is True
    fields = captured["body"]["fields"]
    assert fields["账号昵称"] == "Tester"
    assert fields["Handle"] == "@tester"
    assert fields["动作"] == ["发帖"]


def test_record_relationship_maps_follow_and_unfollow_actions():
    sync = XFeishuSync(cfg_path="unused")
    rows = []
    sync._api_request = lambda path, method="GET", body=None: (
        rows.append(body["fields"]) or {"code": 0}
    )
    assert sync.record_relationship(
        target_nick="Alice", target_handle="@alice", action="follow") is True
    assert sync.record_relationship(
        target_nick="Bob", target_handle="bob", action="unfollow") is True
    assert rows[0]["动作"] == ["关注"]
    assert rows[0]["Handle"] == "@alice"
    assert rows[1]["动作"] == ["取关"]
    assert rows[1]["Handle"] == "@bob"
