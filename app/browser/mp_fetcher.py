"""微信公众号 Web 抓取 (浏览器自动化 + 拦截 mp.weixin.qq.com CGI 接口)，对标 channels_fetcher.py。

微信公众平台 (mp.weixin.qq.com) 数据接口挂载在 /cgi-bin/* 下，依赖 cookie 与 URL 中的 token 参数：
  - /cgi-bin/home 或 settingpage -> 账号基础资料、头像、关注者概要
  - /cgi-bin/appmsg?action=list_ex -> 图文列表与草稿箱
  - /cgi-bin/freepublish?action=get_publication_records -> 已发表图文与统计数据 (阅读数/点赞数/在看数)
  - /cgi-bin/comment?action=list -> 对应图文的留言与互动数据
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from .identity import Identity
from .manager import BrowserManager

log = logging.getLogger("creatorhub.wechat_mp")

BASE = "https://mp.weixin.qq.com"
HOME_URL = f"{BASE}/"
APPMSG_LIST_URL = f"{BASE}/cgi-bin/appmsg?begin=0&count=20&type=77&action=list_ex"
PUBLISHED_LIST_URL = f"{BASE}/cgi-bin/freepublish?action=get_publication_records&offset=0&count=20"
COMMENT_LIST_URL = f"{BASE}/cgi-bin/comment?action=list"


def _rf(d: dict, *keys, default=""):
    for k in keys:
        v = (d or {}).get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def _extract_token_from_url_or_obj(url: str, obj: dict = None) -> str:
    if url:
        m = re.search(r"[?&]token=(\d+)", url)
        if m:
            return m.group(1)
    if isinstance(obj, dict):
        t = obj.get("token") or obj.get("data", {}).get("token")
        if t:
            return str(t)
    return ""


async def fetch_mp_self_profile(mgr: BrowserManager, identity: Identity,
                                block_media: bool = False
                                ) -> Tuple[dict, str]:
    """获取公众号账号资料。打开公众号后台，提取昵称、头像、gh_id 及关注者概要。
    返回 (profile_dict, error)；error == "logged_out" 表示登录态失效。"""
    result: dict = {}
    error = ""
    page = await mgr.new_page(identity, block_media)

    try:
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3500)

        final_url = page.url
        if "login" in final_url:
            return {}, "logged_out"

        # 1. 尝试从页面全局 window.wx.commonData 中直接读取
        try:
            wx_data = await page.evaluate("() => (window.wx && window.wx.commonData && window.wx.commonData.data) || null")
            if isinstance(wx_data, dict) and wx_data.get("nick_name"):
                result = {
                    "nickname": wx_data.get("nick_name"),
                    "user_name": wx_data.get("user_name") or wx_data.get("user_name_original"),
                    "alias": wx_data.get("alias") or "",
                    "head_img": wx_data.get("head_img") or wx_data.get("logo_url"),
                    "fakeid": str(wx_data.get("uin") or wx_data.get("fakeid") or ""),
                    "token": str(wx_data.get("token") or ""),
                }
        except Exception:
            pass

        # 2. 兜底：从 DOM 节点中读取账号昵称和头像
        if not result or not result.get("nickname"):
            try:
                nick_el = page.locator(".weui-desktop_name, .acount_box-nickname, .weui-desktop-account__nickname, .account_name, .meta_content").first
                if await nick_el.count():
                    nick = (await nick_el.text_content() or "").strip()
                    if nick:
                        result["nickname"] = nick
                avatar_el = page.locator(".weui-desktop-account__thumb, .account_box-panel-head__thumb, .weui-desktop-account__avatar img, .account_avatar img").first
                if await avatar_el.count():
                    av = await avatar_el.get_attribute("src") or ""
                    if av:
                        result["head_img"] = av
            except Exception:
                pass

        # 3. 提取粉丝/文章统计数据 (如果有)
        try:
            token = _extract_token_from_url_or_obj(page.url, result)
            if token:
                result["token"] = token
                # 优先从页面用户数卡片读取
                user_num_el = page.locator(".weui-desktop-user_num, .user_num").first
                if await user_num_el.count():
                    num_text = (await user_num_el.text_content() or "").strip()
                    m = re.search(r"(\d[\d,]*)", num_text)
                    if m:
                        result["total_user"] = int(m.group(1).replace(",", ""))
                if not result.get("total_user"):
                    # 尝试调用粉丝分析概览
                    analysis_url = f"{BASE}/cgi-bin/user_analysis?action=trend&token={token}&lang=zh_CN&f=json"
                    js_fetch = f"""
                    async () => {{
                        try {{
                            const r = await fetch("{analysis_url}", {{ credentials: "include" }});
                            return await r.json();
                        }} catch (e) {{ return null; }}
                    }}
                    """
                    stat_data = await page.evaluate(js_fetch)
                    if isinstance(stat_data, dict) and stat_data.get("total_user"):
                        result["total_user"] = stat_data.get("total_user")
        except Exception:
            pass

    except Exception as e:
        error = f"{e!r}"
    finally:
        try:
            await page.close()
        except Exception:
            pass

    if not result and not error:
        error = "no_profile_data"
    return result, error


async def fetch_mp_works(mgr: BrowserManager, identity: Identity,
                         known_ids: Set[str], max_scrolls: int = 6,
                         settle_ms: int = 1800, block_media: bool = True
                         ) -> Tuple[List[dict], Optional[dict], str]:
    """打开公众号已发表/草稿列表，收集作品与互动数据。
    返回 (新作品列表, author, error)。"""
    collected: Dict[str, dict] = {}
    error = ""
    page = await mgr.new_page(identity, block_media)

    try:
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(settle_ms)

        if "login" in page.url:
            return [], None, "logged_out: 微信公众号未登录"

        token = _extract_token_from_url_or_obj(page.url)
        if not token:
            return [], None, "未能获取 token，无法拉取作品列表"

        # 1. 调用已发表文章接口 (get_publication_records)
        freepub_url = f"{BASE}/cgi-bin/freepublish?action=get_publication_records&offset=0&count=20&f=json&token={token}&lang=zh_CN"
        js_freepub = f"""
        async () => {{
            try {{
                const resp = await fetch("{freepub_url}", {{ credentials: "include" }});
                return await resp.json();
            }} catch (e) {{ return {{ error: String(e) }}; }}
        }}
        """
        pub_res = await page.evaluate(js_freepub)
        if isinstance(pub_res, dict) and "publish_list" in pub_res:
            plist = pub_res.get("publish_list") or []
            for item in plist:
                if isinstance(item, dict):
                    # publish_info 里包含文章元数据
                    pub_info_str = item.get("publish_info") or "{}"
                    try:
                        pub_info = json.loads(pub_info_str) if isinstance(pub_info_str, str) else pub_info_str
                        app_msg_list = pub_info.get("appmsgex") or pub_info.get("appmsg_info") or [pub_info]
                        for sub_msg in app_msg_list:
                            pid = str(sub_msg.get("appmsgid") or sub_msg.get("id") or item.get("publish_id") or "")
                            if pid:
                                sub_msg["publish_id"] = pid
                                sub_msg["create_time"] = sub_msg.get("create_time") or item.get("create_time") or 0
                                collected[pid] = sub_msg
                    except Exception:
                        pass

        # 2. 调用草稿箱/图文列表接口 (appmsg list_ex)
        appmsg_url = f"{BASE}/cgi-bin/appmsg?begin=0&count=20&type=77&action=list_ex&f=json&token={token}&lang=zh_CN"
        js_appmsg = f"""
        async () => {{
            try {{
                const resp = await fetch("{appmsg_url}", {{ credentials: "include" }});
                return await resp.json();
            }} catch (e) {{ return {{ error: String(e) }}; }}
        }}
        """
        appmsg_res = await page.evaluate(js_appmsg)
        if isinstance(appmsg_res, dict) and "app_msg_list" in appmsg_res:
            for item in appmsg_res.get("app_msg_list") or []:
                if isinstance(item, dict):
                    aid = str(item.get("app_msg_id") or item.get("appmsgid") or item.get("fileid") or "")
                    if aid and aid not in collected:
                        collected[aid] = item

    except Exception as e:
        error = f"拉取公众号作品列表异常: {e!r}"
    finally:
        try:
            await page.close()
        except Exception:
            pass

    new_items = [it for oid, it in collected.items() if oid not in known_ids]
    return new_items, None, error


async def fetch_mp_comments(mgr: BrowserManager, identity: Identity,
                            appmsg_id: str, known_cids: Set[str],
                            max_scrolls: int = 4, settle_ms: int = 1600,
                            block_media: bool = True
                            ) -> Tuple[List[dict], str]:
    """拉取某篇图文的留言与读者互动。"""
    collected: Dict[str, dict] = {}
    error = ""
    page = await mgr.new_page(identity, block_media)

    try:
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(settle_ms)
        if "login" in page.url:
            return [], "logged_out: 微信公众号未登录"

        token = _extract_token_from_url_or_obj(page.url)
        if not token:
            return [], "无法获取 token"

        comment_api_url = f"{BASE}/cgi-bin/comment?action=list&appmsgid={appmsg_id}&offset=0&limit=50&f=json&token={token}&lang=zh_CN"
        js_comment = f"""
        async () => {{
            try {{
                const resp = await fetch("{comment_api_url}", {{ credentials: "include" }});
                return await resp.json();
            }} catch (e) {{ return {{ error: String(e) }}; }}
        }}
        """
        c_res = await page.evaluate(js_comment)
        if isinstance(c_res, dict) and "comment" in c_res:
            for c in c_res.get("comment") or []:
                if isinstance(c, dict):
                    cid = str(c.get("comment_id") or c.get("id") or "")
                    if cid:
                        collected[cid] = c
    except Exception as e:
        error = f"拉取留言异常: {e!r}"
    finally:
        try:
            await page.close()
        except Exception:
            pass

    new_comments = [c for cid, c in collected.items() if cid not in known_cids]
    return new_comments, error


async def post_mp_comment(mgr: BrowserManager, identity: Identity,
                          appmsg_id: str, content: str,
                          reply_to_id: str = "", headed: bool = True,
                          settle_ms: int = 1800, timeout_ms: int = 12000
                          ) -> Tuple[bool, str]:
    """回复公众号图文下的读者留言。"""
    content = (content or "").strip()
    if not content:
        return False, "回复内容不能为空"

    ctx = await mgr.open_headed(identity) if headed else None
    page = await ctx.new_page() if ctx else await mgr.new_page(identity, block_media=False)

    try:
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(settle_ms)
        if "login" in page.url:
            return False, "logged_out: 微信公众号未登录"

        token = _extract_token_from_url_or_obj(page.url)
        if not token:
            return False, "无法获取 token"

        reply_url = f"{BASE}/cgi-bin/comment?action=reply&f=json&token={token}&lang=zh_CN"
        reply_payload = {
            "appmsgid": appmsg_id,
            "comment_id": reply_to_id,
            "content": content,
            "token": token,
            "lang": "zh_CN",
            "f": "json",
        }

        js_reply = f"""
        async () => {{
            const params = new URLSearchParams({json.dumps(reply_payload, ensure_ascii=False)});
            const resp = await fetch("{reply_url}", {{
                method: "POST",
                headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
                body: params.toString(),
                credentials: "include"
            }});
            return await resp.json();
        }}
        """
        res = await page.evaluate(js_reply)
        if res.get("base_resp", {}).get("ret") == 0:
            return True, ""
        return False, f"回复留言失败: {res}"
    except Exception as e:
        return False, f"回复留言异常: {e!r}"
    finally:
        try:
            if ctx:
                await ctx.close()
            else:
                await page.close()
        except Exception:
            pass

