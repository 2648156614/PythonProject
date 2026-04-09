"""批量导入压测用户脚本（用于 Locust 100+ 并发登录场景）。

示例：
  python docs/import_loadtest_users.py --start 1 --end 200 --prefix student --password 123456

可选：
  python docs/import_loadtest_users.py --start 1 --end 300 --prefix student \
    --password 123456 --mode upsert --plain-password
"""

from __future__ import annotations

import argparse
import os

import mysql.connector
from werkzeug.security import generate_password_hash


def build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量创建/更新压测账号")
    parser.add_argument("--start", type=int, default=1, help="起始编号（含）")
    parser.add_argument("--end", type=int, default=200, help="结束编号（含）")
    parser.add_argument("--prefix", type=str, default="student", help="用户名前缀")
    parser.add_argument("--width", type=int, default=3, help="编号补零宽度（如 3 => 001）")
    parser.add_argument("--password", type=str, default="123456", help="统一密码")
    parser.add_argument(
        "--mode",
        choices=("insert-ignore", "upsert"),
        default="upsert",
        help="insert-ignore: 已存在则跳过；upsert: 已存在则更新密码和姓名",
    )
    parser.add_argument(
        "--plain-password",
        action="store_true",
        help="使用明文密码写入（默认写哈希，建议不要开启）",
    )
    return parser.parse_args()


def get_db_config() -> dict:
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", "123456"),
        "database": os.getenv("DB_NAME", "physics_new3"),
    }


def build_user_rows(args: argparse.Namespace) -> list[tuple[str, str, str, bool]]:
    if args.start > args.end:
        raise ValueError("--start 不能大于 --end")
    if args.width < 1:
        raise ValueError("--width 必须 >= 1")

    password_value = args.password if args.plain_password else generate_password_hash(args.password)
    rows = []
    for i in range(args.start, args.end + 1):
        username = f"{args.prefix}{i:0{args.width}d}"
        name = f"压测用户{i:0{args.width}d}"
        rows.append((username, password_value, name, True))
    return rows


def main() -> None:
    args = build_args()
    rows = build_user_rows(args)
    db_config = get_db_config()

    print("🚀 准备导入压测用户...")
    print(f"   范围: {args.start} ~ {args.end} ({len(rows)} 个)")
    print(f"   前缀: {args.prefix}")
    print(f"   密码存储: {'明文' if args.plain_password else '哈希'}")
    print(f"   导入模式: {args.mode}")
    print(f"   数据库: {db_config['host']}/{db_config['database']}")

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    try:
        if args.mode == "insert-ignore":
            sql = """
                INSERT IGNORE INTO users (username, password, name, password_changed)
                VALUES (%s, %s, %s, %s)
            """
        else:
            sql = """
                INSERT INTO users (username, password, name, password_changed)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    password = VALUES(password),
                    name = VALUES(name),
                    password_changed = VALUES(password_changed)
            """

        cursor.executemany(sql, rows)
        conn.commit()
        print("✅ 导入完成")
        print(f"   影响行数（MySQL 统计）: {cursor.rowcount}")
    except Exception as exc:
        conn.rollback()
        print(f"❌ 导入失败: {exc}")
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
