"""Locust 压测脚本：仅对登录接口进行压力测试。

目标：只压测 POST /login，不混入答题、取题等请求。

使用示例：
  # 50 并发（预热）
  locust -f docs/locustfile_login_only.py --host http://127.0.0.1:5000 \
    --headless -u 50 -r 10 -t 2m

  # 100 并发（基线）
  locust -f docs/locustfile_login_only.py --host http://127.0.0.1:5000 \
    --headless -u 100 -r 20 -t 3m

  # 200 并发（冲击）
  locust -f docs/locustfile_login_only.py --host http://127.0.0.1:5000 \
    --headless -u 200 -r 30 -t 3m

可选环境变量：
  LOADTEST_PASSWORD=123456
  LOADTEST_USERNAME_PREFIX=student
  LOADTEST_USERNAME_WIDTH=3
  LOADTEST_USER_START=1
  LOADTEST_USER_END=200
"""

from __future__ import annotations

import os
import random

from locust import FastHttpUser, between, task


def _pick_username() -> str:
    """从给定账号区间内随机挑选一个用户名。"""
    prefix = os.getenv("LOADTEST_USERNAME_PREFIX", "student")
    width = int(os.getenv("LOADTEST_USERNAME_WIDTH", "3"))
    start = int(os.getenv("LOADTEST_USER_START", "1"))
    end = int(os.getenv("LOADTEST_USER_END", "200"))

    if end < start:
        start, end = end, start

    user_no = random.randint(start, end)
    return f"{prefix}{user_no:0{width}d}"


class LoginOnlyUser(FastHttpUser):
    """仅循环请求登录接口，聚焦 /login 延迟与吞吐。"""

    # 纯登录压测建议尽量降低等待，放大接口压力。
    wait_time = between(0.0, 0.2)

    def on_start(self):
        self._password = os.getenv("LOADTEST_PASSWORD", "123456")

    @task
    def login(self):
        username = _pick_username()

        with self.client.post(
            "/login",
            data={"username": username, "password": self._password},
            name="POST /login",
            allow_redirects=True,
            catch_response=True,
        ) as resp:
            if resp.status_code >= 400:
                resp.failure(f"登录失败 status={resp.status_code}, user={username}")
                return

            if "用户名或密码错误" in resp.text:
                resp.failure(f"登录失败（账号密码错误）user={username}")
                return

            resp.success()
