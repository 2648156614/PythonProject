import os
import sys
import logging
from datetime import datetime
from app import app, initialize_database, create_admin_user, repair_database


# 配置日志
def setup_logging(port: int):
    os.makedirs('logs', exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f'logs/waitress_{port}.log', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )


def get_port() -> int:
    """从环境变量读取端口，默认 5000"""
    raw = os.environ.get("PORT", "5000").strip()
    try:
        port = int(raw)
        if not (1 <= port <= 65535):
            raise ValueError("port out of range")
        return port
    except Exception:
        print(f"❌ 环境变量 PORT 无效: {raw}，请设置为 1~65535 的整数")
        sys.exit(1)


if __name__ == '__main__':
    port = get_port()
    print("🚀 启动物理考试系统服务器...")

    # 设置日志（不同端口不同日志文件）
    setup_logging(port)

    # 确保目录存在
    os.makedirs('static/images', exist_ok=True)

    try:
        # 初始化数据库（注意：多实例同时启动时可能会同时跑一遍）
        print("📊 初始化数据库...")
        initialize_database()
        create_admin_user()
        repair_database()

        # 生产环境使用 Waitress
        from waitress import serve

        print("🎯 服务器配置信息:")
        print(f"   - 地址: http://0.0.0.0:{port}")
        print(f"   - 线程数: 12")
        print(f"   - 最大连接: 2000")
        print(f"   - 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 50)

        # 优化后的生产配置
        serve(
            app,
            host='0.0.0.0',
            port=port,
            threads=12,              # 建议 4 实例时先用 12（比 16 更稳）
            connection_limit=2000,
            asyncore_use_poll=True,
            channel_timeout=300,
            ident=f"Physics Exam System :{port}"
        )

    except Exception as e:
        logging.error(f"服务器启动失败: {e}")
        print(f"❌ 服务器启动失败: {e}")
        sys.exit(1)
