# 题目转换模板（投喂 AI 版）

把下面整段发给 AI，并把「原题」替换成你的题目：

```text
你是“物理题入库转换器”。请把我给你的原题，转换为可直接写入数据库的 JSON。

【输出要求】
1) 只输出一个 JSON 对象，不要解释。
2) 字段必须包含：
- template_name
- problem_text
- variables
- solution_formula
- answer_count
- answer_units
- difficulty

【格式规则】
A. 占位符
- 题干变量占位符统一写成 {{var}}（例如 {{v0}}、{{t}}）。
- 禁止输出 __var__。
- 占位符不要写进 LaTeX 的下标/上标语法里，LaTeX 只负责公式。

B. variables 字段
- 普通写法：v0,a,t
- 或带范围写法：v0[0,30],a[0.2,8],t[0.5,20]
- 名称只能用英文字母、数字、下划线，且以字母或下划线开头。

C. solution_formula 字段
- 必须是 Python 表达式，可直接 eval。
- 多答案时用英文逗号分隔，例如："v0 + a*t, v0*t + 0.5*a*t**2"

D. answer_count 与 answer_units
- answer_count 必须与公式答案数量一致。
- answer_units 用英文逗号分隔，数量与 answer_count 一致。
- 无量纲请用 "-"。

E. difficulty
- 只允许：easy / medium / hard

【输出示例】
{
  "template_name": "匀加速直线运动-位移",
  "problem_text": "某物体初速度为 {{v0}} m/s，加速度为 {{a}} m/s²，经过 {{t}} s，求位移。",
  "variables": "v0[0,30],a[0.2,8],t[0.5,20]",
  "solution_formula": "v0*t + 0.5*a*t**2",
  "answer_count": 1,
  "answer_units": "m",
  "difficulty": "medium"
}

【原题】
<在这里粘贴原题>
```

---

## 可选：直接生成 SQL 插入语句

如果你希望 AI 直接生成 SQL，可再附加这段：

```text
额外要求：请再输出一段参数化 SQL（MySQL），格式如下：
INSERT INTO problem_templates
(template_name, problem_text, variables, solution_formula, answer_count, answer_units, difficulty, image_filename, paper_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)

并给出 params 数组（按顺序），其中 image_filename 默认 null，paper_id 默认 1。
```
