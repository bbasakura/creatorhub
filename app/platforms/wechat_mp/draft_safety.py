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


def matches_draft(response: dict, draft_id: str, title: str) -> bool:
    if not draft_id or not isinstance(response, dict):
        return False
    if response.get("base_resp", {}).get("ret", 0) != 0:
        return False
    for row in response.get("app_msg_list", []):
        identity = str(row.get("app_msg_id") or row.get("appmsgid") or "")
        if identity != draft_id:
            continue
        info = row.get("appmsg_info") or row.get("multi_item") or []
        titles = [row.get("title", "")]
        if isinstance(info, list):
            titles.extend(item.get("title", "") for item in info if isinstance(item, dict))
        return title in titles
    return False


async def verify_saved_draft(page, token: str, draft_id: str, title: str) -> bool:
    if not draft_id:
        return False
    response = await page.evaluate("""async ({token}) => {
        const query = new URLSearchParams({begin:'0',count:'20',type:'77',
            action:'list_ex',f:'json',lang:'zh_CN',token});
        const response = await fetch('/cgi-bin/appmsg?' + query,
            {credentials:'include'});
        if (!response.ok) return {};
        return await response.json();
    }""", {"token": token})
    return matches_draft(response, draft_id, title)
