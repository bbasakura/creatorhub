"""Narrow compatibility patches for the optional twikit read backend.

Twikit 2.3.3 currently fails against X's newer webpack layout while upstream
PRs #411/#419/#432 are still unmerged.  Keep the workaround here instead of
mutating site-packages so it can be removed cleanly once upstream releases a
fixed version.
"""
from __future__ import annotations

import copy
import re


_ON_DEMAND_FILE_REGEX = re.compile(
    r'''[,{](\d+):["']ondemand\.s["']''', re.MULTILINE)
_ON_DEMAND_HASH_PATTERN = r'''[,{{]{chunk_id}:["']([0-9a-f]+)["']'''
_INDICES_REGEX = re.compile(r'''\[(\d+)\],\s*16''', re.MULTILINE)


def patch_twikit_transaction(module) -> bool:
    """Patch twikit's ClientTransaction index discovery in process.

    Returns True when the compatible implementation is installed.  The patch is
    intentionally scoped to the read-only twikit process and does not touch the
    CreatorHub BrowserManager write backend.
    """
    try:
        transaction = module.x_client_transaction.transaction
    except AttributeError:
        try:
            from twikit.x_client_transaction import transaction
        except Exception:
            return False

    cls = getattr(transaction, "ClientTransaction", None)
    if cls is None:
        return False
    if getattr(cls, "_creatorhub_compat_2026", False):
        return True

    async def get_indices(self, home_page_response, session, headers):
        response = self.validate_response(home_page_response) or self.home_page_response
        response_text = str(response)
        match = _ON_DEMAND_FILE_REGEX.search(response_text)
        if not match:
            raise Exception("Couldn't get ondemand.s chunk id")
        chunk_id = match.group(1)
        hash_match = re.search(
            _ON_DEMAND_HASH_PATTERN.format(chunk_id=chunk_id), response_text)
        if not hash_match:
            raise Exception(f"Couldn't find ondemand.s hash for chunk id {chunk_id!r}")
        file_hash = hash_match.group(1)
        url = (
            "https://abs.twimg.com/responsive-web/client-web/"
            f"ondemand.s.{file_hash}a.js"
        )
        asset = await session.request(method="GET", url=url, headers=headers)
        indices = [int(item.group(1)) for item in _INDICES_REGEX.finditer(asset.text)]
        if not indices:
            raise Exception("Couldn't get KEY_BYTE indices")
        return indices[0], indices[1:]

    cls.get_indices = get_indices
    cls._creatorhub_compat_2026 = True
    return True


def _normalize_user_payload(data):
    payload = copy.deepcopy(data or {})
    legacy = payload.get("legacy")
    if not isinstance(legacy, dict):
        return payload
    entities = legacy.get("entities")
    if not isinstance(entities, dict):
        entities = {}
    description = entities.get("description")
    if not isinstance(description, dict):
        description = {}
    description["urls"] = description.get("urls") or []
    entities["description"] = description
    legacy["entities"] = entities
    legacy["pinned_tweet_ids_str"] = legacy.get("pinned_tweet_ids_str") or []
    legacy["withheld_in_countries"] = legacy.get("withheld_in_countries") or []
    return payload


def patch_twikit_user_models(module) -> bool:
    """Guard legacy User fields that X now legitimately omits."""
    patched = False
    for dotted in ("user", "guest.user"):
        target = module
        try:
            for part in dotted.split("."):
                target = getattr(target, part)
        except AttributeError:
            try:
                target = __import__(f"twikit.{dotted}", fromlist=["User"])
            except Exception:
                continue
        cls = getattr(target, "User", None)
        if cls is None:
            continue
        if getattr(cls, "_creatorhub_user_compat_2026", False):
            patched = True
            continue
        original = cls.__init__

        def compat_init(self, client, data, _original=original):
            return _original(self, client, _normalize_user_payload(data))

        cls.__init__ = compat_init
        cls._creatorhub_user_compat_2026 = True
        patched = True
    return patched
