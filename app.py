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
    device_id = data.get("device_id", "").strip() or config.DEVICE_ID

    if not username or not password:
        return jsonify({"ok": False, "error": "请填写邮箱和密码"})

    def do_login():
        from pikpakapi import PikPakApi
        import json as _json

        client = PikPakApi(username=username, password=password, device_id=device_id)

        async def _login():
            await client.login()
            quota = await client.get_quota_info()
            q = quota.get("quota", {})
            # 保存 token
            data_dict = client.to_dict()
            with open(config.TOKEN_PATH, "w", encoding="utf-8") as f:
                _json.dump(data_dict, f, ensure_ascii=False, indent=2)
            usage = int(q.get("usage", 0))
            limit = int(q.get("limit", 0))
            await client.httpx_client.aclose()
            return {
                "usage_gb": round(usage / (1024**3), 2),
                "limit_gb": round(limit / (1024**3), 2),
            }

        return _run_async(_login())

    try:
        quota = do_login()
        return jsonify({"ok": True, "quota": quota})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


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
        from pikpakapi import PikPakApi

        client = PikPakApi.from_dict(token_dict)

        async def _verify():
            quota = await client.get_quota_info()
            q = quota.get("quota", {})
            # 保存
            with open(config.TOKEN_PATH, "w", encoding="utf-8") as f:
                _json.dump(client.to_dict(), f, ensure_ascii=False, indent=2)
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
        return jsonify({"ok": False, "error": f"token 验证失败: {e}"})


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
    scanner.init_db()
    _auto_load_token()
    print(f"\n🍅 PikPak 磁盘空间分析工具")
    print(f"   http://127.0.0.1:5001\n")
    app.run(host="127.0.0.1", port=5001, debug=False)
