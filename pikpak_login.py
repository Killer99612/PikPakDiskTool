"""PikPak 命令行登录 —— 获取并保存 token。"""
import asyncio
import json
import getpass

from pikpakapi import PikPakApi

import config
from pikpak_client import build_httpx_args


def save_token(client: PikPakApi):
    data = client.to_dict()
    with open(config.TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ token 已保存到: {config.TOKEN_PATH}")


async def main():
    print("=" * 50)
    print("PikPak 登录")
    print("=" * 50)
    print(f"账号(邮箱): {config.PIKPAK_USERNAME}")

    if "your_email" in config.PIKPAK_USERNAME or "你的邮箱" in config.PIKPAK_USERNAME:
        print("\n❌ 请先在 config_local.py 里把 PIKPAK_USERNAME 改成你的真实邮箱！")
        return

    password = getpass.getpass("请输入 PikPak 密码（输入时不显示）: ")

    client = PikPakApi(
        username=config.PIKPAK_USERNAME,
        password=password,
        device_id=config.DEVICE_ID,
        httpx_client_args=build_httpx_args(),
    )

    try:
        print("\n正在登录 ...")
        await client.login()
        print("✅ 登录成功！")

        quota = await client.get_quota_info()
        q = quota.get("quota", {})
        limit = int(q.get("limit", 0)) / (1024**3)
        usage = int(q.get("usage", 0)) / (1024**3)
        print(f"✅ token 有效！网盘容量: 已用 {usage:.1f} GB / 共 {limit:.1f} GB")

        save_token(client)
        print("\n🎉 登录完成！")
    except Exception as e:
        print(f"\n❌ 登录失败: {e}")
    finally:
        try:
            await client.httpx_client.aclose()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
