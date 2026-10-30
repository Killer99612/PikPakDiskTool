import os
import sys

# ---------------- 项目根目录 ----------------
# 打包成 EXE 后固定为 EXE 所在目录，保证 data/、config_local.py 都在 EXE 旁边持久化
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# ---------------- PikPak 账号（敏感，放 config_local.py）----------------
PIKPAK_USERNAME = "1368426646@qq.com"
DEVICE_ID = "c7008507bada402eb7b9ac7f1c2cf595"  # 从浏览器 Local Storage 获取

# PikPak token（可选，填了就免密码登录）
PIKPAK_ACCESS_TOKEN = ""
PIKPAK_REFRESH_TOKEN = ""
# 浏览器的 captcha_token（过期后需重新获取）
PIKPAK_CAPTCHA_TOKEN = ""
# client_id（从浏览器 Local Storage 的 credentials_ 后缀获取）
PIKPAK_CLIENT_ID = "YUMx5nl8ZU8Ap8pm"
# 网络代理（可选），例：http://127.0.0.1:10808 ；留空直连
PIKPAK_PROXY = ""

# ---------------- 性能 ----------------
LIST_PAGE_SIZE = 200
SCAN_CONCURRENCY = 16

# ---------------- 存储路径 ----------------
TOKEN_PATH = os.path.join(DATA_DIR, "token.json")
DB_PATH = os.path.join(DATA_DIR, "disk.db")

# ---------------- 本地覆盖（敏感信息）----------------
# 从 BASE_DIR 下的 config_local.py 加载（开发与 EXE 模式行为一致，改完重启生效）
try:
    import importlib.util as _ilu

    _cl_path = os.path.join(BASE_DIR, "config_local.py")
    if os.path.exists(_cl_path):
        _spec = _ilu.spec_from_file_location("config_local", _cl_path)
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        for _k in dir(_mod):
            if not _k.startswith("_"):
                globals()[_k] = getattr(_mod, _k)
except Exception:
    pass

os.makedirs(DATA_DIR, exist_ok=True)
