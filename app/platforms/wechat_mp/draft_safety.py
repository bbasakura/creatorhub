"""Evidence checks shared by draft writers and offline tests."""
from __future__ import annotations


def saved_draft_id(response: dict) -> str:
    if not isinstance(response, dict):
        return ""
    if response.get("base_resp", {}).get("ret", 0) != 0:
        return ""
    value = (response.get("appMsgId") or response.get("appmsgid")
             or response.get("data", {}).get("appMsgId"))
    return str(value) if value else ""


def _matching_row(response: dict, draft_id: str, title: str) -> dict | None:
    if not draft_id or not isinstance(response, dict):
        return None
    if response.get("base_resp", {}).get("ret", 0) != 0:
        return None
    for row in response.get("app_msg_list", []):
        identity = str(row.get("app_msg_id") or row.get("appmsgid") or "")
        if identity != draft_id:
            continue
        info = row.get("appmsg_info") or row.get("multi_item") or []
        titles = [row.get("title", "")]
        if isinstance(info, list):
            titles.extend(item.get("title", "") for item in info if isinstance(item, dict))
        return row if title in titles else None
    return None


def matches_draft(response: dict, draft_id: str, title: str) -> bool:
    return _matching_row(response, draft_id, title) is not None


def matches_draft_type(response: dict, draft_id: str, title: str,
                       expected_type: int) -> bool:
    row = _matching_row(response, draft_id, title)
    if row is None:
        return False
    candidates = [
        row.get("appmsg_type"),
        row.get("type"),
        row.get("item_show_type"),
    ]
    info = row.get("appmsg_info") or row.get("multi_item") or []
    if isinstance(info, list):
        for item in info:
            if isinstance(item, dict):
                candidates.extend([
                    item.get("appmsg_type"),
                    item.get("type"),
                    item.get("item_show_type"),
                ])
    for value in candidates:
        if value in (None, ""):
            continue
        try:
            return int(value) == int(expected_type)
        except (TypeError, ValueError):
            continue
    return False


async def _fetch_drafts(page, token: str) -> dict:
    return await page.evaluate("""async ({token}) => {
        const query = new URLSearchParams({begin:'0',count:'20',type:'77',
            action:'list_ex',f:'json',lang:'zh_CN',token});
        const response = await fetch('/cgi-bin/appmsg?' + query,
            {credentials:'include'});
        if (!response.ok) return {};
        return await response.json();
    }""", {"token": token})


async def verify_saved_draft(page, token: str, draft_id: str, title: str) -> bool:
    if not draft_id:
        return False
    response = await _fetch_drafts(page, token)
    return matches_draft(response, draft_id, title)


async def verify_saved_draft_type(page, token: str, draft_id: str, title: str,
                                  expected_type: int) -> bool:
    if not draft_id:
        return False
    response = await _fetch_drafts(page, token)
    return matches_draft_type(response, draft_id, title, expected_type)
