"""PikPak API 客户端封装 —— 登录态管理 + 目录遍历。"""
import json
import os
import time

import pikpakapi
from pikpakapi import PikPakApi

import config

# 关键：覆盖库内置的 CLIENT_ID 为你浏览器实际使用的值
# 浏览器 Local Storage 中 credentials_YUMx5nl8ZU8Ap8pm 的后缀即 client_id
PIKPAK_CLIENT_ID = getattr(config, "PIKPAK_CLIENT_ID", "YUMx5nl8ZU8Ap8pm")
pikpakapi.CLIENT_ID = PIKPAK_CLIENT_ID


def build_httpx_args():
    """httpx 客户端参数：统一超时；config 配了 PIKPAK_PROXY 则走代理。

    应用不读 Windows 系统代理，只认这里的配置（或 HTTP_PROXY 环境变量）。
    """
    args = {"timeout": 30}
    proxy = (getattr(config, "PIKPAK_PROXY", "") or "").strip()
    if proxy:
        args["proxy"] = proxy
    return args


async def fetch_captcha_token(client: PikPakApi, action: str) -> str:
    """换取 captcha_token。

    captcha_sign 的计算常量绑定 android 客户端 ID（见 pikpakapi.utils），
    captcha/init 请求若携带 web 客户端 ID 会被服务端以
    "invalid captcha_sign" 拒绝，永远换不到 captcha_token，
    后续请求缺少 X-Captcha-Token 时报 "Verification code is invalid"。
    这里固定用与签名一致的 android 客户端 ID 调 captcha/init；
    signin/refresh 请求体里的 client_id 仍是上面覆盖的 web 值。
    """
    from pikpakapi.utils import (
        captcha_sign,
        get_timestamp,
        CLIENT_ID as SIGN_CLIENT_ID,
        CLIENT_VERSION,
        PACKAG_ENAME,
    )

    t = f"{get_timestamp()}"
    meta = {
        "captcha_sign": captcha_sign(client.device_id, t),
        "client_version": CLIENT_VERSION,
        "package_name": PACKAG_ENAME,
        "user_id": client.user_id,
        "timestamp": t,
    }
    params = {
        "client_id": SIGN_CLIENT_ID,
        "action": action,
        "device_id": client.device_id,
        "meta": meta,
    }
    url = f"https://{PikPakApi.PIKPAK_USER_HOST}/v1/shield/captcha/init"
    result = await client._request_post(url, data=params)
    return result.get("captcha_token") or ""


