import os
import sys
import logging
from datetime import datetime
from app import app, initialize_database, create_admin_user, repair_database


# 配置日志
def setup_logging():
    os.makedirs('logs', exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/waitress.log', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )


if __name__ == '__main__':
    print("🚀 启动物理考试系统服务器...")

    # 设置日志
    setup_logging()

    # 确保目录存在
    os.makedirs('static/images', exist_ok=True)

    try:
        # 初始化数据库
        print("📊 初始化数据库...")
        initialize_database()
        create_admin_user()
        repair_database()

        # 生产环境使用 Waitress
        from waitress import serve

        print("🎯 服务器配置信息:")
        print(f"   - 地址: http://0.0.0.0:5000")
        print(f"   - 线程数: 16")
        print(f"   - 最大连接: 2000")
        print(f"   - 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 50)

        # 优化后的生产配置
        serve(
            app,
            host='0.0.0.0',
            port=5000,
            threads=16,  # 增加线程应对并发
            connection_limit=2000,  # 提高连接限制
            asyncore_use_poll=True,  # 使用 poll 提高性能
            channel_timeout=300,  # 增加超时时间
            ident="Physics Exam System"  # 服务标识
        )

    except Exception as e:
        logging.error(f"服务器启动失败: {e}")
        print(f"❌ 服务器启动失败: {e}")
        sys.exit(1)