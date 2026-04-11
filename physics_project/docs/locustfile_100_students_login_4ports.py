"""Locust 压测脚本：基于 100 名学生模型，仅压测四端口登录。

设计目标：
1) 复用 `locustfile_100_students.py` 的“按用户序号分配账号”逻辑，避免大量用户撞同一账号。
2) 仅压测 `POST /login`，不混入答题请求。
3) 支持在 5000/5001/5002/5003 四个 Waitress 端口间随机分发请求。

Windows（PowerShell）示例：
  $env:LOADTEST_MULTI_HOST_BASE="http://127.0.0.1"
  $env:LOADTEST_TARGET_PORTS="5000,5001,5002,5003"
  $env:LOADTEST_PASSWORD="123456"
  locust -f docs/locustfile_100_students_login_4ports.py --headless -u 100 -r 20 -t 5m --csv login_4ports_100

Windows（CMD）示例：
  set LOADTEST_MULTI_HOST_BASE=http://127.0.0.1
  set LOADTEST_TARGET_PORTS=5000,5001,5002,5003
  set LOADTEST_PASSWORD=123456
  locust -f docs/locustfile_100_students_login_4ports.py --headless -u 100 -r 20 -t 5m --csv login_4ports_100
"""

from __future__ import annotations

import os
import random
from itertools import count

from locust import FastHttpUser, between, task


_USER_COUNTER = count(1)


def _build_username(index: int) -> str:
    prefix = os.getenv("LOADTEST_USERNAME_PREFIX", "student")
    width = int(os.getenv("LOADTEST_USERNAME_WIDTH", "3"))
    start = int(os.getenv("LOADTEST_USER_START", "1"))
    end = int(os.getenv("LOADTEST_USER_END", "200"))

    if end < start:
        start, end = end, start

    span = max(end - start + 1, 1)
    user_no = start + ((index - 1) % span)
    return f"{prefix}{user_no:0{width}d}"


def _parse_ports() -> list[int]:
    raw = os.getenv("LOADTEST_TARGET_PORTS", "5000,5001,5002,5003").strip()
    ports: list[int] = []
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        port = int(p)
        if port <= 0:
            raise ValueError(f"无效端口: {port}")
        ports.append(port)
    if not ports:
        raise ValueError("LOADTEST_TARGET_PORTS 不能为空")
    return ports


class Login100StudentsFourPortsUser(FastHttpUser):
    """100 学生模型：循环压测四端口登录。"""

    # 纯登录压测：等待尽量短，突出接口吞吐与延迟。
    wait_time = between(0.0, 0.2)

    def on_start(self):
        idx = next(_USER_COUNTER)
        self._username = _build_username(idx)
        self._password = os.getenv("LOADTEST_PASSWORD", "123456")
        self._multi_host_base = os.getenv("LOADTEST_MULTI_HOST_BASE", "http://127.0.0.1").rstrip("/")
        self._ports = _parse_ports()

    def _build_login_url(self) -> str:
        port = random.choice(self._ports)
        return f"{self._multi_host_base}:{port}/login"

    @task
    def login(self):
        login_url = self._build_login_url()
        with self.client.post(
            login_url,
            data={"username": self._username, "password": self._password},
            name="POST /login (4 ports)",
            allow_redirects=True,
            catch_response=True,
        ) as resp:
            if resp.status_code >= 400:
                resp.failure(f"登录失败 status={resp.status_code}, user={self._username}")
                return
            if "用户名或密码错误" in resp.text:
                resp.failure(f"登录失败（账号密码错误）user={self._username}")
                return
            resp.success()
