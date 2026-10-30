"""分析器：目录空间树聚合 + 文件名+大小去重。"""
import sqlite3
from collections import defaultdict

import config


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024.0
        if n < 1024:
            return f"{n:.2f} {unit}"
    return f"{n:.2f} PB"


def _conn(db_path=None):
    db = db_path or config.DB_PATH
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================
# 目录空间分析
# ============================================================

def get_directory_tree(db_path=None):
    """返回所有目录及其直接文件大小、子目录汇总大小。
    返回结构：
    [
      {
        "path": "分类/照片",
        "name": "照片",
        "direct_files": 120,        # 直接包含的文件数
        "direct_bytes": 524288000,  # 直接包含的文件总大小
        "total_files": 350,         # 含子目录的总文件数
        "total_bytes": 1073741824,  # 含子目录的总大小
        "depth": 1,
      }, ...
    ]
    """
    conn = _conn(db_path)
    rows = conn.execute(
        "SELECT parent_path, name, size FROM files"
    ).fetchall()
    conn.close()

    # 按目录聚合直接文件
    dir_direct = defaultdict(lambda: {"files": 0, "bytes": 0})
    all_dirs = set()
    all_dirs.add("")  # 根目录

    for r in rows:
        pp = r["parent_path"]
        dir_direct[pp]["files"] += 1
        dir_direct[pp]["bytes"] += r["size"]
        # 把所有祖先目录都加入
        parts = pp.split("/") if pp else []
        for i in range(len(parts) + 1):
            all_dirs.add("/".join(parts[:i]))

    # 从叶子到根累加 total
    dir_total = defaultdict(lambda: {"files": 0, "bytes": 0})
    # 先把直接值放进去
    for d in all_dirs:
        if d in dir_direct:
            dir_total[d] = {
                "files": dir_direct[d]["files"],
                "bytes": dir_direct[d]["bytes"],
            }

    # 按深度从深到浅累加到父目录
    sorted_dirs = sorted(all_dirs, key=lambda x: x.count("/"), reverse=True)
    for d in sorted_dirs:
        if d == "":
            continue
        parent = "/".join(d.split("/")[:-1])
        dir_total[parent]["files"] += dir_total[d]["files"]
        dir_total[parent]["bytes"] += dir_total[d]["bytes"]

    # 组装结果
    result = []
    for d in sorted(all_dirs):
        if d == "":
            continue
        name = d.split("/")[-1]
        depth = d.count("/")
        result.append({
            "path": d,
            "name": name,
            "direct_files": dir_direct.get(d, {}).get("files", 0),
            "direct_bytes": dir_direct.get(d, {}).get("bytes", 0),
            "total_files": dir_total[d]["files"],
            "total_bytes": dir_total[d]["bytes"],
            "total_size_str": fmt_size(dir_total[d]["bytes"]),
            "depth": depth,
        })

    # 按 path 排序（树状顺序）
    result.sort(key=lambda x: x["path"])
    return result


def get_root_summary(db_path=None):
    """根目录总览。"""
    conn = _conn(db_path)
    row = conn.execute(
        "SELECT COUNT(*) as cnt, COALESCE(SUM(size),0) as total FROM files"
    ).fetchone()
    conn.close()
    return {
        "total_files": row["cnt"],
        "total_bytes": row["total"],
        "total_size_str": fmt_size(row["total"]),
    }


def list_directory_files(parent_path, limit=200, offset=0, db_path=None):
    """列出某目录下的直接文件（按大小降序，分页）。"""
    conn = _conn(db_path)
    total = conn.execute(
        "SELECT COUNT(*) AS cnt FROM files WHERE parent_path = ?",
        (parent_path,),
    ).fetchone()["cnt"]
    rows = conn.execute(
        "SELECT id, name, size, mime_type FROM files "
        "WHERE parent_path = ? ORDER BY size DESC, name LIMIT ? OFFSET ?",
        (parent_path, limit, offset),
    ).fetchall()
    conn.close()
    return {
        "total": total,
        "files": [
            {
                "id": r["id"],
                "name": r["name"],
                "size": r["size"],
                "size_str": fmt_size(r["size"]),
                "mime_type": r["mime_type"],
            }
            for r in rows
        ],
        "has_more": offset + len(rows) < total,
    }


# ============================================================
# 文件名 + 大小去重
# ============================================================

def find_duplicate_files(db_path=None, limit=200):
    """找出文件名完全一致且文件大小相同的文件组。
    优化：单条 JOIN 查询替代 N+1。
    limit: 最多返回多少组（避免数据量大时卡死）。
    """
    conn = _conn(db_path)
    rows = conn.execute("""
        SELECT f.id, f.name, f.size, f.path, f.parent_path
        FROM files f
        INNER JOIN (
            SELECT name, size FROM files
            GROUP BY name, size
            HAVING COUNT(*) > 1
        ) dup ON f.name = dup.name AND f.size = dup.size
        ORDER BY f.name, f.size, f.path
    """).fetchall()
    conn.close()

    # 按 (name, size) 分组
    from collections import defaultdict
    grouped = defaultdict(list)
    for r in rows:
        key = (r["name"], r["size"])
        grouped[key].append({
            "id": r["id"],
            "path": r["path"],
            "parent_path": r["parent_path"],
        })

    # 组装结果，按浪费空间降序
    results = []
    for (name, size), files in grouped.items():
        cnt = len(files)
        wasted = (cnt - 1) * size
        results.append({
            "name": name,
            "size": size,
            "size_str": fmt_size(size),
            "count": cnt,
            "wasted_bytes": wasted,
            "wasted_str": fmt_size(wasted),
            "files": files,
        })

    results.sort(key=lambda x: x["wasted_bytes"], reverse=True)
    return results[:limit]


def get_dedup_summary(db_path=None):
    """去重总览（直接用 SQL 聚合，不加载全部数据）。"""
    conn = _conn(db_path)
    row = conn.execute("""
        SELECT COUNT(*) as groups,
               COALESCE(SUM(cnt), 0) as total_files,
               COALESCE(SUM((cnt - 1) * sz), 0) as wasted
        FROM (
            SELECT COUNT(*) as cnt, size as sz
            FROM files GROUP BY name, size HAVING COUNT(*) > 1
        )
    """).fetchone()
    conn.close()
    return {
        "total_groups": row["groups"],
        "total_dup_files": row["total_files"],
        "total_wasted_bytes": row["wasted"],
        "total_wasted_str": fmt_size(row["wasted"]),
    }


# ============================================================
# 大文件排行
# ============================================================

def get_largest_files(limit=100, db_path=None):
    """返回最大的 N 个文件。"""
    conn = _conn(db_path)
    rows = conn.execute(
        "SELECT id, name, path, size, mime_type FROM files "
        "ORDER BY size DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "path": r["path"],
            "size": r["size"],
            "size_str": fmt_size(r["size"]),
            "mime_type": r["mime_type"],
        }
        for r in rows
    ]


# ============================================================
# 关键词搜索
# ============================================================

def search_files(keyword, db_path=None):
    """按文件名模糊搜索。"""
    conn = _conn(db_path)
    rows = conn.execute(
        "SELECT id, name, path, size, mime_type FROM files "
        "WHERE name LIKE ? ORDER BY size DESC LIMIT 200",
        (f"%{keyword}%",),
    ).fetchall()
    conn.close()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "path": r["path"],
            "size": r["size"],
            "size_str": fmt_size(r["size"]),
            "mime_type": r["mime_type"],
        }
        for r in rows
    ]
