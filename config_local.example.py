# 复制此文件为 config_local.py 并填入你的真实信息
# 这个文件包含账号凭证，不会提交到 Git

# PikPak 邮箱
PIKPAK_USERNAME = "your_email@example.com"

# 从浏览器获取的 device_id（F12 -> Application -> Local Storage -> deviceid）
# 只需中间的哈希部分，去掉 "wdi10." 前缀
DEVICE_ID = "your_device_hash_here"

# ===== 以下为可选：直接用 token 登录（推荐，绕过 API 风控） =====
# 从浏览器获取（F12 -> Application -> Local Storage -> credentials_XXX）
PIKPAK_ACCESS_TOKEN = ""
PIKPAK_REFRESH_TOKEN = ""

# 浏览器的 captcha_token（F12 -> Application -> Local Storage -> captcha_XXX）
# 过期后需重新获取
PIKPAK_CAPTCHA_TOKEN = ""

# 网络代理（可选）。应用不读 Windows 系统代理，只认这里。
# 本机有代理客户端时填，例如 v2rayN/Clash：http://127.0.0.1:10808
# 留空 "" 表示直连
PIKPAK_PROXY = ""
