# 更新日志

版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)（vX.Y.Z）：
- **X** 主版本：不兼容的大改版
- **Y** 次版本：新增功能（向后兼容）
- **Z** 修订号：问题修复（向后兼容）

每个版本对应一个 git tag（`vX.Y.Z`）和 GitHub Release（附带单文件 EXE）。

## [v1.0.0] - 2026-10-30

首个版本化发布。

### 新增
- **在线播放**：实时浏览网盘目录（懒加载/分页），视频/图片/音频在线播放
- **播放器**：可拖动进度条、倍速（0.5×~2×）、清晰度切换（保留进度）、音量、全屏、快捷键（空格/←→/↑↓/M/F）、控制栏自动隐藏
- **目录文件列表**：目录空间页的叶子目录现在显示其中的文件
- **单文件 EXE**：`build_exe.bat` 一键打包，双击即用、自动打开浏览器，数据与配置在 exe 旁
- **代理配置**：`config_local.py` 的 `PIKPAK_PROXY`（留空直连，应用不读系统代理）
- **错误提示**：登录/导入/浏览失败时给出可操作的原因与建议

### 修复
- captcha_token 获取失败（captcha_sign 需配套 android client_id，web client_id 会报 invalid captcha_sign）
- 密码登录 404（signin 需与 client_secret 配套的 android 客户端身份）
- 登录后容量验证缺少 captcha 报 "Verification code is invalid"
- token 导入验证脆弱（改为手动构造客户端 + JWT 提取 user_id + 自动刷新）
- 请求超时 10s 过短导致的误报（统一为 30s）
