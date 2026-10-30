"""PikPak 磁盘空间分析工具 —— Flask Web 应用。"""
import asyncio
import logging
import sqlite3
import threading

from flask import Flask, render_template, jsonify, request

import config
import scanner
import analyzer

logging.getLogger("werkzeug").setLevel(logging.WARNING)

app = Flask(__name__)

# 扫描状态
SCAN = {"running": False, "progress": {}, "last": None}


def _db():
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================
# 页面
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


# ============================================================
# 网盘容量
# ============================================================

@app.route("/api/quota")
def api_quota():
    try:
        from pikpak_client import load_client, get_quota
        client = load_client()
        quota = _run_async(get_quota(client))
        try:
            import asyncio as _a
            _a.new_event_loop().run_until_complete(client.httpx_client.aclose())
        except Exception:
            pass
        return jsonify({"ok": True, "quota": quota})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ============================================================
# 扫描
# ============================================================

@app.route("/api/scan/start", methods=["POST"])
def api_scan_start():
    if SCAN["running"]:
        return jsonify({"ok": False, "error": "扫描正在进行中"})
    SCAN["running"] = True
    SCAN["progress"] = {"stage": "starting", "msg": "正在启动扫描..."}
    SCAN["last"] = None

    def worker():
        def cb(stage, count, msg):
            SCAN["progress"] = {"stage": stage, "count": count, "msg": msg}
        try:
            result = _run_async(scanner.scan_drive(progress_cb=cb))
            SCAN["last"] = result
        except Exception as e:
            SCAN["progress"] = {"stage": "error", "msg": str(e)}
            SCAN["last"] = {"error": str(e)}
        finally:
            SCAN["running"] = False

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True, "msg": "扫描已启动"})


@app.route("/api/scan/status")
def api_scan_status():
    return jsonify({
        "running": SCAN["running"],
        "progress": SCAN["progress"],
        "last": SCAN["last"],
    })


# ============================================================
# 目录空间树
# ============================================================

@app.route("/api/tree")
def api_tree():
    try:
        tree = analyzer.get_directory_tree()
        summary = analyzer.get_root_summary()
        return jsonify({"ok": True, "tree": tree, "summary": summary})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/dir_files")
