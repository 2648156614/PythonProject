#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys

def check_package(package_name, version_attr='__version__'):
    """检查包是否安装并获取版本"""
    try:
        module = __import__(package_name)
        if hasattr(module, version_attr):
            version = getattr(module, version_attr)
            return True, version
        else:
            return True, "未知版本"
    except ImportError:
        return False, None

def main():
    print("🔍 检查考试系统环境...")
    print("=" * 50)

    # 必需包列表
    required_packages = [
        ('flask', '__version__'),
        ('mysql.connector', '__version__'),
        ('sympy', '__version__'),
        ('waitress', '__version__'),
        ('werkzeug', '__version__'),
    ]

    # 可选包列表
    optional_packages = [
        ('win32service', None),  # pywin32
        ('numpy', '__version__'),
    ]

    all_ok = True

    # 检查必需包
    print("📦 必需依赖检查:")
    for package, version_attr in required_packages:
        installed, version = check_package(package, version_attr)
        if installed:
            print(f"   ✅ {package}: {version}")
        else:
            print(f"   ❌ {package}: 未安装")
            all_ok = False

    print("\n📦 可选依赖检查:")
    for package, version_attr in optional_packages:
        installed, version = check_package(package, version_attr)
        if installed:
            print(f"   ✅ {package}: {version}")
        else:
            print(f"   ⚠️  {package}: 未安装（可选）")

    print("\n" + "=" * 50)
    if all_ok:
        print("🎉 所有必需依赖已安装，环境准备就绪！")
        print("🚀 可以启动考试系统了")
    else:
        print("❌ 部分必需依赖缺失，请运行: pip install -r requirements.txt")
        sys.exit(1)

if __name__ == "__main__":
    main()