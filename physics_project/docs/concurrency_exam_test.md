# 并发测试指南：模拟学生在线考试

本文给你一套“可以直接执行”的压测方案，覆盖你图里提到的两类核心链路：

- 压测 A：打开题目页 `GET /problem_ajax/<id>`
- 压测 B：提交答案 `POST /api/submit/<id>`

---

## 1. 测试目标与观察指标

## 压测 A（读路径）
- **接口**：`GET /problem_ajax/<id>`
- **重点看**：
  - P95/P99 响应时间
  - Redis 命中情况（题池是否有效）
  - Waitress 线程是否打满
  - CPU 是否飙高

## 压测 B（写路径）
- **接口**：`POST /api/submit/<id>`
- **重点看**：
  - MySQL 写入延迟
  - 每秒写入量（TPS）
  - 错题率高时触发“新题生成”的额外耗时
  - P95/P99 响应时间

> 建议按“先 A 后 B，再混合 AB”的顺序执行，便于定位瓶颈。

---

## 2. 压测前准备（必须）

1. 准备一批测试学生账号（至少与并发用户数同量级）。
2. 确保题库数据充足（避免因为题目不足导致结果失真）。
3. 在测试环境执行，不要直接压生产。
4. 固定一次测试的版本与配置（包括 `PROBLEM_POOL_TARGET_SIZE`、`PROBLEM_POOL_REFILL_BATCH`、`PROBLEM_TTL_SECONDS`），确保可对比。

---

## 3. 工具选择（推荐 Locust）

安装：

```bash
pip install locust
```

仓库已提供脚本：`docs/locustfile_exam.py`。

它会模拟：
- 登录建立会话
- 高频访问题目页（权重 4）
- 低频提交答案（权重 1）

---

## 4. 运行压测（基础命令）

### 4.1 交互式（看 Web UI）

```bash
cd physics_project
export LOADTEST_USERNAME=student001
export LOADTEST_PASSWORD=123456
locust -f docs/locustfile_exam.py --host http://127.0.0.1:5000
```

打开 `http://127.0.0.1:8089`：
- Users（并发用户）先从 20 开始，逐级到 50/100/200
- Spawn rate 建议 5~20/s，避免瞬时冲击掩盖真实瓶颈

### 4.2 无头模式（CI/批量跑）

```bash
cd physics_project
export LOADTEST_USERNAME=student001
export LOADTEST_PASSWORD=123456
locust -f docs/locustfile_exam.py \
  --host http://127.0.0.1:5000 \
  --headless -u 100 -r 10 -t 10m \
  --csv loadtest_exam
```

输出文件：
- `loadtest_exam_stats.csv`
- `loadtest_exam_failures.csv`
- `loadtest_exam_stats_history.csv`

---

## 5. 分场景执行（与你的截图对应）

## 场景 A：只压打开题目页

做法：把 `submit_answer` 任务临时注释掉（或把权重调成 0），仅保留 `open_problem`。

目标：验证 Redis + 模板渲染路径极限吞吐。

通过标准（示例）：
- P95 < 300ms
- 错误率 < 1%

## 场景 B：只压提交答案

做法：把 `open_problem` 临时注释掉，仅保留 `submit_answer`。

目标：验证 MySQL 写入和业务计算链路。

通过标准（示例）：
- P95 < 500ms
- 数据库无明显锁等待堆积

## 场景 C：混合压测（最接近真实考试）

做法：保持默认 4:1 读写比例。

可再按真实行为调整为：
- 考试前 5 分钟：读多写少（8:1）
- 交卷窗口：写请求占比升高（3:2）

---

## 6. 监控建议（压测时同时观察）

## 应用层

```bash
# 观察 Flask/Waitress 日志
# 若你用 start_server.py 启动，可在该终端直接看响应抖动/错误堆栈
```

## 系统层

```bash
# CPU/内存
top

# 每秒网络连接变化（Linux）
ss -s
```

## Redis

```bash
redis-cli info stats
redis-cli info memory
```

关注：`keyspace_hits` / `keyspace_misses`、内存增长是否异常。

## MySQL

```bash
mysql -uroot -p -e "SHOW GLOBAL STATUS LIKE 'Threads_running';"
mysql -uroot -p -e "SHOW ENGINE INNODB STATUS\G"
```

关注：活跃线程、锁等待、事务堆积。

---

## 7. 常见误区与修正

1. **只看平均响应时间，不看 P95/P99**
   - 修正：考试场景必须重点看尾延迟。

2. **直接一步拉满并发**
   - 修正：分阶段升压（20→50→100→200），每档至少跑 5~10 分钟。

3. **账号、题库、缓存未预热**
   - 修正：先做 1~2 分钟预热流量，再记正式结果。

4. **只测 GET，不测 POST**
   - 修正：提交答案链路通常更容易成为瓶颈，必须单独测。

---

## 8. 推荐的基线实验矩阵

- 20 并发，10 分钟（基线）
- 50 并发，10 分钟（常规考试）
- 100 并发，10 分钟（高峰）
- 200 并发，10 分钟（极限）

每次固定：
- 读写比例
- 账号池
- 题库规模
- 服务配置

这样你才能横向对比优化是否有效（例如 Redis 题池参数调整、SQL 索引优化）。

---

## 9. 结果判读模板（建议记录）

每次压测记录：
- Git 提交号
- 并发用户数 / 爬升速率
- 场景（A/B/C）
- 平均 / P95 / P99
- 错误率
- Redis 命中率
- MySQL 线程与锁等待
- CPU / 内存峰值

最后按“先出现瓶颈的层”排序优化（一般是 DB > 应用线程池 > 缓存）。

---

## 10. 一句话结论

你要模拟“学生考试并发”，最实用的方法就是：
- 用 `docs/locustfile_exam.py` 做读写混合压测；
- 分开跑 A（开题）和 B（提交）定位瓶颈；
- 全程盯 P95/P99 + Redis 命中 + MySQL 写入与锁等待。

