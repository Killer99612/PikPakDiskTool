# 🍅 PikPakDiskTool

> PikPak 云盘磁盘空间分析 + 文件去重工具 —— 按文件名+大小精准识别重复文件，一键清理释放空间。

## ✨ 功能

- **📂 目录空间分析** — 按文件夹层级展示空间占用，逐层下钻定位大目录
- **🔍 智能去重** — 基于「文件名 + 大小」精确匹配识别重复文件，零下载开销
- **🗑️ 一键清理** — 支持单组删除和批量去重，文件移入回收站可恢复
- **📊 大文件排行** — 快速定位空间大户
- **🔎 关键词搜索** — 按文件名模糊搜索
- **📊 网盘容量总览** — 已用/总容量一目了然

## 🆚 与传统去重方式的区别

| | 传统（缩略图/pHash） | 本工具（文件名+大小） |
|---|---|---|
| 原理 | 下载缩略图逐像素比对 | 仅比对文件元数据 |
| 速度 | 慢（需下载+计算） | **秒级**（纯 API 遍历） |
| 磁盘开销 | 数十 GB 缩略图缓存 | **几乎为零** |
| 准确率 | 高（视觉比对） | 高（name+size 双重精确匹配） |

## 🛠️ 技术栈

- **后端**：Python + Flask
- **云盘接口**：pikpakapi（非官方 PikPak API）
- **存储**：SQLite（本地元数据，轻量）

## 📦 安装

```bash
git clone https://github.com/YOUR_USERNAME/PikPakDiskTool.git
cd PikPakDiskTool

# 创建虚拟环境
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

# 安装依赖
pip install -r requirements.txt
```

## ⚙️ 配置

```bash
copy config_local.example.py config_local.py   # Windows
# cp config_local.example.py config_local.py   # macOS / Linux
```

编辑 `config_local.py`，填入你的 PikPak 账号信息：

### 获取参数（从浏览器）

1. 浏览器打开 [mypikpak.com](https://mypikpak.com) 并登录
2. 按 **F12** 打开开发者工具
3. **Application** → **Local Storage** → `mypikpak.com`

需要的字段：

| 字段 | 位置 | 说明 |
|------|------|------|
| `deviceid` | Local Storage | 取哈希部分（去掉 `wdi10.` 前缀） |
| `credentials_XXX` | Local Storage | 展开获取 `access_token` 和 `refresh_token` |
| `captcha_XXX` | Local Storage | 展开获取 `captcha_token` |
| `client_id` | `credentials_` 的后缀 | 如 `YUMx5nl8ZU8Ap8pm` |

> **提示**：token 约 2 小时过期，过期后需重新获取。captcha_token 过期后也需重新复制。

## 🚀 使用

```bash
python app.py
```

浏览器打开 `http://127.0.0.1:5001`。

### 操作流程

1. **扫描** — 点击「开始全盘扫描」，收集所有文件元数据
2. **查看** — 目录空间 / 文件去重 / 大文件排行
3. **清理** — 在「文件去重」页点击「一键批量去重」

### 删除安全机制

- 文件默认移入**回收站**（可恢复），不是彻底删除
- 每个重复组**保留一份**（可手动选择保留哪个）
- 删除前弹窗确认，显示释放空间预估

## 📁 项目结构

```
PikPakDiskTool/
├── app.py                  # Flask Web 应用 + API
├── config.py               # 配置（不含敏感信息）
├── config_local.example.py # 配置模板
├── pikpak_client.py        # PikPak API 封装 + 认证
├── pikpak_login.py         # 命令行登录
├── scanner.py              # 网盘遍历 + 元数据收集
├── analyzer.py             # 空间分析 + 去重算法
├── templates/
│   └── index.html          # Web 界面
├── requirements.txt
└── README.md
```

## ⚠️ 注意事项

- `config_local.py` 和 `data/` 包含账号凭证，已被 `.gitignore` 排除，**勿泄露**
- 扫描为全盘重建，每次覆盖旧数据（元数据很轻量，速度取决于 API 遍历）
- 去重基于「文件名 + 大小」精确匹配，不做内容比对（快速、零下载）
- 请遵守 PikPak 服务条款，仅供个人学习使用

## 🙏 致谢

- [pikpakapi](https://github.com/awaw00/pikpakapi) — PikPak 非官方 API 封装

## 📄 License

MIT
