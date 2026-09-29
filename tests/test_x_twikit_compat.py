import asyncio
from types import SimpleNamespace

from app.platforms.x.twikit_compat import (
    _normalize_user_payload,
    patch_twikit_transaction,
)


class _Soup:
    def __str__(self):
        return '{123:"ondemand.s",123:"abc123"}'


class _Asset:
    text = 'x[7], 16; y[12], 16; z[3], 16'

    def raise_for_status(self):
        pass


class _Session:
    async def request(self, **_kwargs):
        return _Asset()


class _Transaction:
    _creatorhub_compat_2026 = False
    home_page_response = None
    def validate_response(self, response):
        return response


def test_twikit_transaction_patch_supports_new_chunk_layout(monkeypatch):
    module = SimpleNamespace(
        x_client_transaction=SimpleNamespace(
            transaction=SimpleNamespace(ClientTransaction=_Transaction)))
    assert patch_twikit_transaction(module) is True
    tx = _Transaction()
    row, indices = asyncio.run(tx.get_indices(_Soup(), _Session(), {}))
    assert row == 7
    assert indices == [12, 3]


def test_user_payload_compat_fills_optional_legacy_fields_without_mutating_input():
    source = {
        "rest_id": "1",
        "legacy": {
            "entities": None,
            "withheld_in_countries": None,
        },
    }
    normalized = _normalize_user_payload(source)
    assert normalized["legacy"]["entities"]["description"]["urls"] == []
    assert normalized["legacy"]["pinned_tweet_ids_str"] == []
    assert normalized["legacy"]["withheld_in_countries"] == []
    assert source["legacy"]["entities"] is None
