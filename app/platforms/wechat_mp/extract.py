"""微信公众平台 (WeChat Official Account / wechat_mp) 数据提取模块。

提供文章列表 (appmsg_list / freepublish)、留言 (comment)、账号资料 (self_profile) 的归一化解析。
"""
from __future__ import annotations

import json
import re
from typing import List, Optional

from ..douyin.extract import Aweme, MediaItem, safe_title  # noqa: F401


def _first(d: dict, *keys, default=None):
    if not isinstance(d, dict):
        return default
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def _to_int(v) -> int:
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        try:
            if s.endswith("万") or s.endswith("w") or s.endswith("W"):
                return int(float(s[:-1]) * 10000)
            return int(float(s))
        except (ValueError, TypeError):
            return 0
    return 0


def parse_mp_feed(item: dict, quality: str = "highest") -> Optional[Aweme]:
    """解析公众号已发表文章/草稿箱中的一条作品记录。"""
    if not isinstance(item, dict):
        return None

    appmsg_info = item.get("appmsg_info") or item.get("appmsgInfo") or {}
    if isinstance(appmsg_info, list) and appmsg_info:
        appmsg_info = appmsg_info[0]

    # 提取唯一标识 (appmsgid / publish_id / msgid / fileid)
    aid = str(_first(
        item, "appmsgid", "publish_id", "msgid", "fileid", "id", "article_id",
        default=""
    ) or _first(
        appmsg_info, "appmsgid", "publish_id", "msgid", "fileid", "id",
        default=""
    ) or "")

    if not aid:
        return None

    title = str(_first(
        item, "title", "digest", default=""
    ) or _first(
        appmsg_info, "title", "digest", default="无标题"
    ) or "无标题").strip()

    digest = str(_first(
        item, "digest", default=""
    ) or _first(
        appmsg_info, "digest", default=""
    ) or "").strip()

    desc = f"{title}\n{digest}".strip() if digest and digest != title else title

    create_time = _to_int(_first(
        item, "create_time", "update_time", "masssend_time", "time",
        default=0
    ) or _first(
        appmsg_info, "create_time", "update_time", "time", default=0
    ))
    if create_time > 100_000_000_000:
        create_time //= 1000

    author_name = str(_first(
        item, "author_name", "author", "nickname", "account_name",
        default=""
    ) or _first(
        appmsg_info, "author_name", "author", default=""
    ) or "").strip()

    cover_url = str(_first(
        item, "cover", "cdn_url", "thumb_url", "pic_cdn_url", "cover_url",
        default=""
    ) or _first(
        appmsg_info, "cover", "cdn_url", "thumb_url", default=""
    ) or "").strip()

    # 判断类型：appmsg_type 10 = 图片消息/贴图, 15 = 视频消息, 9 = 图文文章
    msg_type_code = _to_int(_first(item, "appmsg_type", "type", default=9))
    media_type = "images" if msg_type_code == 10 else ("video" if msg_type_code == 15 else "video")

    aw = Aweme(
        aweme_id=aid,
        desc=desc,
        create_time=create_time,
        author_name=author_name,
        media_type=media_type,
        cover=cover_url or None,
        platform="wechat_mp",
    )

    # 统计数据：阅读数、点赞数、在看数、分享数、留言数
    read_num = _to_int(_first(item, "read_num", "read_count", "readNum", default=0))
    like_num = _to_int(_first(item, "like_num", "like_count", "likeNum", "digg_count", default=0))
    old_like_num = _to_int(_first(item, "old_like_num", "oldLikeNum", "looking_num", default=0))
    comment_num = _to_int(_first(item, "comment_num", "comment_count", "commentNum", default=0))

    aw.like_count = like_num + old_like_num
    aw.comment_count = comment_num

    # 如果有封面图，挂载为媒体项
    if cover_url and cover_url.startswith("http"):
        aw.medias.append(MediaItem(url=cover_url, kind="image", ext="jpeg", index=0))

    # 如果是多图消息，解析 item.get("picture_list") / "cdn_urls"
    picture_list = item.get("picture_list") or item.get("img_list") or []
    if isinstance(picture_list, list):
        for idx, pic in enumerate(picture_list):
            purl = ""
            if isinstance(pic, dict):
                purl = _first(pic, "cdn_url", "url", "pic_url", default="")
            elif isinstance(pic, str):
                purl = pic
            if purl and purl.startswith("http") and purl != cover_url:
                aw.medias.append(MediaItem(url=purl, kind="image", ext="jpeg", index=idx + 1))

    return aw


