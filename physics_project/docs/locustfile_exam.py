"""Locust 脚本：模拟学生在线考试行为。

使用示例：
  locust -f docs/locustfile_exam.py --host http://127.0.0.1:5000
"""

import os
import random

from locust import HttpUser, between, task


class ExamStudentUser(HttpUser):
    # 每个虚拟学生两次请求间隔（秒）
    wait_time = between(0.5, 2.0)

    def on_start(self):
        # 注意：需要在环境变量中导出测试账号，避免把账号硬编码到代码库
        username = os.getenv("LOADTEST_USERNAME", "student001")
        password = os.getenv("LOADTEST_PASSWORD", "123456")

        # 登录，建立 session cookie
        self.client.post(
            "/login",
            data={"username": username, "password": password},
            name="POST /login",
        )

    @task(4)
    def open_problem(self):
        """高频操作：打开题目页（命中 Redis 题池与模板渲染）。"""
        problem_id = random.randint(1, 40)
        self.client.get(f"/problem_ajax/{problem_id}", name="GET /problem_ajax/[id]")

    @task(1)
    def submit_answer(self):
        """低频但重写入操作：提交答案（MySQL 写入 + 可能触发新题生成）。"""
        problem_id = random.randint(1, 40)

        # 系统支持多答案输入 answer_1, answer_2 ...，这里先模拟单答案题型
        payload = {"answer_1": str(round(random.uniform(1, 100), 2))}

        self.client.post(
            f"/api/submit/{problem_id}",
            data=payload,
            name="POST /api/submit/[id]",
        )
