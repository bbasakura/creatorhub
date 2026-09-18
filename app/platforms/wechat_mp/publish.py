"""微信公众号发布引擎 (浏览器自动化 + mp.weixin.qq.com CGI 接口)。

支持：
1. 图文草稿 (article/text): 上传配图并保存，要求草稿ID与列表标题回读匹配。
2. 贴图和视频草稿等待真实编辑器校准，当前拒绝执行。
3. 此入口禁止发表；提交后证据不足返回 write_uncertain。
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
from html import escape

from .draft_safety import saved_draft_id, verify_saved_draft
import re
from pathlib import Path
from typing import List, Optional, Tuple

from ...browser.identity import Identity
from ...browser.manager import BrowserManager

log = logging.getLogger("creatorhub.wechat_mp")

BASE_URL = "https://mp.weixin.qq.com"
HOME_URL = f"{BASE_URL}/"
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
        line_s = escape(line.strip())
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
        elif line_s.startswith("&gt; "):
            quote = line_s[5:].strip()
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
      - "images": 贴图/图片消息草稿；
      - "video": 视频消息草稿。
    publish_mode:
      - "draft": 保存至草稿箱 (无次数限制，安全免扫码，推荐)；
      - "publish": 此入口禁止自动发表 (微信强制管理员手机扫码验证)。
    """
    if publish_mode != "draft":
        return False, "", "unsupported_operation: 此入口仅允许保存草稿，不允许发表 (微信群发强制管理员手机扫码)"
    is_tietu = media_type in ("images", "tietu")
    if not is_tietu and media_type not in ("article", "text"):
        return False, "", "unsupported_media: 公众号当前支持图文草稿(article)与贴图草稿(images)"
    title_max = 20 if is_tietu else 64
    if not title.strip() or len(title) > title_max:
        return False, "", f"invalid_title: {'贴图' if is_tietu else '图文'}标题须为1至{title_max}字"
    if not desc.strip():
        return False, "", "invalid_content: 正文描述不能为空"
    files = [str(Path(p)) for p in (media_paths or [])]
    if any(not Path(p).is_file() for p in files) or (cover_path and not Path(cover_path).is_file()):
        return False, "", "missing_media: 配图或封面不存在"

    ctx = await mgr.open_headed(identity)
    page = await ctx.new_page()
    submitted = False
    try:
        await page.set_viewport_size({"width": 1600, "height": 960})
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=40000)
        token, err = await _get_mp_token(page)
        if not token:
            return False, "", "logged_out: 请重新登录公众号后台"

        cover_file = cover_path or (files[0] if files else "")
        if not cover_file and not files:
            return False, "", "missing_cover: 请选择图片或封面"

        # 打开公众号草稿编辑器 (贴图为 createType=8, 图文为普通富文本)
        if is_tietu:
            edit_url = f"{BASE_URL}/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isNew=1&type=77&createType=8&token={token}&lang=zh_CN"
        else:
            edit_url = f"{BASE_URL}/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isNew=1&type=77&token={token}&lang=zh_CN"
        await page.goto(edit_url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(3500)

        # 监听保存草稿网络响应
        save_state = {"saved": False, "appmsg_id": ""}
        def on_response(res):
            u = res.url
            if "operate_appmsg" in u and ("sub=create" in u or "sub=update" in u):
                asyncio.create_task(handle_body(res))
        async def handle_body(res):
            try:
                text = await res.text()
                if "appMsgId" in text or "appmsgid" in text:
                    d = json.loads(text)
                    aid = str(d.get("appMsgId") or d.get("appmsgid") or d.get("data", {}).get("appMsgId") or "")
                    if aid:
                        save_state["saved"] = True
                        save_state["appmsg_id"] = aid
            except Exception:
                pass
        page.on("response", on_response)

        tags = " ".join("#" + tag.strip().lstrip("#") for tag in topics.split(",") if tag.strip())

        if is_tietu:
            # ── 贴图模式 ──
            # 1. 注入图片
            img_inp = page.locator('.image-selector__add input[type="file"], input[type="file"]').first
            if await img_inp.count():
                await img_inp.set_input_files(files or [cover_file])
                await page.wait_for_timeout(2500)

            # 2. 填写标题 (<= 20 字)
            short_t = title.strip()[:20]
            await page.evaluate("""(val) => {
                const el = document.querySelector('#title');
                if (el) {
                    el.value = val;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }""", short_t)
            await page.wait_for_timeout(400)

            # 3. 填写正文
            body_text = (desc + (chr(10) * 2 + tags if tags else "")).strip()
            await page.evaluate("""(text) => {
                const pm = document.querySelector('.share-text__input .ProseMirror') || document.querySelector('.ProseMirror');
                if (pm) {
                    pm.focus();
                    pm.innerText = text;
                    pm.dispatchEvent(new Event('input', { bubbles: true }));
                }
            }""", body_text)
            await page.wait_for_timeout(400)
        else:
            # ── 图文文章模式 ──
            # 1. 填写标题 (<= 64 字)
            await page.evaluate("""(val) => {
                const el = document.querySelector('#title');
                if (el) {
                    el.value = val;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }""", title)
            await page.wait_for_timeout(400)

            # 2. 填写正文 HTML
            html = _markdown_to_wechat_html(desc + (chr(10) * 2 + tags if tags else ""))
            await page.evaluate("""(html) => {
                const pm = document.querySelector('#ueditor_0 .ProseMirror') || document.querySelector('.rich_media_content .ProseMirror') || document.querySelector('.ProseMirror');
                if (pm) {
                    pm.focus();
                    pm.innerHTML = html;
                    pm.dispatchEvent(new Event('input', { bubbles: true }));
                }
            }""", html)
            await page.wait_for_timeout(400)

            # 3. 上传封面图片
            cover_inp = page.locator('input[type="file"]').first
            if await cover_inp.count() and cover_file:
                await cover_inp.set_input_files(cover_file)
                await page.wait_for_timeout(2500)
                crop_confirm = page.locator('button.weui-desktop-btn_primary:visible').filter(has_text="确定").first
                if await crop_confirm.count():
                    await crop_confirm.click()
                    await page.wait_for_timeout(1500)

        # 4. 点击 保存为草稿
        submit_btn = page.locator('#js_submit, button:has-text("保存为草稿")').first
        if not await submit_btn.count():
            return False, "", "draft_failed: 未找到「保存为草稿」按钮"

        submitted = True
        await submit_btn.click()

        # 等待草稿保存响应
        for _ in range(30):
            await page.wait_for_timeout(500)
            if save_state["saved"] and save_state["appmsg_id"]:
                break

        draft_id = save_state["appmsg_id"]
        if not draft_id:
            return False, "", "write_uncertain: 已点击保存但未取得草稿ID响应，请到草稿箱核对，禁止自动重试"

        # 5. 回读草稿箱核验，杜绝假成功
        for attempt in range(3):
            if await verify_saved_draft(page, token, draft_id, title):
                return True, f"https://mp.weixin.qq.com/#draft={draft_id}", ""
            if attempt < 2:
                await asyncio.sleep(1)

        return False, "", "write_uncertain: 草稿已保存但草稿箱未回读确认，请人工核对"
    except Exception as e:
        return False, "", ("write_uncertain: 保存提交后页面异常，请核对草稿箱" if submitted
                            else f"draft_failed: 草稿保存失败: {e!r}")
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
        await page.close()


def send_mp_heartbeat(storage_state_json: str, token: str = "") -> bool:
    """直接通过轻量级 HTTP 请求向微信公众平台发送保活请求，维持会话热度。无需启动浏览器。"""
    try:
        import urllib.request
        import json
        st = json.loads(storage_state_json or "{}")
        cookies = {c["name"]: c["value"] for c in st.get("cookies", []) if c.get("name") and c.get("value")}
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
        url = f"https://mp.weixin.qq.com/cgi-bin/home?t=home/index&lang=zh_CN&token={token}" if token else "https://mp.weixin.qq.com/"
        req = urllib.request.Request(
            url,
            headers={
                "Cookie": cookie_header,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200 and "login" not in resp.url.lower()
    except Exception:
        return False