def parse_mp_comment(raw: dict) -> Optional[dict]:
    """解析微信公众平台的一条留言。"""
    if not isinstance(raw, dict):
        return None
    cid = str(_first(raw, "comment_id", "id", "content_id", default="") or "")
    if not cid:
        return None

    content = str(_first(raw, "content", "text", "comment_text", default="") or "").strip()
    user_name = str(_first(raw, "nick_name", "user_name", "author", "nickname", default="") or "微信用户").strip()
    user_avatar = str(_first(raw, "logo_url", "head_img", "avatar", default="") or "").strip()
    like_count = _to_int(_first(raw, "like_num", "like_count", default=0))
    create_time = _to_int(_first(raw, "create_time", "time", default=0))
    if create_time > 100_000_000_000:
        create_time //= 1000

    reply = raw.get("reply") or {}
    reply_to = ""
    if isinstance(reply, dict):
        reply_to = str(_first(reply, "content", "text", default="") or "").strip()

    return {
        "comment_id": cid,
        "text": content,
        "user_nickname": user_name,
        "avatar": user_avatar,
        "like_count": like_count,
        "create_time": create_time,
        "reply_to": reply_to,
        "is_elected": bool(_to_int(_first(raw, "is_elected", "elected", default=0))),
        "is_top": bool(_to_int(_first(raw, "is_top", "top", default=0))),
        "raw_json": json.dumps(raw, ensure_ascii=False),
    }


def flatten_mp_comments(root_comments: list) -> list:
    """展平公众号留言列表。"""
    if not isinstance(root_comments, list):
        return []
    flat = []
    for c in root_comments:
        if isinstance(c, dict):
            flat.append(c)
            # 处理作者回复作为子评论或挂载
            reply_list = c.get("reply_list") or c.get("replies") or []
            if isinstance(reply_list, list):
                for r in reply_list:
                    if isinstance(r, dict):
                        flat.append(r)
    return flat


def parse_self_user(u: dict) -> dict:
    """把微信公众号账号资料归一成平台账号对象。"""
    if not isinstance(u, dict):
        return {}
    data = u.get("data") if isinstance(u.get("data"), dict) else u
    user_info = data.get("user_info") if isinstance(data.get("user_info"), dict) else data

    nickname = str(_first(
        user_info, "nickname", "nick_name", "account_name", "name", default=""
    ) or "").strip()

    gh_id = str(_first(
        user_info, "user_name", "gh_id", "original_id", "username", default=""
    ) or "").strip()

    alias = str(_first(
        user_info, "alias", "wechat_id", "wx_id", default=""
    ) or "").strip()

    fakeid = str(_first(
        user_info, "fakeid", "bizuin", "uin", "app_id", "appid", default=""
    ) or "").strip()

    avatar = str(_first(
        user_info, "head_img", "avatar", "logo_url", "icon", default=""
    ) or "").strip()

    follower_count = _to_int(_first(
        user_info, "total_user", "follower_count", "fans_count", "total_fans", default=0
    ))
    aweme_count = _to_int(_first(
        user_info, "appmsg_cnt", "masssend_cnt", "aweme_count", "article_count", default=0
    ))

    return {
        "nickname": nickname or "微信公众号",
        "sec_uid": fakeid or gh_id,
        "douyin_id": alias or gh_id or fakeid,
        "avatar": avatar,
        "follower_count": follower_count,
        "aweme_count": aweme_count,
    }

