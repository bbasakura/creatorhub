from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
from .secrets import protect, unprotect

ROOT = Path(__file__).resolve().parents[3] / "data" / "youtube"
API = "https://www.googleapis.com/youtube/v3"
REDIRECT = "http://127.0.0.1:8000/api/youtube/callback"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"


def _path(key):
    if not key or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in key):
        raise ValueError("Invalid credential reference")
    ROOT.mkdir(parents=True, exist_ok=True)
    return ROOT / (key + ".json")


def store(key, value):
    path = _path(key)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(protect(json.dumps(value).encode("utf-8")))
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def load(key):
    return json.loads(unprotect(_path(key).read_bytes()).decode("utf-8"))


def get_client_credentials() -> tuple[str, str]:
    try:
        import dotenv
        env_file = Path(__file__).resolve().parents[3] / ".env"
        if env_file.exists():
            dotenv.load_dotenv(env_file)
    except Exception:
        pass
    client_id = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    if not (client_id and client_secret):
        cfg_path = Path(__file__).resolve().parents[3] / "config.yaml"
        if cfg_path.exists():
            try:
                import yaml
                raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                yt = raw.get("youtube", {})
                client_id = client_id or str(yt.get("client_id", "")).strip()
                client_secret = client_secret or str(yt.get("client_secret", "")).strip()
            except Exception:
                pass
    return client_id, client_secret


def configured():
    cid, csec = get_client_credentials()
    return bool(cid and csec)


def start_oauth(redirect_uri: str | None = None):
    cid, csec = get_client_credentials()
    if not (cid and csec):
        raise ValueError("请在 .env 或 config.yaml 中配置 YOUTUBE_CLIENT_ID 和 YOUTUBE_CLIENT_SECRET")
    uri = redirect_uri or REDIRECT
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    store("state_" + state, {"expires": time.time() + 600, "verifier": verifier, "redirect_uri": uri})
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": cid, "redirect_uri": uri,
        "response_type": "code", "scope": SCOPES, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
        "access_type": "offline", "prompt": "consent"})


async def finish_oauth(code, state, redirect_uri: str | None = None):
    path = _path("state_" + state)
    if not path.exists():
        raise ValueError("授权状态不存在或已过期，请返回面板重新点击「授权 YouTube 频道」")
    consumed = path.with_suffix(".consumed")
    os.replace(path, consumed)
    try:
        record = json.loads(unprotect(consumed.read_bytes()).decode("utf-8"))
    finally:
        consumed.unlink(missing_ok=True)
    if record["expires"] < time.time():
        raise ValueError("授权已过期（超过10分钟），请返回面板重新点击授权")
    cid, csec = get_client_credentials()
    if not (cid and csec):
        raise ValueError("缺少 YouTube OAuth 客户端配置")
    uri = redirect_uri or record.get("redirect_uri") or REDIRECT
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id": cid, "client_secret": csec,
            "code": code, "code_verifier": record["verifier"], "redirect_uri": uri,
            "grant_type": "authorization_code"})
        if response.status_code != 200:
            raise ValueError(f"Google 令牌交换失败 ({response.status_code}): {response.text}")
        token = response.json()
        if not token.get("refresh_token"):
            raise ValueError("Google 未返回 refresh_token（离线授权）；请在面板重新授权并确保勾选所有请求的权限")
        response = await client.get(API + "/channels", params={"part": "snippet", "mine": "true"},
                                    headers={"Authorization": "Bearer " + token["access_token"]})
        if response.status_code != 200:
            raise ValueError(f"获取 YouTube 频道失败 ({response.status_code}): {response.text}")
        items = response.json().get("items", [])
        if not items:
            raise ValueError("未在该 Google 账号下找到 YouTube 频道，请先登录 youtube.com 确认是否已创建个人/品牌频道")
    channel = items[0]
    ref = secrets.token_hex(24)
    store(ref, {"refresh_token": token["refresh_token"], "channel_id": channel["id"]})
    return {"credential_ref": ref, "channel_id": channel["id"], "nickname": channel["snippet"]["title"]}


