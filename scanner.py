"""扫描器：遍历 PikPak 网盘，将文件元数据写入 SQLite。"""
import asyncio
import sqlite3
import time

import config


def init_db(db_path=None):
    """建表（幂等）。"""
    db = db_path or config.DB_PATH
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            size INTEGER NOT NULL DEFAULT 0,
            path TEXT NOT NULL,
            parent_path TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'file',
            mime_type TEXT DEFAULT '',
            indexed_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
        CREATE INDEX IF NOT EXISTS idx_files_parent ON files(parent_path);
        CREATE INDEX IF NOT EXISTS idx_files_name_size ON files(name, size);
    """)
    conn.commit()
    conn.close()


def clear_db(db_path=None):
    db = db_path or config.DB_PATH
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM files")
    conn.commit()
    conn.close()


async def scan_drive(progress_cb=None, db_path=None):
    """全盘扫描：遍历所有文件夹，收集每个文件的 name/size/path。
    progress_cb(stage, current_count, message) 可选。"""
    from pikpak_client import load_client, walk_all_files

    db = db_path or config.DB_PATH
    init_db(db)

    client = load_client()
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")

    total_files = 0
    total_bytes = 0
    folders_seen = 0
    t0 = time.time()

    try:
        # 先清空旧数据，全盘重建（比增量更可靠、逻辑更简单）
        conn.execute("DELETE FROM files")
        conn.commit()

        batch = []
        async for prefix, files in walk_all_files(client):
            folders_seen += 1
            parent_path = prefix.rstrip("/")

            for f in files:
                fid = f.get("id", "")
                name = f.get("name", "")
                size = int(f.get("size", 0) or 0)
                mime = f.get("mime_type", "")
                full_path = prefix + name

                batch.append((
                    fid, name, size, full_path,
                    parent_path or "", "file", mime, time.time(),
                ))
                total_files += 1
                total_bytes += size

            if len(batch) >= 500:
                conn.executemany(
                    "INSERT OR REPLACE INTO files (id,name,size,path,parent_path,kind,mime_type,indexed_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    batch,
                )
                conn.commit()
                batch.clear()

            if progress_cb and folders_seen % 10 == 0:
                progress_cb(
                    "scanning", total_files,
                    f"已扫描 {folders_seen} 个目录，发现 {total_files} 个文件，累计 {fmt_size(total_bytes)}",
                )

        # 写入剩余
        if batch:
            conn.executemany(
                "INSERT OR REPLACE INTO files (id,name,size,path,parent_path,kind,mime_type,indexed_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                batch,
            )
            conn.commit()

        elapsed = time.time() - t0
        result = {
            "total_files": total_files,
            "total_bytes": total_bytes,
            "total_size_str": fmt_size(total_bytes),
            "folders_scanned": folders_seen,
            "elapsed_sec": round(elapsed, 1),
        }
        if progress_cb:
            progress_cb("done", total_files, f"扫描完成：{total_files} 个文件，{fmt_size(total_bytes)}")
        return result

    finally:
        conn.close()
        try:
            await client.httpx_client.aclose()
        except Exception:
            pass


def fmt_size(n: int) -> str:
    """人类可读的文件大小。"""
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024.0
        if n < 1024:
            return f"{n:.2f} {unit}"
    return f"{n:.2f} PB"
