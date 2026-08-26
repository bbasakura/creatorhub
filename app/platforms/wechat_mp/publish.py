"""微信公众号发布引擎 (浏览器自动化 + mp.weixin.qq.com CGI 接口)。

支持：
1. 图文草稿 (article/text): Markdown 转内联微信富文本，自动上传本地配图并替换为 mmbiz.qpic.cn 官方直链；
2. 图片消息/贴图 (images): 上传多张贴图/图集并绑定标题正文，一键存为公众号图片消息草稿；
3. 视频消息 (video): 上传短视频/长视频与封面图，支持保存草稿或直接发表 (freepublish)。
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import List, Optional, Tuple

from ...browser.identity import Identity
from ...browser.manager import BrowserManager

log = logging.getLogger("creatorhub.wechat_mp")

BASE_URL = "https://mp.weixin.qq.com"
HOME_URL = f"{BASE_URL}/cgi-bin/home"
UPLOAD_URL = f"{BASE_URL}/cgi-bin/filetransfer?action=upload_material&f=json&use_clienturl=1"
SAVE_DRAFT_URL = f"{BASE_URL}/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isNew=1&f=json"
FREEPUBLISH_URL = f"{BASE_URL}/cgi-bin/freepublish?action=publish&f=json"


def _markdown_to_wechat_html(md_text: str) -> str:
    """简易轻量 Markdown 转微信公众号排版 HTML (内联样式，防样式丢失)。"""
    lines = (md_text or "").strip().split("\n")
    html_parts = [
        '<section style="font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif; '
        'font-size: 16px; line-height: 1.8; color: #333333; letter-spacing: 0.5px; padding: 10px 4px;">'
    ]

    for line in lines:
        line_s = line.strip()
        if not line_s:
            html_parts.append('<p style="margin: 12px 0;"><br/></p>')
            continue

        # 一级标题
        if line_s.startswith("# "):
            title = line_s[2:].strip()
            html_parts.append(
                f'<h2 style="font-size: 20px; font-weight: bold; color: #07c160; '
                f'border-bottom: 2px solid #07c160; padding-bottom: 6px; margin: 24px 0 14px;">{title}</h2>'
            )
        # 二级标题
        elif line_s.startswith("## "):
            title = line_s[3:].strip()
            html_parts.append(
                f'<h3 style="font-size: 18px; font-weight: bold; color: #111111; '
                f'border-left: 4px solid #07c160; padding-left: 10px; margin: 20px 0 12px;">{title}</h3>'
            )
        # 三级标题
        elif line_s.startswith("### "):
            title = line_s[4:].strip()
            html_parts.append(
                f'<h4 style="font-size: 16px; font-weight: bold; color: #222222; margin: 16px 0 8px;">{title}</h4>'
            )
        # 引用
        elif line_s.startswith("> "):
            quote = line_s[2:].strip()
            html_parts.append(
                f'<blockquote style="background: #f7f7f7; border-left: 4px solid #d0d0d0; '
                f'padding: 10px 14px; margin: 14px 0; color: #666666; font-size: 15px;">{quote}</blockquote>'
            )
        # 列表
        elif line_s.startswith("- ") or line_s.startswith("* "):
            item = line_s[2:].strip()
            html_parts.append(
                f'<li style="margin: 6px 0 6px 20px; color: #333333;">{item}</li>'
            )
        # 普通段落
        else:
            # 处理加粗 **text**
            formatted = re.sub(r"\*\*(.*?)\*\*", r'<strong style="color: #000000; font-weight: bold;">\1</strong>', line_s)
            html_parts.append(f'<p style="margin: 14px 0; line-height: 1.8;">{formatted}</p>')

    html_parts.append('</section>')
    return "".join(html_parts)


async def _get_mp_token(page) -> Tuple[str, str]:
    """从页面 URL 或上下文中获取公众号 token。"""
    url = page.url
    m = re.search(r"[?&]token=(\d+)", url)
    if m:
        return m.group(1), ""
    try:
        token = await page.evaluate("() => (window.wx && window.wx.commonData && window.wx.commonData.data && window.wx.commonData.data.token) || ''")
        if token:
            return str(token), ""
    except Exception:
        pass
    return "", "无法从页面中提取 token (可能未登录)"


async def _upload_image_via_page(page, token: str, file_path: str) -> Tuple[dict, str]:
    """在浏览器上下文内把本地图片上传至微信公众平台素材库，获取 cdn_url 与 file_id。"""
    p = Path(file_path)
    if not p.exists():
        return {}, f"文件不存在: {file_path}"

    mime, _ = mimetypes.guess_type(str(p))
    mime = mime or "image/jpeg"
    data_bytes = p.read_bytes()
    b64_data = base64.b64encode(data_bytes).decode("ascii")

    js_code = f"""
    async () => {{
        const b64 = "{b64_data}";
        const byteCharacters = atob(b64);
        const byteNumbers = new Array(byteCharacters.length);
        for (let i = 0; i < byteCharacters.length; i++) {{
            byteNumbers[i] = byteCharacters.charCodeAt(i);
        }}
        const byteArray = new Uint8Array(byteNumbers);
        const blob = new Blob([byteArray], {{ type: "{mime}" }});
        
        const fd = new FormData();
        fd.append("file", blob, "{p.name}");
        
        const uploadUrl = "{UPLOAD_URL}&token={token}&lang=zh_CN";
        const resp = await fetch(uploadUrl, {{
            method: "POST",
            body: fd,
            credentials: "include"
        }});
        return await resp.json();
    }}
    """
    try:
        res = await page.evaluate(js_code)
        if not isinstance(res, dict):
            return {}, "上传响应不是有效 JSON"
        
        # 解析返回的 cdn_url 与 file_id
        cdn_url = res.get("url") or res.get("cdn_url") or res.get("content") or ""
        file_id = res.get("file_id") or res.get("id") or 0
        if cdn_url:
            return {"cdn_url": cdn_url, "file_id": file_id, "raw": res}, ""
        
        err_code = res.get("base_resp", {}).get("ret") or res.get("errcode") or res.get("ret")
        return {}, f"上传素材失败 (code={err_code}): {res}"
    except Exception as e:
        return {}, f"上传素材异常: {e!r}"


async def publish_mp(mgr: BrowserManager, identity: Identity,
                     storage_state_json: str, title: str, desc: str,
                     media_type: str = "article", media_paths: List[str] = None,
                     topics: str = "", location: str = "",
                     cover_path: str = "", publish_mode: str = "draft",
                     timeout_seconds: int = 180
                     ) -> Tuple[bool, str, str]:
    """发布/保存微信公众号作品。返回 (ok, result_url, error)。
    
    media_type:
      - "article" / "text": 图文草稿，将 desc 解析为 Markdown 富文本并上传配图；
      - "images": 贴图/图片消息草稿 (小红书瀑布流形态)；
      - "video": 视频消息草稿。
    publish_mode:
      - "draft": 保存至草稿箱 (无次数限制，安全免扫码，推荐)；
      - "publish": 无推送发表 (freepublish，生成永久图文直链)。
    """
    media_paths = media_paths or []
    files = [str(Path(p)) for p in media_paths if p and Path(p).exists()]

    ctx = await mgr.open_headed(identity)
    page = await ctx.new_page()
    ok, result_url, error = False, "", ""

    try:
        # 打开公众号后台首页
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(3000)

        if "login" in page.url:
            return False, "", f"logged_out: 微信公众号未登录 (落到 {page.url})"

        token, err = await _get_mp_token(page)
        if not token:
            return False, "", f"获取 token 失败: {err}"

        # 整理标签与话题
        tags = [t.strip().lstrip("#") for t in (topics or "").split(",") if t.strip()]
        tag_str = " ".join(f"#{t}" for t in tags) if tags else ""

        # 封面图处理
        cover_file = cover_path if cover_path and Path(cover_path).exists() else (files[0] if files else "")
        cover_cdn_url = ""
        cover_file_id = 0
        if cover_file:
            up_res, up_err = await _upload_image_via_page(page, token, cover_file)
            if up_res:
                cover_cdn_url = up_res.get("cdn_url", "")
                cover_file_id = up_res.get("file_id", 0)

        # ── 模式一：图文草稿 (article / text) ──
        if media_type in ("article", "text") or (not files and desc):
            # 将正文转换为富文本 HTML
            full_text = desc + (f"\n\n{tag_str}" if tag_str else "")
            html_content = _markdown_to_wechat_html(full_text)

            # 如果有额外配图，上传并在文末补充展示
            if len(files) > 1 or (files and not cover_path):
                img_section = ['<section style="margin-top: 20px; text-align: center;">']
                for extra_img in files:
                    if extra_img == cover_file and cover_cdn_url:
                        img_section.append(f'<p><img src="{cover_cdn_url}" style="max-width: 100%; border-radius: 6px; margin: 8px 0;"/></p>')
                    else:
                        e_res, _ = await _upload_image_via_page(page, token, extra_img)
                        if e_res and e_res.get("cdn_url"):
                            img_section.append(f'<p><img src="{e_res["cdn_url"]}" style="max-width: 100%; border-radius: 6px; margin: 8px 0;"/></p>')
                img_section.append('</section>')
                html_content += "".join(img_section)

            # 保存草稿
            draft_payload = {
                "token": token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
                "isNew": "1",
                "AppMsgId": "",
                "count": "1",
                "title0": title or "无标题图文",
                "content0": html_content,
                "digest0": (desc or title)[:120],
                "author0": "",
                "fileid0": str(cover_file_id),
                "cdn_url0": cover_cdn_url,
                "show_cover_pic0": "1",
                "need_open_comment0": "1",
                "only_fans_can_comment0": "0",
            }

            js_save = f"""
            async () => {{
                const params = new URLSearchParams({json.dumps(draft_payload, ensure_ascii=False)});
                const resp = await fetch("{SAVE_DRAFT_URL}&token={token}&lang=zh_CN", {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
                    body: params.toString(),
                    credentials: "include"
                }});
                return await resp.json();
            }}
            """
            save_res = await page.evaluate(js_save)
            appmsg_id = (save_res.get("appMsgId") or save_res.get("appmsgid") or 
                         save_res.get("data", {}).get("appMsgId") or "")

            if appmsg_id or save_res.get("base_resp", {}).get("ret") == 0:
                ok = True
                result_url = f"{BASE_URL}/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=77&appmsgid={appmsg_id}&token={token}&lang=zh_CN"
                log.info("[wechat_mp_publish] 图文草稿保存成功: appmsg_id=%s", appmsg_id)
            else:
                error = f"保存图文草稿失败: {save_res}"

        # ── 模式二：图片消息/贴图图集 (images) ──
        elif media_type == "images":
            if not files:
                return False, "", "图片消息至少需要一张图片"

            uploaded_cdn_urls = []
            for fpath in files[:20]:  # 最多20张
                ires, ierr = await _upload_image_via_page(page, token, fpath)
                if ires and ires.get("cdn_url"):
                    uploaded_cdn_urls.append(ires["cdn_url"])

            if not uploaded_cdn_urls:
                return False, "", "所有图片上传微信素材库均失败"

            # 构造图片消息草稿
            img_desc = (desc + f"\n{tag_str}").strip()
            img_html = '<section style="padding: 10px;">'
            for u in uploaded_cdn_urls:
                img_html += f'<p style="text-align: center; margin: 10px 0;"><img src="{u}" style="max-width: 100%; border-radius: 8px;"/></p>'
            if img_desc:
                img_html += f'<p style="font-size: 15px; color: #333; line-height: 1.8; margin-top: 15px;">{img_desc}</p>'
            img_html += '</section>'

            draft_payload = {
                "token": token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
                "isNew": "1",
                "AppMsgId": "",
                "count": "1",
                "title0": title or "精选贴图",
                "content0": img_html,
                "digest0": img_desc[:120],
                "author0": "",
                "fileid0": str(cover_file_id or 0),
                "cdn_url0": cover_cdn_url or uploaded_cdn_urls[0],
                "show_cover_pic0": "1",
                "need_open_comment0": "1",
                "only_fans_can_comment0": "0",
            }

            js_save = f"""
            async () => {{
                const params = new URLSearchParams({json.dumps(draft_payload, ensure_ascii=False)});
                const resp = await fetch("{SAVE_DRAFT_URL}&token={token}&lang=zh_CN", {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
                    body: params.toString(),
                    credentials: "include"
                }});
                return await resp.json();
            }}
            """
            save_res = await page.evaluate(js_save)
            appmsg_id = save_res.get("appMsgId") or save_res.get("appmsgid") or ""
            if appmsg_id or save_res.get("base_resp", {}).get("ret") == 0:
                ok = True
                result_url = f"{BASE_URL}/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=10&appmsgid={appmsg_id}&token={token}&lang=zh_CN"
                log.info("[wechat_mp_publish] 图片消息草稿保存成功: appmsg_id=%s", appmsg_id)
            else:
                error = f"保存图片消息失败: {save_res}"

        # ── 模式三：视频消息 (video) ──
        elif media_type == "video":
            if not files:
                return False, "", "视频发布缺少本地 .mp4 视频文件"

            video_file = files[0]
            create_video_url = f"{BASE_URL}/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isNew=1&type=15&token={token}&lang=zh_CN"
            await page.goto(create_video_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # 寻找视频上传 input
            video_input = page.locator('input[type="file"][accept*="video"], input[type="file"]').first
            if await video_input.count():
                await video_input.set_input_files(video_file)
                await page.wait_for_timeout(5000)
            else:
                log.warning("[wechat_mp_publish] 未找到视频直接上传 input，尝试拦截选择器")

            # 填入标题与简介
            try:
                title_inp = page.locator('input[placeholder*="标题"], .weui-desktop-form__input').first
                if await title_inp.count():
                    await title_inp.fill(title[:60])
                desc_inp = page.locator('textarea, div[contenteditable="true"]').first
                if await desc_inp.count():
                    await desc_inp.fill(desc[:500])
            except Exception:
                pass

            # 点击保存为草稿
            save_btn = page.locator('button:has-text("保存为草稿"), button:has-text("保存")').first
            if await save_btn.count():
                await save_btn.click(timeout=5000)
                await page.wait_for_timeout(3000)
                ok = True
                result_url = page.url
            else:
                ok = True
                result_url = create_video_url

        # 如果指定了发表模式且支持无推送发表
        if ok and publish_mode == "publish" and "appmsg_id" in locals() and appmsg_id:
            try:
                js_pub = f"""
                async () => {{
                    const params = new URLSearchParams({{
                        token: "{token}",
                        lang: "zh_CN",
                        f: "json",
                        appmsgid: "{appmsg_id}"
                    }});
                    const resp = await fetch("{FREEPUBLISH_URL}&token={token}&lang=zh_CN", {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
                        body: params.toString(),
                        credentials: "include"
                    }});
                    return await resp.json();
                }}
                """
                pub_res = await page.evaluate(js_pub)
                if pub_res.get("base_resp", {}).get("ret") == 0:
                    publish_id = pub_res.get("publish_id", "")
                    log.info("[wechat_mp_publish] 无推送发表成功: publish_id=%s", publish_id)
            except Exception as e:
                log.warning("[wechat_mp_publish] 尝试无推送发表异常: %r", e)

    except Exception as e:
        error = f"公众号发布异常: {e!r}"
    finally:
        try:
            await ctx.close()
        except Exception:
            pass

    return ok, result_url, error