async def upload_video(task_id, credential_ref, channel_id, video_path, title, description,
                       tags, visibility="private", category_id="22", made_for_kids=False,
                       thumbnail_path=""):
    if visibility not in ("private", "unlisted", "public"):
        return False, "", "invalid_visibility"
    path = Path(video_path)
    if not path.is_file() or not title.strip() or len(title) > 100:
        return False, "", "invalid_video_or_title"
    session_key = "upload_" + str(task_id)
    record = load(session_key) if _path(session_key).exists() else {}
    submitted = bool(record.get("session") or record.get("video_id"))
    try:
        token = load(credential_ref)
        if token["channel_id"] != channel_id:
            return False, "", "channel_mismatch"
        cid, csec = get_client_credentials()
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post("https://oauth2.googleapis.com/token", data={
                "client_id": cid, "client_secret": csec,
                "refresh_token": token["refresh_token"], "grant_type": "refresh_token"})
            response.raise_for_status()
            headers = {"Authorization": "Bearer " + response.json()["access_token"]}
            response = await client.get(API + "/channels", params={"part": "id", "mine": "true"}, headers=headers)
            response.raise_for_status()
            if channel_id not in [c["id"] for c in response.json().get("items", [])]:
                return False, "", "channel_mismatch"
            total = path.stat().st_size
            identity = {"path": str(path.resolve()), "size": total, "mtime": path.stat().st_mtime_ns,
                        "channel": channel_id, "visibility": visibility, "title": title,
                        "description": description, "tags": tags, "category": category_id,
                        "made_for_kids": made_for_kids}
            if record and record.get("identity") != identity:
                return False, "", "write_uncertain: 上传会话与当前文件或频道不一致"
            if record.get("session"):
                parsed = urlsplit(record["session"])
                if parsed.scheme != "https" or parsed.hostname != "www.googleapis.com":
                    return False, "", "write_uncertain: 上传会话地址无效"
            if not record:
                response = await client.post("https://www.googleapis.com/upload/youtube/v3/videos",
                    params={"uploadType": "resumable", "part": "snippet,status"},
                    headers={**headers, "X-Upload-Content-Length": str(total), "X-Upload-Content-Type": "video/mp4"},
                    json={"snippet": {"title": title, "description": description, "tags": tags, "categoryId": category_id},
                          "status": {"privacyStatus": visibility, "selfDeclaredMadeForKids": made_for_kids}})
                response.raise_for_status()
                submitted = True
                session = response.headers["location"]
                parsed = urlsplit(session)
                if parsed.scheme != "https" or parsed.hostname != "www.googleapis.com":
                    raise ValueError("Unexpected upload host")
                record = {"session": session, "identity": identity}
                store(session_key, record)
            if not record.get("video_id"):
                submitted = True
                response = await client.put(record["session"], headers={**headers, "Content-Range": f"bytes */{total}", "Content-Length": "0"})
                if response.status_code in (200, 201):
                    record["video_id"] = response.json()["id"]
                elif response.status_code == 308:
                    offset = int(response.headers.get("Range", "bytes=0--1").rsplit("-", 1)[-1]) + 1 if response.headers.get("Range") else 0
                    with path.open("rb") as f:
                        f.seek(offset)
                        while offset < total:
                            chunk = f.read(8 * 1024 * 1024)
                            response = await client.put(record["session"], headers={**headers,
                                "Content-Range": f"bytes {offset}-{offset+len(chunk)-1}/{total}"}, content=chunk)
                            if response.status_code in (200, 201):
                                record["video_id"] = response.json()["id"]
                                store(session_key, record)
                                break
                            if response.status_code != 308:
                                response.raise_for_status()
                                raise ValueError("Unexpected upload response")
                            offset += len(chunk)
                else:
                    response.raise_for_status()
            if not record.get("video_id"):
                return False, "", "write_uncertain: 请恢复原上传任务，勿新建重复视频"
            store(session_key, record)
            video_id = record["video_id"]
            response = await client.get(API + "/videos", params={"part": "status,processingDetails,snippet", "id": video_id}, headers=headers)
            response.raise_for_status()
            items = response.json().get("items", [])
            if not items or items[0]["snippet"]["channelId"] != channel_id:
                return False, "", "write_uncertain: 视频已上传但无法回读频道"
            actual = items[0]["status"]["privacyStatus"]
            record["actual_visibility"] = actual
            record["processing"] = items[0].get("processingDetails", {}).get("processingStatus", "unknown")
            store(session_key, record)
            warning = ""
            if actual != visibility:
                warning = "实际可见性为 " + actual + "，请检查 API 项目审核限制"
            if record["processing"] in ("failed", "terminated"):
                warning = "视频已上传，但平台处理失败；请在 YouTube Studio 检查"
            if thumbnail_path and not record.get("thumbnail_done"):
                try:
                    response = await client.post(API + "/thumbnails/set", params={"videoId": video_id},
                        headers={**headers, "Content-Type": "image/jpeg"}, content=Path(thumbnail_path).read_bytes())
                    response.raise_for_status()
                    record["thumbnail_done"] = True
                    store(session_key, record)
                except Exception:
                    warning += " 缩略图设置失败，视频不会重复上传"
            return True, "https://www.youtube.com/watch?v=" + video_id, warning
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        resp_text = exc.response.text
        if "uploadLimitExceeded" in resp_text:
            reason = "频道达到 YouTube 单日上传上限 (uploadLimitExceeded)，平台限制单日发布频次，24小时后自动恢复"
        elif status == 401:
            reason = "授权失效"
        elif status == 403:
            reason = "配额或权限不足"
        else:
            reason = f"API请求失败 ({status}): {resp_text[:120]}"
        return False, "", ("write_uncertain: " if submitted else "") + reason
    except Exception:
        return False, "", ("write_uncertain: 上传连接中断，请核对或恢复原任务" if submitted else "youtube_failed: 请检查授权与配置")


