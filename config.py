import os

# ---------------- 项目根目录 ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# ---------------- PikPak 账号（敏感，放 config_local.py）----------------
PIKPAK_USERNAME = "your_email@example.com"
DEVICE_ID = "your_device_id_here"  # 从浏览器 Local Storage 获取

# PikPak token（可选，填了就免密码登录）
PIKPAK_ACCESS_TOKEN = ""
PIKPAK_REFRESH_TOKEN = ""
# 浏览器的 captcha_token（过期后需重新获取）
PIKPAK_CAPTCHA_TOKEN = ""
# client_id（从浏览器 Local Storage 的 credentials_ 后缀获取）
PIKPAK_CLIENT_ID = "YUMx5nl8ZU8Ap8pm"

# ---------------- 性能 ----------------
LIST_PAGE_SIZE = 200
SCAN_CONCURRENCY = 16

# ---------------- 存储路径 ----------------
TOKEN_PATH = os.path.join(DATA_DIR, "token.json")
DB_PATH = os.path.join(DATA_DIR, "disk.db")

# ---------------- 本地覆盖（敏感信息）----------------
try:
    from config_local import *   # noqa
except ImportError:
    pass

os.makedirs(DATA_DIR, exist_ok=True)