def _save_token_dict(client):
    data = client.to_dict() if hasattr(client, 'to_dict') else {}
    # 确保保存的字段完整
    data.setdefault('access_token', client.access_token)
    data.setdefault('refresh_token', client.refresh_token)
    data.setdefault('username', getattr(client, 'username', config.PIKPAK_USERNAME))
    data.setdefault('password', getattr(client, 'password', 'token_auth_placeholder'))
    data.setdefault('device_id', getattr(client, 'device_id', config.DEVICE_ID))
    data.setdefault('client_id', pikpakapi.CLIENT_ID)
    with open(config.TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_client() -> PikPakApi:
    if os.path.exists(config.TOKEN_PATH):
        with open(config.TOKEN_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        # token.json 不存在，直接从 config 加载
        access = getattr(config, "PIKPAK_ACCESS_TOKEN", "").strip()
        refresh = getattr(config, "PIKPAK_REFRESH_TOKEN", "").strip()
        if not access or not refresh:
            raise RuntimeError("找不到 token.json 且 config 中未配置 token。请先登录或导入 token。")
        data = {
            "access_token": access,
            "refresh_token": refresh,
            "username": config.PIKPAK_USERNAME,
            "device_id": config.DEVICE_ID,
            "password": "token_auth_placeholder",
        }

    # 手动构造客户端，避免 from_dict 缺字段导致校验失败
    client = PikPakApi(
        username=data.get("username") or config.PIKPAK_USERNAME,
        password=data.get("password", "") or "token_auth_placeholder",
        device_id=data.get("device_id") or config.DEVICE_ID,
        httpx_client_args=build_httpx_args(),
    )
    # 回填 token 等字段
    client.access_token = data.get("access_token")
    client.refresh_token = data.get("refresh_token")
    client.encoded_token = data.get("encoded_token")

    # 从 JWT 提取 user_id
    if client.access_token:
        try:
            import base64
            payload = client.access_token.split('.')[1]
            payload += '=' * (4 - len(payload) % 4)
            claims = json.loads(base64.b64decode(payload))
            client.user_id = claims.get("sub", "")
        except Exception:
            pass

    # 设置 captcha_token
    captcha = getattr(config, "PIKPAK_CAPTCHA_TOKEN", "").strip()
    if captcha:
        client.captcha_token = captcha

    # 恢复签发该 token 的客户端身份：signin/refresh 请求体里的 client_id
    # 必须与 token 匹配（密码登录是 android，浏览器导入是 web）
    client_id = data.get("client_id") or getattr(config, "PIKPAK_CLIENT_ID", "YUMx5nl8ZU8Ap8pm")
    pikpakapi.CLIENT_ID = client_id

    client.token_refresh_callback = lambda c, *a, **k: _save_token_dict(c)

    # 检查 token 是否过期，如果过期则尝试刷新
    if client.access_token:
        try:
            import base64
            payload = client.access_token.split('.')[1]
            payload += '=' * (4 - len(payload) % 4)
            claims = json.loads(base64.b64decode(payload))
            exp = claims.get('exp', 0)
            if exp < time.time():
                print(f"⚠️ access_token 已过期，尝试用 refresh_token 刷新...")
                # 同步刷新
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(client.refresh_access_token())
                    print("✅ token 刷新成功")
                except Exception as e:
                    print(f"❌ token 刷新失败: {e}")
                    raise RuntimeError(f"token 已过期且刷新失败: {e}。请从浏览器重新复制 token。")
                finally:
                    loop.close()
        except RuntimeError:
            raise
        except Exception:
            pass  # JWT 解析失败则直接用原 token

    return client


async def ensure_captcha(client, action="GET:/drive/v1/files"):
    """设置 captcha_token。优先在线换取（值过期很快），失败再退回 config 里的。"""
    if client.captcha_token:
        return
    captcha = await fetch_captcha_token(client, action=action)
    if not captcha:
        captcha = getattr(config, "PIKPAK_CAPTCHA_TOKEN", "").strip()
    if not captcha:
        raise RuntimeError("获取 captcha_token 失败。请检查网络，或从浏览器复制 captcha_token 填入 config_local.py")
    client.captcha_token = captcha


async def get_quota(client) -> dict:
    """返回 {usage_bytes, limit_bytes, usage_gb, limit_gb}"""
    await ensure_captcha(client, action="GET:/drive/v1/about")
    quota = await client.get_quota_info()
    q = quota.get("quota", {})
    usage = int(q.get("usage", 0))
    limit = int(q.get("limit", 0))
    return {
        "usage_bytes": usage,
        "limit_bytes": limit,
        "usage_gb": round(usage / (1024**3), 2),
        "limit_gb": round(limit / (1024**3), 2),
    }


async def list_folder(client, parent_id=None, page_token=None, size=200):
    """实时列出一个文件夹（子文件夹+文件），在线浏览用，不走本地扫描库。"""
    await ensure_captcha(client, action="GET:/drive/v1/files")
    res = await client.file_list(size=size, parent_id=parent_id, next_page_token=page_token)
    items = []
    for f in res.get("files", []):
        is_folder = f.get("kind", "").endswith("folder")
        items.append({
            "id": f.get("id", ""),
            "name": f.get("name", ""),
            "kind": "folder" if is_folder else "file",
            "size": int(f.get("size", 0) or 0),
            "mime_type": f.get("mime_type", "") or "",
        })
    return {"items": items, "next_page_token": res.get("next_page_token") or ""}


async def get_file_detail(client, file_id):
    """获取文件详情与播放/下载直链。

    直链接口按 action 校验 captcha（GET:/drive/v1/files/<id>），
    库自带的 get_download_url 内部 captcha_init 会因 client_id 验签失败，
    这里用 fetch_captcha_token 取新值后自己请求。

    medias 按浏览器可播优先排序：h264 原片 > 转码流 > 其他（如 h265 原片）。
    """
    try:
        captcha = await fetch_captcha_token(client, action=f"GET:/drive/v1/files/{file_id}")
        if captcha:
            client.captcha_token = captcha
    except Exception:
        pass  # 换取失败则沿用已有 captcha
    url = f"https://{PikPakApi.PIKPAK_API_HOST}/drive/v1/files/{file_id}"
    detail = await client._request_get(url, {"thumbnail_size": "SIZE_LARGE"})
    medias = []
    for m in detail.get("medias") or []:
        link = (m or {}).get("link") or {}
        if not link.get("url"):
            continue
        v = (m or {}).get("video") or {}
        codec = (v.get("video_codec") or "").lower()
        name = m.get("media_name") or ""
        # 0: 浏览器可解码（h264 或未知）；2: 大概率不可播（h265 等）
        codec_score = 2 if codec and codec != "h264" else 0
        orig_score = 0 if name.lower() == "original" else 1
        medias.append({
            "name": name,
            "url": link["url"],
            "video_codec": codec,
            "audio_codec": (v.get("audio_codec") or "").lower(),
            "width": v.get("width") or 0,
            "height": v.get("height") or 0,
            "duration": v.get("duration") or 0,
            "_sort": (codec_score, orig_score),
        })
    medias.sort(key=lambda x: x.pop("_sort"))
    return {
        "id": detail.get("id", file_id),
        "name": detail.get("name", ""),
        "size": int(detail.get("size", 0) or 0),
        "mime_type": detail.get("mime_type", "") or "",
        "web_content_link": detail.get("web_content_link", "") or "",
        "medias": medias,
    }


async def walk_all_files(client, folder_id=None, prefix=""):
    """广度优先遍历整棵目录树，yield (path_prefix, file_dict_list)。
    file_dict 包含 id/name/size/kind/mime_type 等原始字段。"""
    await ensure_captcha(client, action="GET:/drive/v1/files")
    queue = [(folder_id, prefix)]
    while queue:
        fid, pfx = queue.pop(0)
        token = None
        files_here, subfolders = [], []
        while True:
            res = await client.file_list(
                size=config.LIST_PAGE_SIZE, parent_id=fid, next_page_token=token
            )
            for f in res.get("files", []):
                if f.get("kind", "").endswith("folder"):
                    subfolders.append(
                        (f.get("id"), pfx + f.get("name", "") + "/")
                    )
                else:
                    files_here.append(f)
            token = res.get("next_page_token")
            if not token:
                break
        yield pfx, files_here
        queue.extend(subfolders)


async def list_subfolders(client, parent_id=None):
    """列某一层的子文件夹（懒加载用）。"""
    await ensure_captcha(client, action="GET:/drive/v1/files")
    folders = []
    token = None
    while True:
        res = await client.file_list(
            size=config.LIST_PAGE_SIZE, parent_id=parent_id, next_page_token=token
        )
        for f in res.get("files", []):
            if f.get("kind", "").endswith("folder"):
                folders.append({"name": f.get("name"), "id": f.get("id")})
        token = res.get("next_page_token")
        if not token:
            break
    return folders


async def resolve_folder_id(client, path_parts):
    """按路径逐级找到文件夹 id。path_parts 形如 ["分类", "照片"]"""
    await ensure_captcha(client, action="GET:/drive/v1/files")
    parent_id = None
    for part in path_parts:
        found = None
        token = None
        while True:
            res = await client.file_list(
                size=config.LIST_PAGE_SIZE, parent_id=parent_id, next_page_token=token
            )
            for f in res.get("files", []):
                if f.get("kind", "").endswith("folder") and f.get("name") == part:
                    found = f.get("id")
                    break
            if found:
                break
            token = res.get("next_page_token")
            if not token:
                break
        if not found:
            raise RuntimeError(f"找不到文件夹: {part}")
        parent_id = found
    return parent_id
