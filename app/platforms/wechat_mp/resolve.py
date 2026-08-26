"""微信公众号 ID 与文章链接解析。对标 channels/resolve.py。

支持提取公众号 gh_id / 微信号 / __biz / appmsgid 以及公众平台文章链接 (mp.weixin.qq.com/s/...)。
"""
from __future__ import annotations

import re
from typing import Optional

# 微信公众号原始ID (gh_ 开头)
_GH_ID_RE = re.compile(r"\b(gh_[0-9a-zA-Z_]{12,})\b")
# 微信公众号短链 (mp.weixin.qq.com/s/...)
_MP_SHORT_URL_RE = re.compile(r"https?://mp\.weixin\.qq\.com/s/([0-9a-zA-Z_-]+)")
# 微信公众号长链参数 (__biz / mid / appmsgid / sn)
_MID_RE = re.compile(r"[?&](?:mid|appmsgid)=(\d+)")
_SN_RE = re.compile(r"[?&]sn=([0-9a-zA-Z]+)")
_BIZ_RE = re.compile(r"[?&]__biz=([0-9a-zA-Z_==]+)")
# 纯数字 appmsgid
_DIGIT_ID_RE = re.compile(r"^\d{8,22}$")
_BARE_GH_RE = re.compile(r"^gh_[0-9a-zA-Z_]{10,}$")


async def resolve_mp_user_id(text: str, user_agent: str = "") -> Optional[str]:
    """从文本或主页链接解析公众号原始 gh_id 或 fakeid。"""
    text = (text or "").strip()
    m = _GH_ID_RE.search(text)
    if m:
        return m.group(1)
    if _BARE_GH_RE.match(text):
        return text
    # 提取 __biz
    bm = _BIZ_RE.search(text)
    if bm:
        return bm.group(1)
    return None


async def resolve_mp_article_id(text: str, user_agent: str = "") -> Optional[str]:
    """从文章链接或文本提取文章 ID (appmsgid / short_code / sn)。"""
    text = (text or "").strip()
    if _DIGIT_ID_RE.match(text):
        return text
    # 尝试匹配 short code
    sm = _MP_SHORT_URL_RE.search(text)
    if sm:
        return sm.group(1)
    # 尝试提取 mid
    mm = _MID_RE.search(text)
    if mm:
        return mm.group(1)
    # 尝试提取 sn
    sn = _SN_RE.search(text)
    if sn:
        return sn.group(1)
    return None


def looks_like_article(text: str) -> bool:
    """判断输入更像「单篇图文/视频」(含有 /s/ 或 mid 或纯长数字) 还是「公众号账号」(gh_id)。"""
    text = (text or "").strip()
    if _MP_SHORT_URL_RE.search(text) or _MID_RE.search(text) or _DIGIT_ID_RE.match(text):
        return True
    if _GH_ID_RE.search(text) or _BARE_GH_RE.match(text):
        return False
    return "/s" in text or "appmsg" in text

