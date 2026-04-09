"""Locust 压测脚本：100 名学生并发登录 + 答题场景。

使用示例（Web UI）:
  locust -f docs/locustfile_100_students.py --host http://127.0.0.1:5000

无 UI 一键压测（推荐）:
  locust -f docs/locustfile_100_students.py --host http://127.0.0.1:5000 \
    --headless -u 100 -r 20 -t 5m

可选环境变量:
  LOADTEST_PASSWORD=123456
  LOADTEST_USERNAME_PREFIX=student
  LOADTEST_USER_START=1
  LOADTEST_USER_END=200
  LOADTEST_MIN_PROBLEM_ID=1
  LOADTEST_MAX_PROBLEM_ID=40
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

    span = max(end - start + 1, 1)
    offset = (index - 1) % span
    user_no = start + offset
    return f"{prefix}{user_no:0{width}d}"


class Exam100StudentsUser(FastHttpUser):
    """模拟学生登录后浏览题目并提交答案。"""

    wait_time = between(0.2, 1.0)

    def on_start(self):
        self._min_problem_id = int(os.getenv("LOADTEST_MIN_PROBLEM_ID", "1"))
        self._max_problem_id = int(os.getenv("LOADTEST_MAX_PROBLEM_ID", "40"))
        self._password = os.getenv("LOADTEST_PASSWORD", "123456")

        idx = next(_USER_COUNTER)
        self._username = _build_username(idx)
        self._current_problem_id = self._min_problem_id

        with self.client.post(
            "/login",
            data={"username": self._username, "password": self._password},
            name="POST /login",
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

    @task(5)
    def open_problem(self):
        problem_id = random.randint(self._min_problem_id, self._max_problem_id)
        self._current_problem_id = problem_id
        with self.client.get(
            f"/problem_ajax/{problem_id}",
            name="GET /problem_ajax/[id]",
            catch_response=True,
        ) as resp:
            if resp.status_code >= 400:
                resp.failure(f"打开题目失败 status={resp.status_code}")
            else:
                resp.success()

    @task(2)
    def submit_answer(self):
        problem_id = self._current_problem_id
        payload = {
            "answer": str(round(random.uniform(1, 100), 2)),
            "time_taken": round(random.uniform(3, 60), 2),
        }

        with self.client.post(
            f"/api/submit/{problem_id}",
            json=payload,
            name="POST /api/submit/[id]",
            catch_response=True,
        ) as resp:
            if resp.status_code >= 400:
                resp.failure(f"提交失败 status={resp.status_code}")
            else:
                resp.success()