async def _get_access_token(credential_ref: str) -> tuple[str, dict]:
    token = load(credential_ref)
    cid, csec = get_client_credentials()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id": cid, "client_secret": csec,
            "refresh_token": token["refresh_token"], "grant_type": "refresh_token"
        })
        response.raise_for_status()
        access_token = response.json()["access_token"]
    return access_token, token


async def fetch_youtube_channel_stats(credential_ref: str) -> dict:
    access_token, token_rec = await _get_access_token(credential_ref)
    async with httpx.AsyncClient(timeout=30) as client:
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = await client.get(f"{API}/channels?part=snippet,contentDetails,statistics&mine=true", headers=headers)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return {}
        ch = items[0]
        st = ch.get("statistics", {})
        sn = ch.get("snippet", {})
        thumbs = sn.get("thumbnails", {})
        avatar = thumbs.get("default", {}).get("url") or thumbs.get("medium", {}).get("url") or ""
        return {
            "channel_id": ch.get("id", ""),
            "nickname": sn.get("title", ""),
            "avatar": avatar,
            "follower_count": int(st.get("subscriberCount") or 0),
            "aweme_count": int(st.get("videoCount") or 0),
            "view_count": int(st.get("viewCount") or 0),
            "uploads_playlist": ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", ""),
        }


async def fetch_youtube_my_works(credential_ref: str, max_results: int = 500) -> list[dict]:
    stats = await fetch_youtube_channel_stats(credential_ref)
    playlist_id = stats.get("uploads_playlist")
    if not playlist_id:
        return []
    access_token, _ = await _get_access_token(credential_ref)
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=45) as client:
        items = []
        page_token = ""
        while True:
            url = f"{API}/playlistItems?part=snippet,status&playlistId={playlist_id}&maxResults=50"
            if page_token:
                url += f"&pageToken={page_token}"
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                break
            data = resp.json()
            page_items = data.get("items", [])
            if not page_items:
                break
            items.extend(page_items)
            page_token = data.get("nextPageToken")
            if not page_token or len(items) >= max_results:
                break

        if not items:
            return []

        video_ids = [it["snippet"]["resourceId"]["videoId"] for it in items if it.get("snippet", {}).get("resourceId", {}).get("videoId")]
        stat_map = {}
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i+50]
            sresp = await client.get(f"{API}/videos?part=statistics,status&id={','.join(chunk)}", headers=headers)
            if sresp.status_code == 200:
                for v in sresp.json().get("items", []):
                    stat_map[v["id"]] = v

        works = []
        for it in items:
            sn = it.get("snippet", {})
            st_it = it.get("status", {})
            vid = sn.get("resourceId", {}).get("videoId", "")
            if not vid:
                continue
            v_detail = stat_map.get(vid, {})
            v_stat = v_detail.get("statistics", {})
            v_status = v_detail.get("status", st_it)

            pub_at = sn.get("publishedAt", "")
            create_time = 0
            if pub_at:
                try:
                    dt = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
                    create_time = int(dt.timestamp())
                except Exception:
                    pass

            thumbs = sn.get("thumbnails", {})
            cover = thumbs.get("high", {}).get("url") or thumbs.get("medium", {}).get("url") or thumbs.get("default", {}).get("url") or ""
            privacy = v_status.get("privacyStatus", "public")

            works.append({
                "item_id": vid,
                "desc": sn.get("title", ""),
                "media_type": "video",
                "cover_url": cover,
                "create_time": create_time,
                "like_count": int(v_stat.get("likeCount") or 0),
                "comment_count": int(v_stat.get("commentCount") or 0),
                "collect_count": 0,
                "share_count": 0,
                "play_count": int(v_stat.get("viewCount") or 0),
                "status": privacy,
                "xsec_token": "",
                "raw_json": json.dumps(it, ensure_ascii=False)
            })
        return works


async def fetch_youtube_subscriptions(credential_ref: str, max_results: int = 50) -> list[dict]:
    try:
        access_token, _ = await _get_access_token(credential_ref)
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{API}/subscriptions?part=snippet&mine=true&maxResults={max_results}", headers=headers)
            if resp.status_code != 200:
                return []
            items = resp.json().get("items", [])
            subs = []
            for it in items:
                sn = it.get("snippet", {})
                thumbs = sn.get("thumbnails", {})
                avatar = thumbs.get("default", {}).get("url") or thumbs.get("medium", {}).get("url") or ""
                subs.append({
                    "uid": sn.get("resourceId", {}).get("channelId", "") or it.get("id", ""),
                    "sec_uid": sn.get("resourceId", {}).get("channelId", ""),
                    "nickname": sn.get("title", ""),
                    "avatar": avatar,
                    "signature": sn.get("description", "")[:200]
                })
            return subs
    except Exception:
        return []