def api_dir_files():
    """列出某目录下的直接文件（读本地扫描库，不请求网盘）。"""
    path = request.args.get("path", "")
    try:
        limit = min(max(int(request.args.get("limit", 200)), 1), 500)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        limit, offset = 200, 0
    try:
        data = analyzer.list_directory_files(path, limit=limit, offset=offset)
        return jsonify({"ok": True, **data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/drive/list")
def api_drive_list():
    """实时浏览网盘目录（在线播放用，不依赖本地扫描库）。"""
    folder_id = request.args.get("folder_id", "") or None
    page_token = request.args.get("page_token", "") or None
    try:
        size = min(max(int(request.args.get("size", 200)), 1), 500)
    except ValueError:
        size = 200
    try:
        from pikpak_client import load_client, list_folder
        client = load_client()
        data = _run_async(list_folder(client, parent_id=folder_id, page_token=page_token, size=size))
        try:
            import asyncio as _a
            _a.new_event_loop().run_until_complete(client.httpx_client.aclose())
        except Exception:
            pass
        return jsonify({"ok": True, **data})
    except Exception as e:
        return jsonify({"ok": False, "error": f"浏览失败: {e}", "hint": _drive_error_hint(str(e))})


@app.route("/api/drive/file")
def api_drive_file():
    """取文件详情与播放/下载直链。"""
    file_id = request.args.get("id", "")
    if not file_id:
        return jsonify({"ok": False, "error": "缺少文件 id"})
    try:
        from pikpak_client import load_client, get_file_detail
        client = load_client()
        data = _run_async(get_file_detail(client, file_id))
        try:
            import asyncio as _a
            _a.new_event_loop().run_until_complete(client.httpx_client.aclose())
        except Exception:
            pass
        return jsonify({"ok": True, **data})
    except Exception as e:
        return jsonify({"ok": False, "error": f"获取直链失败: {e}", "hint": _drive_error_hint(str(e))})


def _drive_error_hint(err):
    if "Verification code" in err:
        return "captcha/风控校验失败，请稍后重试；频繁请求会触发风控。"
    if any(k in err.lower() for k in ("token", "401", "unauthorized", "not found", "expire")):
        return "登录态无效或已过期，请到「扫描/登录」页重新登录或导入 token。"
    if any(k in err for k in ("Max retries", "Timeout", "Connect", "timeout")):
        return (
            "连不上 PikPak。若其他网站正常，多半是本机 IP 被临时限制"
            "（重启路由器换 IP 或用手机热点即可，不需要代理）；"
            "也可能是断网或代理配置失效，稍后再试。"
        )
    return ""


# ============================================================
# 去重
# ============================================================

@app.route("/api/dedup")
def api_dedup():
    try:
        summary_only = request.args.get("summary_only", "").lower() == "true"
        if summary_only:
            summary = analyzer.get_dedup_summary()
            return jsonify({"ok": True, "summary": summary})
        groups = analyzer.find_duplicate_files()
        summary = analyzer.get_dedup_summary()
        return jsonify({"ok": True, "groups": groups, "summary": summary})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ============================================================
# 大文件
# ============================================================

@app.route("/api/largest")
def api_largest():
    try:
        limit = request.args.get("limit", 100, type=int)
        files = analyzer.get_largest_files(limit=min(limit, 500))
        return jsonify({"ok": True, "files": files})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ============================================================
# 搜索
# ============================================================

@app.route("/api/search")
def api_search():
    kw = request.args.get("q", "").strip()
    if not kw:
        return jsonify({"ok": False, "error": "请输入关键词"})
    try:
        files = analyzer.search_files(kw)
        return jsonify({"ok": True, "files": files})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ============================================================
# 删除重复文件
# ============================================================

@app.route("/api/dedup/batch_delete", methods=["POST"])
def api_dedup_batch_delete():
    """批量删除所有重复组的多余副本（每组保留第一个）。
    从数据库直接计算，不受前端显示限制。"""
    def do_batch():
        from pikpak_client import load_client, ensure_captcha

        # 从数据库找出所有重复组，每组保留 path 最小的（第一个）
        conn = _db()
        rows = conn.execute("""
            SELECT f.id, f.name, f.size, f.path
            FROM files f
            INNER JOIN (
                SELECT name, size FROM files
                GROUP BY name, size
                HAVING COUNT(*) > 1
            ) dup ON f.name = dup.name AND f.size = dup.size
            ORDER BY f.name, f.size, f.path
        """).fetchall()
        conn.close()

        # 按 (name, size) 分组，每组保留 path 排序最小的
        from collections import defaultdict
        grouped = defaultdict(list)
        for r in rows:
            grouped[(r["name"], r["size"])].append(r["id"])

        delete_ids = []
        for key, ids in grouped.items():
            # 保留第一个，删除其余
            delete_ids.extend(ids[1:])

        if not delete_ids:
            return {"deleted": 0}

        # 分批删除（每批最多 500 个）
        client = load_client()

        async def _delete():
            await ensure_captcha(client, action="POST:/drive/v1/files:batchTrash")
            total = 0
            try:
                for i in range(0, len(delete_ids), 500):
                    batch = delete_ids[i:i+500]
                    await client.delete_to_trash(batch)
                    total += len(batch)
                return {"deleted": total}
            finally:
                await client.httpx_client.aclose()

        result = _run_async(_delete())

        # 同步删除本地数据库记录
        conn = _db()
        for i in range(0, len(delete_ids), 500):
            batch = delete_ids[i:i+500]
            placeholders = ",".join(["?"] * len(batch))
            conn.execute(f"DELETE FROM files WHERE id IN ({placeholders})", batch)
        conn.commit()
        conn.close()
        return result

    try:
        result = do_batch()
        return jsonify({"ok": True, "deleted": result["deleted"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    """删除重复文件组中的多余副本。
    body: {"groups": [{"name": "...", "size": 123, "keep_path": "path/to/keep", "delete_ids": ["id1","id2"]}]}
    或 {"file_ids": ["id1","id2"]} 直接删除指定文件。
    """
    data = request.get_json(force=True)
    file_ids = data.get("file_ids", [])

    # 如果传了 groups，计算要删除的 id
    if not file_ids and data.get("groups"):
        for g in data["groups"]:
            keep_path = g.get("keep_path", "")
            for f in g.get("files", []):
                if f.get("path") != keep_path:
                    file_ids.append(f.get("id"))
    if not file_ids:
        return jsonify({"ok": False, "error": "没有需要删除的文件"})

    def do_delete():
        from pikpak_client import load_client, ensure_captcha

        async def _delete():
            client = load_client()
            await ensure_captcha(client, action="POST:/drive/v1/files:batchTrash")
            try:
                # 移入回收站（安全，可恢复）
                result = await client.delete_to_trash(file_ids)
                return {"deleted": len(file_ids), "result": result}
            finally:
                await client.httpx_client.aclose()

        return _run_async(_delete())

    try:
        result = do_delete()
        # 从本地数据库也删掉
        conn = _db()
        placeholders = ",".join(["?"] * len(file_ids))
        conn.execute(f"DELETE FROM files WHERE id IN ({placeholders})", file_ids)
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "deleted": result["deleted"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/dedup/delete", methods=["POST"])
def api_dedup_delete():
    """删除指定的重复文件副本。"""
    data = request.get_json(force=True)
    file_ids = data.get("file_ids", [])
    if not file_ids:
        return jsonify({"ok": False, "error": "没有需要删除的文件"})

    def do_delete():
        from pikpak_client import load_client, ensure_captcha

        async def _delete():
            client = load_client()
            await ensure_captcha(client, action="POST:/drive/v1/files:batchTrash")
            try:
                result = await client.delete_to_trash(file_ids)
                return {"deleted": len(file_ids)}
            finally:
                await client.httpx_client.aclose()

        return _run_async(_delete())

    try:
        result = do_delete()
        conn = _db()
        placeholders = ",".join(["?"] * len(file_ids))
        conn.execute(f"DELETE FROM files WHERE id IN ({placeholders})", file_ids)
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "deleted": result["deleted"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/dedup/delete_permanent", methods=["POST"])
def api_dedup_delete_permanent():
    """彻底删除（不可恢复）。"""
    data = request.get_json(force=True)
    file_ids = data.get("file_ids", [])
    if not file_ids:
        return jsonify({"ok": False, "error": "没有需要删除的文件"})

    def do_delete():
        from pikpak_client import load_client, ensure_captcha

        async def _delete():
            client = load_client()
            await ensure_captcha(client, action="POST:/drive/v1/files:batchDelete")
            try:
                result = await client.delete_forever(file_ids)
                return {"deleted": len(file_ids)}
            finally:
                await client.httpx_client.aclose()

        return _run_async(_delete())

    try:
        result = do_delete()
        conn = _db()
        placeholders = ",".join(["?"] * len(file_ids))
        conn.execute(f"DELETE FROM files WHERE id IN ({placeholders})", file_ids)
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "deleted": result["deleted"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ============================================================
# 登录
# ============================================================

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True)
    username = data.get("username", "").strip()
    password = data.get("password", "")
    device_id = data.get("device_id", "").strip()
    if not device_id:
        cfg_dev = (getattr(config, "DEVICE_ID", "") or "").strip()
        # 占位符无效；留空交给库按账号派生稳定的设备 ID
        device_id = "" if cfg_dev.startswith("your_") else cfg_dev

    if not username or not password:
        return jsonify({"ok": False, "error": "请填写邮箱和密码"})

    def do_login():
        import json as _json
        import pikpakapi as _pik
        from pikpakapi import PikPakApi
        from pikpak_client import ensure_captcha, build_httpx_args

        # signin 必须用与 client_secret 配套的 android 客户端身份，
        # 用 web client_id 调 /v1/auth/signin 会 404 not found
        _pik.CLIENT_ID = _pik.utils.CLIENT_ID

        client = PikPakApi(username=username, password=password, device_id=device_id,
                           httpx_client_args=build_httpx_args())

        async def _login():
            # 1. 密码登录（login 内部自取 signin 用的 captcha_token）
            await client.login()

            # 2. 验证 token 有效（about 接口需要 captcha，否则报
            #    "Verification code is invalid"）
            await ensure_captcha(client, action="GET:/drive/v1/about")
            quota = await client.get_quota_info()
            q = quota.get("quota", {})

            # 保存 token
            data_dict = {
                "access_token": client.access_token,
                "refresh_token": client.refresh_token,
                "username": username,
                "password": password,
                "device_id": getattr(client, "device_id", device_id),
                "user_id": client.user_id,
                "client_id": _pik.CLIENT_ID,
            }
            if client.captcha_token:
                data_dict["captcha_token"] = client.captcha_token
            with open(config.TOKEN_PATH, "w", encoding="utf-8") as f:
                _json.dump(data_dict, f, ensure_ascii=False, indent=2)

            usage = int(q.get("usage", 0))
            limit = int(q.get("limit", 0))
            await client.httpx_client.aclose()
            return {
                "usage_gb": round(usage / (1024**3), 2),
                "limit_gb": round(limit / (1024**3), 2),
                "method": "password",
            }

        return _run_async(_login())

    try:
        result = do_login()
        return jsonify({"ok": True, "quota": result, "msg": "密码登录成功"})
    except Exception as e:
        err = str(e)
        # 判断错误类型，给出针对性提示
        hint = ""
        if "review" in err:
            hint = (
                "触发 API 风控（review）。请等待几分钟到几小时后重试，"
                "期间不要反复尝试（会延长拦截）。急用可改「手动导入 Token」。"
            )
        elif "AccessProhibited" in err or "captcha" in err.lower():
            hint = "API 风控拦截。请改用手动导入 Token 方式（从浏览器复制）。"
        elif "invalid_account_or_password" in err or "Invalid username" in err:
            hint = "邮箱或密码错误，请检查。"
        elif "Verification code" in err:
            hint = "验证码校验失败。请改用手动导入 Token 方式。"
        elif any(k in err for k in ("Max retries", "Timeout", "Connect", "timeout")):
            hint = "连不上 PikPak。若其他网站正常，多半是本机 IP 被临时限制（重启路由器换 IP 或用手机热点即可，不需要代理）；也可能是断网，稍后再试。"
        else:
            hint = "登录失败。如果密码登录不行，请切换到「手动导入 Token」方式。"
        return jsonify({"ok": False, "error": err, "hint": hint})


# ============================================================
# 手动导入 token（绕过风控）
# ============================================================

@app.route("/api/token/import", methods=["POST"])
def api_token_import():
    """手动导入 token。接受两种格式：
    1. 直接粘贴完整 JSON（浏览器中复制的 token 对象）
    2. 分别填 access_token + refresh_token
    """
    data = request.get_json(force=True)
    import json as _json
    import time as _time

    raw_json = (data.get("raw_json") or "").strip()
    access_token = (data.get("access_token") or "").strip()
    refresh_token = (data.get("refresh_token") or "").strip()

    token_dict = None

    # 方式一：粘贴完整 JSON
    if raw_json:
        try:
            parsed = _json.loads(raw_json)
            if isinstance(parsed, str):
                parsed = _json.loads(parsed)
            if isinstance(parsed, dict):
                # 可能嵌套在某个 key 里
                if "access_token" in parsed:
                    token_dict = parsed
                elif "data" in parsed and isinstance(parsed["data"], dict) and "access_token" in parsed["data"]:
                    token_dict = parsed["data"]
                else:
                    return jsonify({"ok": False, "error": "JSON 中未找到 access_token 字段"})
            else:
                return jsonify({"ok": False, "error": "无法解析 JSON"})
        except _json.JSONDecodeError as e:
            return jsonify({"ok": False, "error": f"JSON 格式错误: {e}"})

    # 方式二：分别填 access_token / refresh_token
    elif access_token and refresh_token:
        token_dict = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": 7200,
            "expires_at": _time.time() + 7200,
            "user_id": "",
            "username": config.PIKPAK_USERNAME,
            "password": "token_auth_placeholder",
            "device_id": config.DEVICE_ID,
        }
    else:
        return jsonify({"ok": False, "error": "请粘贴 JSON 或分别填写 access_token 和 refresh_token"})

    # 验证 token 有效性
    def verify_and_save():
        import pikpakapi as _pik
        from pikpakapi import PikPakApi
        from pikpak_client import build_httpx_args

        # 浏览器 token 是 web 客户端签发的，刷新需用同一 client_id
        # （密码登录会把全局改成 android，这里改回来）
        web_client_id = getattr(config, "PIKPAK_CLIENT_ID", "YUMx5nl8ZU8Ap8pm")
        _pik.CLIENT_ID = web_client_id

        # 不用 from_dict：浏览器复制的 JSON 通常没有 username/password，
        # 直接构造再回填 token，与 pikpak_client.load_client 保持一致
        client = PikPakApi(
            username=token_dict.get("username") or config.PIKPAK_USERNAME,
            password=token_dict.get("password") or "token_auth_placeholder",
            device_id=token_dict.get("device_id") or config.DEVICE_ID,
            httpx_client_args=build_httpx_args(),
        )
        client.access_token = token_dict.get("access_token")
        client.refresh_token = token_dict.get("refresh_token")

        async def _verify():
            # captcha_init 的 meta 需要 user_id，从 JWT 里解出来
            if client.access_token and not client.user_id:
                try:
                    import base64
                    payload = client.access_token.split(".")[1]
                    payload += "=" * (-len(payload) % 4)
                    claims = _json.loads(base64.b64decode(payload))
                    client.user_id = claims.get("sub", "")
                except Exception:
                    pass

            # 缺少或使用过期的 captcha_token 时，PikPak API 会报
            # "Verification code is invalid"，验证前先换取一个新的
            from pikpak_client import fetch_captcha_token
            fresh = ""
            try:
                fresh = await fetch_captcha_token(client, action="GET:/drive/v1/about")
            except Exception:
                pass
            client.captcha_token = (
                fresh
                or token_dict.get("captcha_token")
                or getattr(config, "PIKPAK_CAPTCHA_TOKEN", "").strip()
                or None
            )

            quota = await client.get_quota_info()
            q = quota.get("quota", {})
            # 保存
            save = {
                "access_token": client.access_token,
                "refresh_token": client.refresh_token,
                "username": getattr(client, "username", config.PIKPAK_USERNAME),
                "password": getattr(client, "password", "token_auth_placeholder"),
                "device_id": getattr(client, "device_id", config.DEVICE_ID),
                "user_id": client.user_id or "",
                "client_id": web_client_id,
            }
            if client.captcha_token:
                save["captcha_token"] = client.captcha_token
            with open(config.TOKEN_PATH, "w", encoding="utf-8") as f:
                _json.dump(save, f, ensure_ascii=False, indent=2)
            usage = int(q.get("usage", 0))
            limit = int(q.get("limit", 0))
            await client.httpx_client.aclose()
            return {
                "usage_gb": round(usage / (1024**3), 2),
                "limit_gb": round(limit / (1024**3), 2),
            }

        return _run_async(_verify())

    try:
        quota = verify_and_save()
        return jsonify({"ok": True, "msg": "token 导入成功", "quota": quota})
    except Exception as e:
        err = str(e)
        hint = ""
        if "Verification code" in err:
            hint = (
                "captcha 校验失败。请检查 config_local.py 的 DEVICE_ID 是否为浏览器真实的"
                " deviceid（去掉 wdi10. 前缀）；若仍失败，把浏览器 Local Storage 中"
                " captcha_XXX 里的 captcha_token 填入 PIKPAK_CAPTCHA_TOKEN。"
                "另注意 access_token 约 2 小时过期，过期请重新复制。"
            )
        elif any(k in err.lower() for k in ("401", "unauthorized", "invalid", "expire", "bad uuid", "not found", "not_found")):
            hint = "access/refresh token 无效或已过期，请从浏览器重新复制完整的 token 值。"
        elif any(k in err for k in ("Max retries", "Timeout", "Connect", "timeout")):
            hint = "连不上 PikPak。若其他网站正常，多半是本机 IP 被临时限制（重启路由器换 IP 或用手机热点即可，不需要代理）；也可能是断网，稍后再试。"
        return jsonify({"ok": False, "error": f"token 验证失败: {err}", "hint": hint})


@app.route("/api/token/status")
def api_token_status():
    """检查 token 是否存在且可用。"""
    import os as _os
    if not _os.path.exists(config.TOKEN_PATH):
        return jsonify({"ok": False, "has_token": False, "msg": "尚未登录"})
    try:
        from pikpak_client import load_client, get_quota
        client = load_client()
        quota = _run_async(get_quota(client))
        try:
            import asyncio as _a
            _a.new_event_loop().run_until_complete(client.httpx_client.aclose())
        except Exception:
            pass
        return jsonify({"ok": True, "has_token": True, "quota": quota})
    except Exception as e:
        return jsonify({"ok": False, "has_token": True, "msg": f"token 可能已过期: {e}"})


def _auto_load_token():
    """如果 config 里配了 token 且本地 token.json 不存在，自动生成。"""
    import os as _os
    import json as _json
    import time as _time

    if _os.path.exists(config.TOKEN_PATH):
        return
    access = getattr(config, "PIKPAK_ACCESS_TOKEN", "").strip()
    refresh = getattr(config, "PIKPAK_REFRESH_TOKEN", "").strip()
    if not access or not refresh:
        return

    token_dict = {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": 7200,
        "expires_at": _time.time() + 7200,
        "user_id": "",
        "username": config.PIKPAK_USERNAME,
        "password": "token_auth_placeholder",
        "device_id": config.DEVICE_ID,
    }
    # 也保存 captcha_token
    captcha = getattr(config, "PIKPAK_CAPTCHA_TOKEN", "").strip()
    if captcha:
        token_dict["captcha_token"] = captcha
    with open(config.TOKEN_PATH, "w", encoding="utf-8") as f:
        _json.dump(token_dict, f, ensure_ascii=False, indent=2)
    print(f"✅ 已从 config_local.py 自动加载 token")


if __name__ == "__main__":
    import sys as _sys
    import threading
    import webbrowser

    scanner.init_db()
    _auto_load_token()

    url = "http://127.0.0.1:5001"
    print(f"\n🍅 PikPak 磁盘空间分析工具")
    print(f"   {url}")
    print(f"   浏览器将自动打开；关闭本窗口即停止服务\n")

    if "--no-browser" not in _sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    app.run(host="127.0.0.1", port=5001, debug=False)
