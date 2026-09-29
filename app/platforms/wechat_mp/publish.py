"""微信公众号发布引擎 (浏览器自动化 + mp.weixin.qq.com CGI 接口)。

支持：
1. 图文草稿 (article/text): 上传配图并保存，要求草稿ID与列表标题回读匹配。
2. 贴图、视频、播客使用各自的创作入口；保存后回读类型。
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
from .tietu_runtime import (
    BODY_SELECTOR, TITLE_SELECTOR, append_topics_via_cdp,
    apply_tietu_extras, replace_text_via_cdp,
)
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


MP_DRAFT_TYPES = {"article", "images", "video", "podcast"}


def _normalize_mp_type(media_type: str) -> str:
    value = (media_type or "").strip().lower()
    aliases = {"text": "article", "tietu": "images"}
    return aliases.get(value, value)


async def _is_tietu_editor(page) -> bool:
    """缺少任一可见贴图专用控件都不允许按贴图判定成功。"""
    try:
        await page.locator('.image-selector__add').first.wait_for(state="visible", timeout=10000)
        await page.locator('.share-text__input .ProseMirror').first.wait_for(state="visible", timeout=10000)
        return True
    except Exception:
        return False


async def _is_video_editor(page) -> bool:
    """视频草稿必须出现视频上传控件，避免静默落到文章/贴图编辑器。"""
    selectors = (
        'input[type="file"][accept*="video"]',
        '.video-upload input[type="file"]',
        '.video-upload__input input[type="file"]',
    )
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count():
                await locator.wait_for(state="attached", timeout=5000)
                return True
        except Exception:
            continue
    return False


async def _is_podcast_editor(page) -> bool:
    """播客入口使用 createType=7，不能把普通文章编辑器当成播客。"""
    if "createType=7" not in page.url:
        return False
    try:
        await page.locator('textarea#title:visible').first.wait_for(state="visible", timeout=10000)
        return True
    except Exception:
        return False


async def _insert_podcast_audio(page, file_path: str, title: str,
                                cover_path: str = "") -> str:
    """插入音频；平台要求同意音频上传服务规则时交给账号持有人处理。"""
    if not await page.locator('.js_insertaudio').count():
        return "missing_audio_editor: 播客编辑器未提供音频插入入口"
    await page.locator('.js_insertaudio').evaluate("element => element.click()")
    upload_button = page.get_by_role("button", name="上传音频", exact=True).first
    if not await upload_button.count():
        return "missing_audio_upload: 未找到音频上传入口"
    await upload_button.click()
    dialog = page.locator('.weui-desktop-dialog:visible').filter(has_text="音频上传服务规则").last
    checkbox = dialog.locator('input.weui-desktop-form__checkbox[type="checkbox"]').first
    if not await checkbox.count() or not await checkbox.is_checked():
        return "terms_confirmation_required: 请账号持有人先在公众号后台阅读并同意音频上传服务规则"
    audio_input = dialog.locator('input[type="file"][name="audio_id"]').first
    if not await audio_input.count():
        return "missing_audio_input: 音频上传控件未就绪"
    await audio_input.set_input_files(file_path)
    await dialog.locator('input[placeholder="填写标题"]').first.fill(title)
    if cover_path:
        cover_input = dialog.locator('input[type="file"][accept*="image"]').first
        if not await cover_input.count():
            return "missing_audio_cover_input: 播客封面上传控件未就绪"
        await cover_input.set_input_files(cover_path)
    else:
        avatar = dialog.get_by_text("使用账号头像", exact=True).first
        if await avatar.count():
            await avatar.click()
    await dialog.get_by_role("button", name="保存", exact=True).click()
    try:
        await dialog.wait_for(state="hidden", timeout=120000)
        picker = page.locator('.weui-desktop-dialog:visible').filter(has_text="插入音频").last
        await picker.get_by_text(title, exact=True).first.click(timeout=30000)
        await picker.get_by_role("button", name="插入", exact=True).click()
        await picker.wait_for(state="hidden", timeout=15000)
    except Exception:
        return "audio_upload_uncertain: 音频可能已上传，但未核实插入播客；请人工核对，禁止自动重试"
    return ""


async def _open_creation_editor(ctx, page, label: str):
    """从公众号首页按原生创作分类打开编辑器，返回新页或当前页。"""
    card = page.locator(
        f".new-creation__menu-item:has-text('{label}'), "
        f".new-creation__menu a:has-text('{label}')"
    ).first
    if await card.count() == 0:
        return None
    before_pages = list(ctx.pages)
    await card.click()
    for _ in range(20):
        await asyncio.sleep(0.5)
        new_pages = [p for p in ctx.pages if p not in before_pages]
        if new_pages:
            return new_pages[0]
        if "appmsg" in page.url or "video" in page.url:
            return page
    return None


async def _publish_mp_once(mgr: BrowserManager, identity: Identity,
                           storage_state_json: str, title: str, desc: str,
                           media_type: str = "article", media_paths: List[str] = None,
                           topics: str = "", location: str = "",
                           collection_name: str = "", cover_path: str = "",
                           publish_mode: str = "draft", claim_text: str = "个人观点",
                           enable_reward: bool = True, timeout_seconds: int = 180
                           ) -> Tuple[bool, str, str]:
    """发布/保存微信公众号作品。返回 (ok, result_url, error)。
    
    media_type:
      - "article" / "text": 文章草稿，将 desc 解析为 Markdown 富文本并上传配图；
      - "images": 贴图草稿；
      - "video": 视频消息草稿；
      - "podcast": 播客草稿，需一个音频文件。
    publish_mode:
      - "draft": 保存至草稿箱；
      - "publish": 此入口禁止自动发表。
    """
    if publish_mode != "draft":
        return False, "", "unsupported_operation: 此入口仅允许保存草稿，不允许发表"
    draft_type = _normalize_mp_type(media_type)
    if draft_type not in MP_DRAFT_TYPES:
        return False, "", "unsupported_media: 公众号草稿类型须为 article / images / video / podcast"
    is_tietu = draft_type == "images"
    is_video = draft_type == "video"
    is_podcast = draft_type == "podcast"
    is_article = draft_type == "article"
    title_max = 20 if is_tietu or is_podcast else 64
    label = {"article": "文章", "images": "贴图", "video": "视频", "podcast": "播客"}[draft_type]
    if not title.strip() or len(title.strip()) > title_max:
        return False, "", f"invalid_title: 公众号{label}标题须为1至{title_max}字"
    if (is_article or is_tietu) and not desc.strip():
        return False, "", f"invalid_content: 公众号{label}正文不能为空"
    files = [str(Path(p)) for p in (media_paths or [])]
    if is_video and len(files) != 1:
        return False, "", "missing_video: 公众号视频草稿需要且只能有1个视频文件"
    if is_podcast and (len(files) != 1 or Path(files[0]).suffix.lower() not in
                       {".mp3", ".m4a", ".wav", ".amr", ".wma"}):
        return False, "", "missing_audio: 公众号播客草稿需要且只能有1个音频文件"
    if is_tietu and not files:
        return False, "", "missing_images: 公众号贴图草稿至少需要1张图片"
    if is_article and not files and not cover_path:
        return False, "", "missing_cover: 公众号文章请选择封面图片"
    if any(not Path(p).is_file() for p in files) or (cover_path and not Path(cover_path).is_file()):
        return False, "", "missing_media: 公众号上传文件不存在"

    ctx = await mgr.open_headed(identity, reuse=True)
    page = await ctx.new_page()
    home_page = page
    submitted = False
    try:
        await page.set_viewport_size({"width": 1600, "height": 960})
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=40000)
        token, err = await _get_mp_token(page)
        if not token:
            try:
                await mgr.close_context(identity.key)
            except Exception:
                pass
            return False, "", "logged_out: 请重新登录公众号后台"

        cover_file = cover_path or (files[0] if files else "")
        if not cover_file and not files:
            return False, "", "missing_cover: 请选择图片或封面"

        # 按微信原生分类打开草稿编辑器：文章、贴图、视频、播客。
        if is_tietu:
            edit_page = await _open_creation_editor(ctx, page, "贴图")
            if edit_page is None:
                return False, "", "editor_mode_mismatch: 首页未找到或未打开贴图创作入口"
            page = edit_page
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(3500)
        elif is_video:
            edit_page = await _open_creation_editor(ctx, page, "视频")
            if edit_page is None:
                return False, "", "editor_mode_mismatch: 首页未找到或未打开视频创作入口"
            page = edit_page
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(3500)
            if not await _is_video_editor(page):
                return False, "", "editor_mode_mismatch: 未能进入公众号视频编辑器，中止保存以防错分类"
        elif is_podcast:
            edit_page = await _open_creation_editor(ctx, page, "播客")
            if edit_page is None:
                return False, "", "editor_mode_mismatch: 首页未找到或未打开播客创作入口"
            page = edit_page
            await page.locator('textarea#title:visible').first.wait_for(state="visible", timeout=20000)
            if not await _is_podcast_editor(page):
                return False, "", "editor_mode_mismatch: 未能进入公众号播客编辑器，中止保存以防错分类"
        else:
            edit_url = f"{BASE_URL}/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isNew=1&type=77&token={token}&lang=zh_CN"
            await page.goto(edit_url, wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(3500)

        # 监听保存草稿网络响应
        save_state = {"saved": False, "appmsg_id": ""}
        def on_response(res):
            u = res.url
            if submitted and "operate_appmsg" in u and ("sub=create" in u or "sub=update" in u):
                asyncio.create_task(handle_body(res))
        async def handle_body(res):
            try:
                text = await res.text()
                if "appMsgId" in text or "appmsgid" in text:
                    d = json.loads(text)
                    aid = saved_draft_id(d)
                    if aid:
                        save_state["saved"] = True
                        save_state["appmsg_id"] = aid
            except Exception:
                pass
        page.on("response", on_response)

        tags = " ".join("#" + tag.strip().lstrip("#") for tag in topics.split(",") if tag.strip())

        if is_tietu:
            # ── 图文/贴图模式 ──
            # 校验是否成功进入贴图编辑器，防止被微信静默降级为图文文章
            if not await _is_tietu_editor(page):
                return False, "", "editor_mode_mismatch: 未能进入公众号贴图编辑器(可能被微信降级为图文)，中止保存以防误存为文章"

            # 1. 注入图片
            img_inp = page.locator('.image-selector__add input[type="file"]').first
            if await img_inp.count():
                await img_inp.set_input_files(files or [cover_file])
                await page.wait_for_timeout(2500)
            else:
                return False, "", "missing_image_input: 贴图上传控件未就绪"

            # 2. 标题/正文使用 CDP 原生文本插入，复用批量贴图脚本中已验证的输入路径。
            short_t = title.strip()[:20]
            await replace_text_via_cdp(page, TITLE_SELECTOR, short_t)
            await replace_text_via_cdp(page, BODY_SELECTOR, desc.strip())

            # 3. 话题逐个输入并敲空格，让公众号编辑器识别为真正的话题链接。
            topic_links = await append_topics_via_cdp(page, topics)

            # 4. 合集/创作来源/赞赏保持 best-effort；它们失败不覆盖草稿本体保存。
            extras = await apply_tietu_extras(
                page, album_name=collection_name,
                claim_text=claim_text, enable_reward=enable_reward)
            log.info("公众号贴图附加项: topics=%s extras=%s", topic_links, extras)
        elif is_video:
            # ── 视频草稿模式 ──
            video_input = page.locator(
                'input[type="file"][accept*="video"], '
                '.video-upload input[type="file"], '
                '.video-upload__input input[type="file"]'
            ).first
            if not await video_input.count():
                return False, "", "missing_video_input: 视频上传控件未就绪"
            await video_input.set_input_files(files[0])
            await page.wait_for_timeout(2500)
            title_input = page.locator(
                '#js_title_main .ProseMirror:visible, '
                '.title-editor__input .ProseMirror:visible, '
                'textarea#title:visible, input#title:visible'
            ).first
            if await title_input.count():
                await title_input.fill(title.strip())
            desc_input = page.locator(
                '.share-text__input .ProseMirror:visible, '
                'textarea:visible'
            ).first
            if desc.strip() and await desc_input.count():
                await desc_input.fill((desc + (chr(10) * 2 + tags if tags else "")).strip())
            await page.wait_for_timeout(600)
        else:
            # ── 文章 / 播客正文 ──
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

            if is_podcast:
                audio_error = await _insert_podcast_audio(page, files[0], title.strip(), cover_path)
                if audio_error:
                    return False, "", audio_error
            else:
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
                if is_video:
                    # 视频类型必须能在草稿列表中回读为 appmsg_type=15；否则不宣称成功。
                    from .draft_safety import verify_saved_draft_type
                    if not await verify_saved_draft_type(page, token, draft_id, title, 15):
                        return False, "", "write_uncertain: 草稿已保存，但未核实为视频草稿；请人工核对，禁止自动重试"
                if is_podcast:
                    from .draft_safety import verify_saved_draft_type
                    if not await verify_saved_draft_type(page, token, draft_id, title, 7):
                        return False, "", "write_uncertain: 草稿已保存，但未核实为播客草稿；请人工核对，禁止自动重试"
                if is_tietu:
                    # 重开已保存草稿，不传 createType，避免以请求类型冒充实际类型。
                    await page.goto(
                        f"{BASE_URL}/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&appMsgId={draft_id}&token={token}&lang=zh_CN",
                        wait_until="domcontentloaded", timeout=40000)
                    if not await _is_tietu_editor(page):
                        return False, "", "write_uncertain: 草稿已保存，但未核实为贴图；请人工核对，禁止自动重试"
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
        if home_page is not page:
            await home_page.close()


async def publish_mp(mgr: BrowserManager, identity: Identity,
                     storage_state_json: str, title: str, desc: str,
                     media_type: str = "article", media_paths: List[str] = None,
                     topics: str = "", location: str = "",
                     collection_name: str = "", cover_path: str = "",
                     publish_mode: str = "draft", claim_text: str = "个人观点",
                     enable_reward: bool = True, timeout_seconds: int = 180
                     ) -> Tuple[bool, str, str]:
    """保存公众号草稿，并对整次浏览器执行施加硬超时。

    超时一律按 ``write_uncertain`` 处理：浏览器可能已经跨过保存点击边界，
    因此宁可要求人工核验，也不能把任务自动重放造成重复草稿。
    """
    try:
        return await asyncio.wait_for(
            _publish_mp_once(
                mgr, identity, storage_state_json, title, desc,
                media_type=media_type, media_paths=media_paths,
                topics=topics, location=location,
                collection_name=collection_name, cover_path=cover_path,
                publish_mode=publish_mode, claim_text=claim_text,
                enable_reward=enable_reward, timeout_seconds=timeout_seconds),
            timeout=max(0.1, float(timeout_seconds)),
        )
    except asyncio.TimeoutError:
        try:
            await mgr.close_context(identity.key)
        except Exception:
            pass
        return False, "", (
            f"write_uncertain: 公众号草稿执行超过 {timeout_seconds} 秒；"
            "浏览器任务已取消，请到草稿箱核对，禁止自动重试"
        )


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

