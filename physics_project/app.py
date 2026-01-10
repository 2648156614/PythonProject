import csv
import io
import json
import math
import os
import random
import re
import time
import traceback
import uuid
from datetime import datetime
from functools import wraps
from math import pi, log

import mysql.connector
import numpy as np
import redis
import sympy as sp
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from werkzeug.utils import secure_filename

app = Flask(__name__, template_folder='templates', static_folder='static', static_url_path='/static')
app.secret_key = 'your_secret_key_here'

# Redis 配置
redis_url = os.getenv('REDIS_URL', 'redis://172.17.66.87:6379/0')
redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
POOL_TARGET = 50
POOL_LOW_WATER = 25
POOL_REFILL_BATCH = 10
PROBLEM_TTL_SECONDS = int(os.getenv('PROBLEM_TTL_SECONDS', 900))

TEMPLATE_CACHE = {}
TEMPLATE_CACHE_TS = 0

PROBLEM_POOL_TARGET_SIZE = int(os.getenv('PROBLEM_POOL_TARGET_SIZE', 20))
PROBLEM_POOL_REFILL_BATCH = int(os.getenv('PROBLEM_POOL_REFILL_BATCH', 10))
PROBLEM_TTL_SECONDS = int(os.getenv('PROBLEM_TTL_SECONDS', 900))

# 数据库配置
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '123456',
    'database': 'physics_new3'
}

# 图片上传配置
UPLOAD_FOLDER = 'static/images'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_file(file):
    """保存上传的文件"""
    if file and file.filename != '' and allowed_file(file.filename):
        # 生成安全的文件名
        filename = secure_filename(file.filename)
        # 确保文件名唯一
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], filename)):
            filename = f"{base}_{counter}{ext}"
            counter += 1

        # 保存文件
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        return filename
    return None


def get_db_connection():
    """获取数据库连接"""
    try:
        conn = mysql.connector.connect(**db_config)
        return conn
    except mysql.connector.Error as err:
        print(f"数据库连接失败：{err}")
        return None


def get_pool_key(template_id):
    return f"exam:pool:{template_id}"


def get_problem_key(token):
    return f"exam:problem:{token}"


def cache_problem_with_token(token, problem_data):
    """将题目数据写入Redis并设置TTL"""
    redis_client.setex(get_problem_key(token), PROBLEM_TTL_SECONDS, json.dumps(problem_data))


def get_problem_by_token(token):
    """通过token从Redis获取题目数据"""
    if not token:
        return None
    raw = redis_client.get(get_problem_key(token))
    if not raw:
        return None
    try:
        redis_client.expire(get_problem_key(token), PROBLEM_TTL_SECONDS)
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def load_template_from_db(template_id):
    conn = get_db_connection()
    if not conn:
        return None
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM problem_templates WHERE id = %s", (template_id,))
    template = cursor.fetchone()
    cursor.close()
    conn.close()
    return template


def get_template(template_id):
    global TEMPLATE_CACHE, TEMPLATE_CACHE_TS
    if template_id in TEMPLATE_CACHE:
        return TEMPLATE_CACHE[template_id]

    template = load_template_from_db(template_id)
    if template:
        TEMPLATE_CACHE[template_id] = template
        TEMPLATE_CACHE_TS = time.time()
    return template


def refill_problem_pool(template_id, count):
    """生成题目并补充到池中"""
    created = 0
    for _ in range(count):
        problem_data = generate_problem_from_template(template_id)
        if problem_data:
            redis_client.lpush(get_pool_key(template_id), json.dumps(problem_data))
            created += 1
    return created


def ensure_problem_pool(template_id):
    """低水位补货（小批量）"""
    current_size = redis_client.llen(get_pool_key(template_id))
    if current_size < POOL_LOW_WATER:
        refill_problem_pool(template_id, POOL_REFILL_BATCH)


def fetch_problem_from_pool(template_id):
    """从池中获取题目，如果不足则补充"""
    ensure_problem_pool(template_id)
    raw_problem = redis_client.rpop(get_pool_key(template_id))

    if not raw_problem:
        problem_data = generate_problem_from_template(template_id)
        if not problem_data:
            return None, None
        token = uuid.uuid4().hex
        cache_problem_with_token(token, problem_data)
        return token, problem_data

    if not raw_problem:
        return None, None

    try:
        problem_data = json.loads(raw_problem)
    except json.JSONDecodeError:
        return None, None

    token = uuid.uuid4().hex
    cache_problem_with_token(token, problem_data)
    return token, problem_data


def generate_and_cache_problem(template_id):
    """直接生成题目并写入Redis，作为池为空时的兜底"""
    problem_data = generate_problem_from_template(template_id)
    if not problem_data:
        return None, None
    token = uuid.uuid4().hex
    cache_problem_with_token(token, problem_data)
    return token, problem_data


def prewarm_pools():
    print("[PREWARM] 开始预热题目池")
    conn = get_db_connection()
    if not conn:
        print("[PREWARM] 数据库连接失败，跳过预热")
        return

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM problem_templates")
    template_ids = [row['id'] for row in cursor.fetchall()]
    cursor.close()
    conn.close()

    for template_id in template_ids:
        pool_size = redis_client.llen(get_pool_key(template_id))
        if pool_size < POOL_TARGET:
            to_add = POOL_TARGET - pool_size
            print(f"[PREWARM] 模板 {template_id} 补货 {to_add} 道")
            refill_problem_pool(template_id, to_add)
        else:
            print(f"[PREWARM] 模板 {template_id} 池已满足，当前 {pool_size}")
    print("[PREWARM] 预热完成")


# 登录装饰器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录！', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


def is_correct(user_answer, correct_answer):
    """判断答案是否正确（允许1%误差，支持科学计数法范围）"""
    print(f"[DEBUG is_correct] 用户答案: {user_answer}, 正确答案: {correct_answer}")
    print(f"[DEBUG is_correct] 类型 - 用户答案: {type(user_answer)}, 正确答案: {type(correct_answer)}")

    # 处理None值
    if user_answer is None or correct_answer is None:
        print(f"[DEBUG is_correct] 答案为空，返回False")
        return False

    # 转换为浮点数
    try:
        user_float = float(user_answer)
        correct_float = float(correct_answer)
    except (ValueError, TypeError) as e:
        print(f"[DEBUG is_correct] 数值转换失败: {e}")
        return False

    print(f"[DEBUG is_correct] 转换后 - 用户答案: {user_float}, 正确答案: {correct_float}")

    # 处理特殊情况：两个都是0
    if user_float == 0 and correct_float == 0:
        print(f"[DEBUG is_correct] 两者均为0，返回True")
        return True

    # 处理特殊情况：其中一个为0，另一个不为0
    if user_float == 0 or correct_float == 0:
        # 如果其中一个为0，则要求完全相等（因为0的1%还是0）
        result = user_float == correct_float
        print(f"[DEBUG is_correct] 有0值，直接比较结果: {result}")
        return result

    # 计算相对误差（百分比）
    relative_error = abs((user_float - correct_float) / correct_float) * 100

    # 动态误差阈值（根据数量级调整）
    base_tolerance = 1.0  # 基础1%误差

    # 对于非常大或非常小的数，稍微放宽误差限制
    magnitude = math.log10(abs(correct_float))
    if magnitude > 10:  # 大于10^10
        adjusted_tolerance = min(base_tolerance * 1.5, 2.0)
    elif magnitude < -10:  # 小于10^-10
        adjusted_tolerance = min(base_tolerance * 1.5, 2.0)
    else:
        adjusted_tolerance = base_tolerance

    # 检查相对误差
    result = relative_error <= adjusted_tolerance

    print(f"[DEBUG is_correct] 相对误差: {relative_error:.6f}%")
    print(f"[DEBUG is_correct] 允许误差: {adjusted_tolerance}%")
    print(f"[DEBUG is_correct] 是否在容错范围内: {result}")

    # 调试信息：显示科学计数法格式
    print(f"[DEBUG is_correct] 科学计数法 - 用户答案: {user_float:.2e}, 正确答案: {correct_float:.2e}")

    return result


# 新增辅助函数：科学计数法格式化
def format_scientific(value, precision=2):
    """将数值格式化为科学计数法字符串"""
    if value == 0:
        return "0.00 × 10⁰"

    is_negative = value < 0
    abs_value = abs(value)

    # 计算指数
    exponent = math.floor(math.log10(abs_value))
    mantissa = abs_value / (10 ** exponent)

    # 调整到标准形式 (1 ≤ mantissa < 10)
    if mantissa >= 10:
        mantissa /= 10
        exponent += 1
    elif mantissa < 1:
        mantissa *= 10
        exponent -= 1

    # 格式化
    sign = '-' if is_negative else ''
    mantissa_str = f"{mantissa:.{precision}f}"

    # 获取上标数字
    superscript_digits = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
        '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹'
    }

    exp_str = str(exponent)
    sup_exp = ''
    if exp_str[0] == '-':
        sup_exp += '⁻'
        exp_str = exp_str[1:]
    for digit in exp_str:
        sup_exp += superscript_digits.get(digit, digit)

    return f"{sign}{mantissa_str} × 10{sup_exp}"


# 新增函数：用于生成正确答案的科学计数法提示
def get_scientific_hint(correct_answers):
    """生成科学计数法格式的正确答案提示"""
    if not correct_answers or not isinstance(correct_answers, list):
        return "正确答案: 暂无"

    formatted_answers = []
    for answer in correct_answers:
        try:
            formatted = format_scientific(float(answer))
            formatted_answers.append(formatted)
        except:
            formatted_answers.append(str(answer))

    if len(formatted_answers) == 1:
        return f"正确答案: {formatted_answers[0]}"
    else:
        parts = []
        for i, answer in enumerate(formatted_answers):
            parts.append(f"答案{i + 1} = {answer}")
        return f"正确答案: {', '.join(parts)}"


def get_problem_display_info():
    """获取题目的显示信息（处理删除后的序号不连续问题）"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 获取所有有效的题目模板，按ID排序
    cursor.execute("SELECT id, template_name FROM problem_templates ORDER BY id")
    templates = cursor.fetchall()

    # 创建显示序号映射
    display_mapping = {}
    for display_number, template in enumerate(templates, 1):
        display_mapping[template['id']] = {
            'display_number': display_number,
            'template_name': template['template_name'],
            'actual_id': template['id']
        }

    cursor.close()
    conn.close()
    return display_mapping


def build_display_to_actual_map():
    """生成显示序号到实际ID的映射，便于前端查找"""
    mapping = get_problem_display_info()
    display_to_actual = {}

    for actual_id, info in mapping.items():
        display_number = info['display_number']
        display_to_actual[display_number] = actual_id

    return display_to_actual


def get_display_number(actual_id):
    """根据实际ID获取显示序号"""
    mapping = get_problem_display_info()
    if actual_id in mapping:
        return mapping[actual_id]['display_number']
    return actual_id  # 回退到实际ID


def get_actual_id(display_number):
    """根据显示序号获取实际ID"""
    mapping = get_problem_display_info()
    for actual_id, info in mapping.items():
        if info['display_number'] == display_number:
            return actual_id
    return None  # 找不到对应的实际ID


def has_full_correct_attempt(cursor, user_id, template_id):
    """判断是否存在所有答案均正确的作答记录"""
    cursor.execute("""
        SELECT attempt_count
        FROM user_responses
        WHERE user_id = %s AND template_id = %s
        GROUP BY attempt_count
        HAVING SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) = COUNT(*)
        LIMIT 1
    """, (user_id, template_id))
    return cursor.fetchone() is not None


def get_latest_full_correct_attempt(cursor, user_id, template_id):
    """获取最近一次所有答案均正确的作答统计"""
    cursor.execute("""
        SELECT attempt_count
        FROM user_responses
        WHERE user_id = %s AND template_id = %s
        GROUP BY attempt_count
        HAVING SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) = COUNT(*)
        ORDER BY attempt_count DESC
        LIMIT 1
    """, (user_id, template_id))
    attempt_row = cursor.fetchone()

    if not attempt_row:
        return None

    attempt_count = attempt_row['attempt_count']
    cursor.execute("""
        SELECT time_taken, attempt_count,
               CASE WHEN is_correct THEN 100 ELSE 0 END as score
        FROM user_responses
        WHERE user_id = %s AND template_id = %s AND attempt_count = %s
        LIMIT 1
    """, (user_id, template_id, attempt_count))
    return cursor.fetchone()


def is_problem_completed(user_id, template_id):
    """检查指定题目是否已被用户正确完成"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        return has_full_correct_attempt(cursor, user_id, template_id)
    finally:
        cursor.close()
        conn.close()


def get_total_problem_count():
    """动态获取题目总数"""
    mapping = get_problem_display_info()
    return len(mapping)


def generate_problem_from_template(template_id, max_attempts=10):
    """从模板生成具体问题 - 完全动态的合理性验证（无学习表），包含答案单位处理"""
    template = get_template(template_id)

    if not template:
        return None

    variables = [v.strip() for v in template['variables'].split(',')] if template['variables'] else []

    # 符号定义
    x, t, h = sp.symbols('x t h')
    local_vars = {
        'x': x, 't': t, 'h': h, 'sp': sp, 'sqrt': sp.sqrt, 'exp': sp.exp,
        'integrate': sp.integrate, 'pi': pi, 'log': log, 'sin': sp.sin, 'cos': sp.cos
    }

    # 内存中的自适应范围（不持久化）
    reasonable_ranges = {}
    for var in variables:
        reasonable_ranges[var] = get_adaptive_default_range(var)

    for attempt in range(max_attempts):
        var_values = {}

        # 使用自适应范围生成变量
        for var in variables:
            min_val, max_val = reasonable_ranges[var]
            # 随着尝试次数增加，逐渐扩大搜索范围
            range_expansion = 1.0 + (attempt * 0.1)  # 每次尝试扩大10%
            expanded_min = max(0.01, min_val / range_expansion)
            expanded_max = max_val * range_expansion

            var_values[var] = round(random.uniform(expanded_min, expanded_max), 2)

        # 格式化问题文本
        problem_content = format_problem_text(template['problem_text'], var_values)

        # 计算答案
        try:
            current_vars = local_vars.copy()
            current_vars.update(var_values)

            correct_answer = eval(template['solution_formula'], {}, current_vars)

            if isinstance(correct_answer, tuple):
                correct_answers = [float(a.evalf()) if hasattr(a, 'evalf') else float(a) for a in correct_answer]
            else:
                correct_answers = [
                    float(correct_answer.evalf()) if hasattr(correct_answer, 'evalf') else float(correct_answer)]

            answer_count = template.get('answer_count', 1)
            if len(correct_answers) != answer_count:
                correct_answers = [correct_answers[0]] * answer_count

            # 动态合理性验证（标准随尝试次数放宽）
            if is_answer_reasonable_dynamic(correct_answers, var_values, attempt):
                # 在内存中更新合理范围（仅本次运行有效）
                for var, value in var_values.items():
                    current_min, current_max = reasonable_ranges[var]
                    reasonable_ranges[var] = (
                        min(current_min, value * 0.8),  # 稍微扩大下限
                        max(current_max, value * 1.2)  # 稍微扩大上限
                    )

                # 解析答案单位
                answer_units = []
                if template.get('answer_units'):
                    answer_units = [u.strip() for u in template['answer_units'].split(',')]

                # 确保答案单位数量与答案数量匹配
                answer_count = template.get('answer_count', 1)
                if len(answer_units) < answer_count:
                    # 如果单位数量不足，用空字符串补齐
                    answer_units.extend([''] * (answer_count - len(answer_units)))
                elif len(answer_units) > answer_count:
                    # 如果单位数量过多，只取前answer_count个
                    answer_units = answer_units[:answer_count]

                # 格式化显示答案（保留适当小数位数）
                formatted_correct_answers = []
                for i, answer in enumerate(correct_answers):
                    # 根据答案大小选择合适的小数位数
                    abs_answer = abs(answer)
                    if abs_answer == 0:
                        formatted_correct_answers.append(0.0)
                    elif abs_answer >= 1000:
                        formatted_correct_answers.append(round(answer, 0))
                    elif abs_answer >= 1:
                        formatted_correct_answers.append(round(answer, 2))
                    elif abs_answer >= 0.01:
                        formatted_correct_answers.append(round(answer, 4))
                    else:
                        formatted_correct_answers.append(round(answer, 6))

                # 构建最终返回数据，包含答案单位
                result_data = {
                    'problem_text': problem_content,
                    'var_values': var_values,
                    'correct_answers': formatted_correct_answers,  # 使用格式化后的答案
                    'answer_units': answer_units,  # 添加答案单位
                    'template_id': template_id,
                    'answer_count': template.get('answer_count', 1),
                    'template_name': template['template_name'],
                    'image_filename': template.get('image_filename')
                }

                # 调试信息
                print(f"✅ 题目生成成功 - 模板: {template['template_name']}")
                print(f"   变量值: {var_values}")
                print(f"   正确答案: {formatted_correct_answers}")
                print(f"   答案单位: {answer_units}")
                print(f"   答案数量: {answer_count}")

                return result_data

        except Exception as e:
            # 计算失败，继续尝试
            print(f"⚠️ 题目生成尝试 {attempt + 1} 失败: {str(e)}")
            continue

    # 最终回退：使用保守但保证成功的方法
    return generate_fallback_problem(template, variables, local_vars)


def generate_fallback_problem(template, variables, local_vars):
    """最终回退方案：使用保守范围生成题目"""
    var_values = {}
    for var in variables:
        # 使用非常保守但保证合理的小范围
        var_values[var] = round(random.uniform(1.0, 3.0), 2)

    problem_content = format_problem_text(template['problem_text'], var_values)

    try:
        current_vars = local_vars.copy()
        current_vars.update(var_values)
        correct_answer = eval(template['solution_formula'], {}, current_vars)

        if isinstance(correct_answer, tuple):
            correct_answers = [float(a.evalf()) if hasattr(a, 'evalf') else float(a) for a in correct_answer]
        else:
            correct_answers = [
                float(correct_answer.evalf()) if hasattr(correct_answer, 'evalf') else float(correct_answer)]

        answer_count = template.get('answer_count', 1)
        if len(correct_answers) != answer_count:
            correct_answers = [correct_answers[0]] * answer_count
    except:
        correct_answers = [0.0] * template.get('answer_count', 1)

    # 解析答案单位（回退方案也处理单位）
    answer_units = []
    if template.get('answer_units'):
        answer_units = [u.strip() for u in template['answer_units'].split(',')]

    # 确保答案单位数量与答案数量匹配
    answer_count = template.get('answer_count', 1)
    if len(answer_units) < answer_count:
        answer_units.extend([''] * (answer_count - len(answer_units)))
    elif len(answer_units) > answer_count:
        answer_units = answer_units[:answer_count]

    # 格式化答案
    formatted_correct_answers = []
    for answer in correct_answers:
        abs_answer = abs(answer)
        if abs_answer >= 1000:
            formatted_correct_answers.append(round(answer, 0))
        elif abs_answer >= 1:
            formatted_correct_answers.append(round(answer, 2))
        else:
            formatted_correct_answers.append(round(answer, 4))

    result_data = {
        'problem_text': problem_content,
        'var_values': var_values,
        'correct_answers': formatted_correct_answers,
        'answer_units': answer_units,  # 包含答案单位
        'template_id': template['id'],
        'answer_count': template.get('answer_count', 1),
        'template_name': template['template_name'],
        'image_filename': template.get('image_filename')
    }

    print(f"⚠️ 使用回退方案生成题目 - 模板: {template['template_name']}")
    print(f"   变量值: {var_values}")
    print(f"   正确答案: {formatted_correct_answers}")
    print(f"   答案单位: {answer_units}")

    return result_data

def get_adaptive_default_range(var_name):
    """根据变量名特征自适应设置默认范围"""
    var_lower = var_name.lower()

    # 基于命名模式的智能猜测
    if any(char in var_lower for char in ['r', 'a', 'l', 'd', 'x', 'h']):  # 几何尺寸类
        return (0.1, 10.0)
    elif any(char in var_lower for char in ['v', 'u', 'w', 'speed', 'velocity']):  # 速度类
        return (1.0, 50.0)
    elif any(char in var_lower for char in ['b', 'e', 'f', 'field']):  # 场强类
        return (0.1, 5.0)
    elif any(char in var_lower for char in ['i', 'current']):  # 电流类
        return (0.1, 10.0)
    elif any(char in var_lower for char in ['r', 'resistance']):  # 电阻类
        return (1.0, 100.0)
    elif any(char in var_lower for char in ['m', 'mass']):  # 质量类
        return (0.01, 5.0)
    elif any(char in var_lower for char in ['omega', 'ω', 'angular']):  # 角速度
        return (1.0, 20.0)
    elif any(char in var_lower for char in ['dbdt', 'alpha', 'rate']):  # 变化率
        return (0.1, 10.0)
    elif any(char in var_lower for char in ['density']):  # 密度
        return (1000.0, 10000.0)
    else:
        # 通用范围
        return (0.5, 20.0)


def is_answer_reasonable_dynamic(correct_answers, var_values, attempt_num):
    """完全动态的合理性验证"""
    if not correct_answers:
        return False

    for answer in correct_answers:
        # 基础检查：必须是有限实数
        if not isinstance(answer, (int, float)) or not np.isfinite(answer):
            return False

        abs_answer = abs(answer)

        # 动态阈值：随着尝试次数增加，逐渐放宽标准
        max_threshold = 1e6 * (1 + attempt_num * 0.2)  # 逐渐放宽上限
        min_threshold = 1e-8 / (1 + attempt_num * 0.2)  # 逐渐放宽下限

        if abs_answer > max_threshold or (0 < abs_answer < min_threshold):
            return False

        # 检查与输入变量的协调性（标准也动态放宽）
        if not check_dynamic_consistency(answer, var_values, attempt_num):
            return False

    return True


def check_dynamic_consistency(answer, var_values, attempt_num):
    """动态检查答案与变量的协调性"""
    if not var_values:
        return True

    abs_answer = abs(answer)
    var_values_list = [abs(v) for v in var_values.values() if isinstance(v, (int, float))]

    if not var_values_list:
        return True

    avg_var = sum(var_values_list) / len(var_values_list)

    # 动态比率阈值：随着尝试次数放宽
    base_max_ratio = 1000
    base_min_ratio = 0.001
    relaxation_factor = 1 + (attempt_num * 0.3)  # 每次尝试放宽30%

    max_ratio = base_max_ratio * relaxation_factor
    min_ratio = base_min_ratio / relaxation_factor

    ratio_to_avg = abs_answer / avg_var if avg_var > 0 else abs_answer

    # 检查是否在合理比率范围内
    if ratio_to_avg > max_ratio or ratio_to_avg < min_ratio:
        return False

    return True


def format_problem_text(problem_text, var_values):
    """格式化问题文本"""
    import re
    pattern = r'__(\w+)__'

    def replace_var(match):
        var_name = match.group(1)
        return str(var_values.get(var_name, match.group(0)))

    return re.sub(pattern, replace_var, problem_text)


def classify_error_type(user_answer, correct_answer, is_correct):
    """根据用户答案与正确答案的差异推断错误类型"""
    if is_correct:
        return '正确'

    if user_answer is None:
        return '未作答'

    try:
        user_float = float(user_answer)
        correct_float = float(correct_answer)
    except (TypeError, ValueError):
        return '格式错误'

    if correct_float == 0:
        return '计算错误' if user_float != 0 else '正确'

    relative_error = abs((user_float - correct_float) / correct_float) * 100

    if relative_error > 50:
        return '概念错误'
    if relative_error > 5:
        return '计算误差'
    return '精度或单位偏差'


def save_user_response(user_id, template_id, problem_text, user_answers, correct_answers, is_correct_list,
                       attempt_count, time_taken, error_types=None):
    """保存用户答题记录（支持多答案）"""
    print(f"\n=== 保存答题记录开始 ===")
    print(f"用户ID: {user_id}")
    print(f"模板ID: {template_id}")
    print(f"用户答案: {user_answers}")
    print(f"正确答案: {correct_answers}")
    print(f"是否正确: {is_correct_list}")
    print(f"尝试次数: {attempt_count}")
    print(f"用时: {time_taken}秒")
    print(f"答案数量: {len(user_answers)}")

    conn = None
    try:
        # 1. 获取数据库连接
        conn = get_db_connection()
        if not conn:
            print("❌ 数据库连接失败")
            return False

        cursor = conn.cursor()
        print("✅ 数据库连接成功")

        # 2. 验证用户和模板是否存在
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        user_exists = cursor.fetchone()
        if not user_exists:
            print(f"❌ 用户ID {user_id} 不存在")
            return False
        print("✅ 用户存在")

        cursor.execute("SELECT id FROM problem_templates WHERE id = %s", (template_id,))
        template_exists = cursor.fetchone()
        if not template_exists:
            print(f"❌ 模板ID {template_id} 不存在")
            return False
        print("✅ 模板存在")

        # 3. 截断过长的problem_text
        truncated_problem_text = problem_text[:1000] + "..." if len(problem_text) > 1000 else problem_text
        print(f"✅ 问题文本已截断: {len(truncated_problem_text)} 字符")

        # 4. 保存每个答案的记录
        all_success = True
        saved_count = 0

        if error_types is None:
            error_types = [
                classify_error_type(user_answer, correct_answer, is_correct)
                for user_answer, correct_answer, is_correct in zip(user_answers, correct_answers, is_correct_list)
            ]

        for i, (user_answer, correct_answer, is_correct, error_type) in enumerate(
                zip(user_answers, correct_answers, is_correct_list, error_types)):
            try:
                print(
                    f"正在保存答案 {i + 1}: user_answer={user_answer}, correct_answer={correct_answer}, is_correct={is_correct}, error_type={error_type}")

                cursor.execute("""
                    INSERT INTO user_responses
                    (user_id, template_id, problem_text, user_answer,
                     correct_answer, is_correct, error_type, attempt_count, time_taken, answer_index)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (user_id, template_id, truncated_problem_text, user_answer,
                      correct_answer, is_correct, error_type, attempt_count, time_taken, i))

                saved_count += 1
                print(f"✅ 答案 {i + 1} 保存成功")

            except mysql.connector.Error as err:
                print(f"❌ 答案 {i + 1} 保存失败: {err}")
                all_success = False
                break
            except Exception as e:
                print(f"❌ 答案 {i + 1} 保存异常: {str(e)}")
                all_success = False
                break

        # 5. 提交事务
        if all_success:
            conn.commit()
            print(f"✅ 事务提交成功，共保存 {saved_count} 个答案记录")
        else:
            conn.rollback()
            print("❌ 部分答案保存失败，事务已回滚")

        return all_success

    except mysql.connector.Error as err:
        print(f"❌ 数据库错误: {err}")
        print(f"错误代码: {err.errno}")
        print(f"SQL状态: {err.sqlstate}")
        if conn:
            conn.rollback()
        return False

    except Exception as e:
        print(f"❌ 保存过程中发生异常: {str(e)}")
        import traceback
        print(f"详细错误信息:\n{traceback.format_exc()}")
        if conn:
            conn.rollback()
        return False

    finally:
        if conn and conn.is_connected():
            conn.close()
            print("✅ 数据库连接已关闭")
        print("=== 保存答题记录结束 ===\n")


def repair_database():
    """修复数据库表结构"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 检查并添加缺失的列
        cursor.execute("SHOW COLUMNS FROM user_responses LIKE 'user_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE user_responses ADD COLUMN user_id INT NOT NULL AFTER id")
            print("已添加 user_id 列")

        cursor.execute("SHOW COLUMNS FROM user_responses LIKE 'template_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE user_responses ADD COLUMN template_id INT NOT NULL AFTER user_id")
            print("已添加 template_id 列")

        cursor.execute("SHOW COLUMNS FROM user_responses LIKE 'error_type'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE user_responses ADD COLUMN error_type VARCHAR(50) DEFAULT '未知' AFTER is_correct")
            cursor.execute("UPDATE user_responses SET error_type = '正确' WHERE is_correct = TRUE")
            cursor.execute("UPDATE user_responses SET error_type = '计算误差' WHERE is_correct = FALSE")
            print("已添加 error_type 列")

        # 添加外键约束（如果不存在）
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.table_constraints
            WHERE table_name = 'user_responses' 
            AND constraint_name = 'user_responses_ibfk_1'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                ALTER TABLE user_responses
                ADD FOREIGN KEY (user_id) REFERENCES users(id)
            """)
            print("已添加 user_id 外键约束")

        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.table_constraints
            WHERE table_name = 'user_responses' 
            AND constraint_name = 'user_responses_ibfk_2'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                ALTER TABLE user_responses
                ADD FOREIGN KEY (template_id) REFERENCES problem_templates(id)
            """)
            print("已添加 template_id 外键约束")

        conn.commit()
    except mysql.connector.Error as err:
        print(f"修复数据库失败: {err}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


def initialize_database():
    """初始化数据库 - 使用新的图片管理方式，包含答案单位字段"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 创建用户表（如果不存在）- 添加完成状态字段
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) NOT NULL UNIQUE,
        password VARCHAR(100) NOT NULL,
        completed_all BOOLEAN DEFAULT FALSE,
        completed_at TIMESTAMP NULL,
        total_score INT DEFAULT 0,
        total_time FLOAT DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 创建问题模板表（如果不存在）- 添加图片文件名字段和答案单位字段
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS problem_templates (
        id INT AUTO_INCREMENT PRIMARY KEY,
        template_name VARCHAR(100) NOT NULL,
        problem_text TEXT NOT NULL,
        variables TEXT NOT NULL,
        solution_formula TEXT NOT NULL,
        answer_count INT DEFAULT 1,
        answer_units TEXT,  -- 新增：答案单位字段
        difficulty VARCHAR(20) DEFAULT 'medium',
        image_filename VARCHAR(255) NULL
    )
    """)

    # 创建用户答题记录表（确保包含所有必要字段）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_responses (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        template_id INT NOT NULL,
        problem_text TEXT NOT NULL,
        user_answer FLOAT NOT NULL,
        correct_answer FLOAT NOT NULL,
        is_correct BOOLEAN NOT NULL,
        error_type VARCHAR(50) DEFAULT '未知',
        attempt_count INT NOT NULL,
        time_taken FLOAT NOT NULL,
        response_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        answer_index INT DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (template_id) REFERENCES problem_templates(id)
    )
    """)

    # 创建防伪记录表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS verification_records (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        verification_code VARCHAR(20) NOT NULL UNIQUE,
        verification_data JSON NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    # 插入电磁学题目模板 - 包含答案单位信息
    templates = [
        # 题目1：闭合圆形线圈的感应电流（无图片）
        {
            'name': '闭合圆形线圈的感应电流',
            'text': r"""
                <div class="math-formula">
                    <h5>题目描述：</h5>
                    <p>用导线制成一半径为 \( r = __r__ \, \text{cm} \) 的闭合圆形线圈，其电阻 \( R = __R__ \, \Omega \)，均匀磁场垂直于线圈平面。</p>
                    <p>欲使电路中有一稳定的感应电流 \( i = __i__ \, \text{A} \)，求 \( B \) 的变化率 \( \frac{dB}{dt} \)。</p>
                    <div class="problem-hint-static">
                        <h5>解题提示：</h5>
                        <p>法拉第电磁感应定律：\( \varepsilon = -\frac{d\Phi}{dt} \)</p>
                        <p>磁通量：\( \Phi = B \cdot S = B \cdot \pi r^2 \)</p>
                        <p>感应电流：\( i = \frac{\varepsilon}{R} \)</p>
                    </div>
                </div>
            """,
            'variables': 'r,R,i',
            'formula': "i * R / (pi * (r/100)**2)",
            'answer_count': 1,
            'answer_units': 'T/s',  # 磁感应强度变化率，单位：特斯拉/秒
            'image_filename': None
        },

        # 题目2：高铁电磁感应问题（无图片）
        {
            'name': '高铁电磁感应问题',
            'text': r"""
            <div class="math-formula">
            <h5>题目描述：</h5>
            <p>中国是目前世界上高速铁路运行里程最长的国家，已知"复兴号"高铁长度为 L = __L__ m，车厢高 h = __h__ m，正常行驶速度 v = __v__ km/h。</p>
            <p>假设地面附近地磁场的水平分量约为 B = __B__ μT，将列车视为一整块导体，只考虑地磁场的水平分量。</p>
            <p>则"复兴号"列车在自西向东正常行驶的过程中，求车顶与车底之间的电势差大小。</p>
            <div class="problem-hint-static">
                        <h5>解题提示：</h5>
                <p>1. 速度单位换算：km/h → m/s</p>
                <p>2. 磁场单位换算：μT → T</p>
                <p>3. 导体在磁场中运动产生的感应电动势：ε = BLv</p>
                <p>4. 最终结果单位转换为微伏(μV)：1 V = 10⁶ μV</p>
            </div>
            </div>
            """,
            'variables': 'L,h,v,B',
            'formula': "B * L * (v / 3.6)",
            'answer_count': 1,
            'answer_units': 'μV',  # 电势差，单位：微伏
            'image_filename': None
        },

        # 题目3：等边三角形金属框转动电动势（有图片）
        {
            'name': '等边三角形金属框转动电动势',
            'text': r"""
                <div class="math-formula">
                    <h5>题目描述：</h5>
                    <p>如图所示，等边三角形的金属框，边长为 \( l = __l__ \, \text{m} \)，放在均匀磁场 \( B = __B__ \, \text{T} \) 中。</p>
                    <p>\( ab \) 边平行于磁感强度 \( B \)，当金属框绕 \( ab \) 边以角速度 \( \omega = __omega__ \, \text{rad/s} \) 转动时：</p>
                    <ol>
                        <li>求 \( bc \) 边上沿 \( bc \) 的电动势</li>
                        <li>求 \( ca \) 边上沿 \( ca \) 的电动势</li>
                        <li>求金属框内的总电动势</li>
                    </ol>
                    <div class="problem-hint-static">
                        <h5>解题提示：</h5>
                        <p>动生电动势：\( \varepsilon = \int (\vec{v} \times \vec{B}) \cdot d\vec{l} \)</p>
                        <p>考虑各边的运动情况和磁场方向</p>
                    </div>
                </div>
            """,
            'variables': 'l,B,omega',
            'formula': "(3/8) * B * omega * l**2, -(3/8) * B * omega * l**2,0",
            'answer_count': 3,
            'answer_units': 'V,V,V',  # 三个电动势，单位都是伏特
            'image_filename': 'problem3.png'
        },

        # 题目4：动生电动势与感生电动势（有图片）
        {
            'name': '动生电动势与感生电动势',
            'text': r"""
                <div class="math-formula">
                    <h5>题目描述：</h5>
                    <p>导体 \( AC \) 以速度 \( v = __v__ \, \text{m/s} \) 运动。</p>
                    <p>设 \( AC = __AC__ \, \text{cm} \)，均匀磁场随时间的变化率 \( \frac{dB}{dt} = __dBdt__ \, \text{T/s} \)。</p>
                    <p>某一时刻 \( B = __B__ \, \text{T} \)，\( x = __x__ \, \text{cm} \)，求：</p>
                    <ol>
                        <li>这时动生电动势的大小</li>
                        <li>总感应电动势的大小</li>
                        <li>动生电动势随 \( AC \) 运动的变化趋势（增大填1，减小填-1）</li>
                    </ol>
                    <div class="problem-hint-static">
                        <h5>解题提示：</h5>
                        <p>动生电动势：导体切割磁感线产生</p>
                        <p>感生电动势：磁场变化产生</p>
                        <p>总电动势为两者之和</p>
                    </div>
                </div>
            """,
            'variables': 'v,AC,dBdt,B,x',
            'formula': "B * v * (AC/100), (B * v * (AC/100)) + (dBdt * (x/100) * (AC/100)), 1",
            'answer_count': 3,
            'answer_units': 'V,V,-',  # 前两个是伏特，第三个是无量纲
            'image_filename': 'problem4.png'
        },

        # 题目5：折形金属导线运动电势差（有图片）
        {
            'name': '折形金属导线运动电势差',
            'text': r"""
                <div class="math-formula">
                    <h5>题目描述：</h5>
                    <p>\( aOc \) 为一折成 \( 30^\circ \) 角的金属导线（\( aO = Oc = L = __L__ \, \text{m} \)），位于 \( xy \) 平面中。</p>
                    <p>其中 \( aO \) 段与 \( x \) 轴夹角为 \( 30^\circ \)，\( Oc \) 段与 \( x \) 轴夹角为 \( 30^\circ \)，两段在 \( O \) 点相接。</p>
                    <p>磁感强度为 \( B = __B__ \, \text{T} \) 的匀强磁场垂直于 \( xy \) 平面。</p>
                    <ol>
                        <li>当 \( aOc \) 以速度 \( v = __v__ \, \text{m/s} \) 沿 \( x \) 轴正向运动时，导线上 \( a, c \) 两点间电势差 \( U_{ac} \)</li>
                        <li>当 \( aOc \) 以速度 \( v \) 沿 \( y \) 轴正向运动时，判断 \( a, c \) 两点电势高低（a点高填1，c点高填-1）</li>
                    </ol>
                    <div class="problem-hint-static">
                        <h5>解题提示：</h5>
                        <p>动生电动势公式：\( \varepsilon = \int (\vec{v} \times \vec{B}) \cdot d\vec{l} \)</p>
                        <p>考虑不同运动方向时各段的电动势，注意30度角的影响</p>
                        <p>总电势差为各段电动势的代数和</p>
                    </div>
                </div>
            """,
            'variables': 'L,B,v',
            'formula': "B * v * L /2 , -1",
            'answer_count': 2,
            'answer_units': 'V,-',  # 第一个是伏特，第二个是无量纲
            'image_filename': 'problem5.png'
        },

        # 题目6：磁铁插入线圈的感应现象（无图片）
        {
            'name': '磁铁插入线圈的感应现象',
            'text': r"""
                <div class="math-formula">
                    <h5>题目描述：</h5>
                    <p>将磁铁插入闭合电路线圈，一次是迅速地插入，另一次是缓慢地插入。</p>
                    <ol>
                        <li>两次插入过程中，线圈中感应电荷量是否相同？（相同填1，不同填0）</li>
                        <li>两次插入过程中，手推磁铁所做的功是否相同？（相同填1，不同填0）</li>
                    </ol>
                    <div class="problem-hint-static">
                        <h5>解题提示：</h5>
                        <p>感应电荷量：\( q = \frac{\Delta\Phi}{R} \)</p>
                        <p>做功与功率和时间有关</p>
                    </div>
                </div>
            """,
            'variables': '',
            'formula': "1, 0",
            'answer_count': 2,
            'answer_units': '-,-',  # 两个都是无量纲
            'image_filename': None
        },

        # 题目7：双圆线圈的感应电流（有图片）
        {
            'name': '双圆线圈的感应电流',
            'text': r"""
                <div class="math-formula">
                    <h5>题目描述：</h5>
                    <p>电阻为 \( R = __R__ \, \Omega \) 的闭合线圈折成半径分别为 \( a = __a__ \, \text{cm} \) 和 \( 2a \) 的两个圆，</p>
                    <p>将其置于与两圆平面垂直的匀强磁场内，磁感应强度按 \( B = B_0 \sin(\omega t) \) 的规律变化。</p>
                    <p>已知 \( B_0 = __B0__ \, \text{T} \)，\( \omega = __omega__ \, \text{rad/s} \)，求线圈中感应电流的最大值。</p>
                    <div class="problem-hint-static">
                        <h5>解题提示：</h5>
                        <p>法拉第电磁感应定律</p>
                        <p>总电动势为两个线圈电动势之和</p>
                        <p>感应电流最大值</p>
                    </div>
                </div>
            """,
            'variables': 'R,a,B0,omega',
            'formula': "(pi * omega * B0 / R) * ((a/100)**2 + (2*a/100)**2)",
            'answer_count': 1,
            'answer_units': 'A',  # 电流，单位：安培
            'image_filename': 'problem7.png'
        },
    ]

    # 插入模板到数据库 - 包含答案单位信息
    for template in templates:
        cursor.execute("SELECT id FROM problem_templates WHERE template_name = %s", (template['name'],))
        if not cursor.fetchone():
            # 如果有图片文件名，在problem_text中插入图片HTML
            problem_text = template['text']
            if template.get('image_filename'):
                img_html = f'''
                <div class="text-center mb-3">
                    <img src="/static/images/{template['image_filename']}" 
                         alt="{template['name']}" class="problem-image img-fluid">
                    <div class="image-caption text-muted">图：{template['name']}</div>
                </div>
                '''
                problem_text = img_html + problem_text

            # 插入包含答案单位的数据
            cursor.execute("""
                INSERT INTO problem_templates 
                (template_name, problem_text, variables, solution_formula, 
                 answer_count, answer_units, image_filename)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                template['name'],
                problem_text,
                template['variables'],
                template['formula'],
                template['answer_count'],
                template.get('answer_units', ''),
                template.get('image_filename')
            ))
            print(f"✅ 插入题目: {template['name']}, 答案单位: {template.get('answer_units', '无')}")

    conn.commit()
    cursor.close()
    conn.close()

    print("✅ 数据库初始化完成，所有题目已添加答案单位")


def create_admin_user():
    """创建管理员用户"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 检查管理员用户是否已存在
        cursor.execute("SELECT id FROM users WHERE username = 'admin'")
        if not cursor.fetchone():
            # 创建管理员用户
            cursor.execute("INSERT INTO users (username, password) VALUES ('admin', 'admin123')")
            conn.commit()
            print("管理员用户创建成功: admin / admin123")
        else:
            print("管理员用户已存在")
    except Exception as e:
        print(f"创建管理员用户失败: {e}")
    finally:
        cursor.close()
        conn.close()


def ensure_default_images():
    """确保默认图片文件存在"""
    import os

    default_images = {
        'problem3.png': '等边三角形金属框示意图',
        'problem4.png': '导体AC运动示意图',
        'problem5.png': '折形金属导线示意图',
        'problem7.png': '双圆线圈示意图'
    }

    images_path = os.path.join(app.root_path, 'static', 'images')
    os.makedirs(images_path, exist_ok=True)

    # 检查默认图片是否存在
    for filename, description in default_images.items():
        file_path = os.path.join(images_path, filename)
        if not os.path.exists(file_path):
            print(f"⚠️ 注意: 默认图片缺失: {filename} - {description}")
            print(f"请将图片文件放置到: {file_path}")

    print("✅ 默认图片检查完成")


def verify_image_consistency():
    """验证图片一致性"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 检查所有有图片的题目
    cursor.execute("""
        SELECT id, template_name, image_filename 
        FROM problem_templates 
        WHERE image_filename IS NOT NULL
    """)

    templates_with_images = cursor.fetchall()

    print("=== 图片一致性检查 ===")
    missing_images = []
    for template in templates_with_images:
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], template['image_filename'])
        if os.path.exists(image_path):
            print(f"✅ 题目 '{template['template_name']}' 图片存在: {template['image_filename']}")
        else:
            print(f"❌ 题目 '{template['template_name']}' 图片缺失: {template['image_filename']}")
            missing_images.append({
                'template_name': template['template_name'],
                'image_filename': template['image_filename']
            })

    if missing_images:
        print(f"\n⚠️ 总计缺失 {len(missing_images)} 个图片文件:")
        for missing in missing_images:
            print(f"   - {missing['template_name']}: {missing['image_filename']}")

    cursor.close()
    conn.close()
    return len(missing_images) == 0


def update_user_completion_status(user_id):
    """更新用户完成状态 - 使用动态题目总数"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 动态获取题目总数
        total_problems = get_total_problem_count()

        # 检查是否完成所有题目
        cursor.execute("""
            SELECT COUNT(DISTINCT template_id) as completed_count
            FROM (
                SELECT template_id, attempt_count
                FROM user_responses
                WHERE user_id = %s
                GROUP BY template_id, attempt_count
                HAVING SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) = COUNT(*)
            ) as completed_attempts
        """, (user_id,))
        completed_count = cursor.fetchone()['completed_count']

        # 计算总分和总用时（仅统计完全正确的尝试）
        cursor.execute("""
            SELECT
                COUNT(*) as total_score,
                SUM(time_taken) as total_time
            FROM user_responses
            WHERE (user_id, template_id, attempt_count) IN (
                SELECT user_id, template_id, attempt_count
                FROM user_responses
                WHERE user_id = %s
                GROUP BY template_id, attempt_count
                HAVING SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) = COUNT(*)
            )
            AND is_correct = TRUE
        """, (user_id,))
        stats = cursor.fetchone()

        completed_all = completed_count >= total_problems  # 使用动态总数

        # 更新用户表
        if completed_all:
            cursor.execute("""
                UPDATE users 
                SET completed_all = TRUE,
                    completed_at = NOW(),
                    total_score = %s,
                    total_time = %s
                WHERE id = %s
            """, (stats['total_score'] or 0, stats['total_time'] or 0, user_id))
        else:
            cursor.execute("""
                UPDATE users 
                SET completed_all = FALSE,
                    total_score = %s,
                    total_time = %s
                WHERE id = %s
            """, (stats['total_score'] or 0, stats['total_time'] or 0, user_id))

        conn.commit()
        return completed_all

    except Exception as e:
        print(f"更新用户完成状态失败: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


def update_all_users_completion_status():
    """为所有用户刷新完成状态，返回更新数量"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT id FROM users")
        users = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    for user in users:
        update_user_completion_status(user['id'])

    return len(users)


def get_completion_stats():
    """获取完成情况统计"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 基础统计
    cursor.execute("""
        SELECT 
            COUNT(*) as total_students,
            SUM(completed_all) as completed_count,
            ROUND(SUM(completed_all) / COUNT(*) * 100, 1) as completion_rate,
            AVG(total_score) as avg_score,
            AVG(total_time) as avg_time
        FROM users
    """)
    stats = cursor.fetchone()

    # 今日完成情况
    cursor.execute("""
        SELECT COUNT(*) as today_completions
        FROM users 
        WHERE completed_all = TRUE 
        AND DATE(completed_at) = CURDATE()
    """)
    today_stats = cursor.fetchone()

    # 成绩排名
    cursor.execute("""
        SELECT username, total_score, total_time, completed_at
        FROM users 
        WHERE completed_all = TRUE 
        ORDER BY total_score DESC, total_time ASC
        LIMIT 10
    """)
    top_students = cursor.fetchall()

    cursor.close()
    conn.close()

    return {
        'stats': stats,
        'today_stats': today_stats,
        'top_students': top_students
    }


def get_students_by_completion(completed=True, limit=None, offset=0):
    """按完成状态获取学生列表"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT id, username, completed_at, total_score, total_time, created_at
        FROM users 
        WHERE completed_all = %s
        ORDER BY completed_at DESC, total_score DESC
    """
    params = [completed]

    if limit:
        query += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])

    cursor.execute(query, params)
    students = cursor.fetchall()
    cursor.close()
    conn.close()

    return students


def diagnose_database_issue():
    """诊断数据库问题"""
    print("\n=== 数据库诊断开始 ===")

    try:
        conn = get_db_connection()
        if not conn:
            print("❌ 数据库连接失败")
            return False

        cursor = conn.cursor(dictionary=True)

        # 检查表是否存在
        cursor.execute("SHOW TABLES LIKE 'user_responses'")
        if not cursor.fetchone():
            print("❌ user_responses 表不存在")
            return False

        # 检查表结构
        cursor.execute("DESCRIBE user_responses")
        columns = cursor.fetchall()
        print("✅ user_responses 表结构:")
        for col in columns:
            print(f"  - {col['Field']} ({col['Type']})")

        # 检查外键约束
        cursor.execute("""
            SELECT TABLE_NAME, COLUMN_NAME, CONSTRAINT_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_NAME = 'user_responses' AND REFERENCED_TABLE_NAME IS NOT NULL
        """)
        foreign_keys = cursor.fetchall()
        print("✅ 外键约束:")
        for fk in foreign_keys:
            print(f"  - {fk['COLUMN_NAME']} -> {fk['REFERENCED_TABLE_NAME']}.{fk['REFERENCED_COLUMN_NAME']}")

        cursor.close()
        conn.close()
        print("✅ 数据库诊断完成")
        return True

    except Exception as e:
        print(f"❌ 数据库诊断失败: {str(e)}")
        return False


# 用户认证路由
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, password))
            conn.commit()
            flash('注册成功！请登录。', 'success')
            return redirect(url_for('login'))
        except mysql.connector.Error as err:
            flash('用户名已存在！', 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, password))
        user = cursor.fetchone()

        cursor.close()
        conn.close()

        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('登录成功！', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('用户名或密码错误！', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('您已成功退出。', 'success')
    return redirect(url_for('login'))


# 主应用路由
@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('home.html')


@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 获取题目显示映射
        display_mapping = get_problem_display_info()
        total_problems = len(display_mapping)

        # 获取用户完成状态
        cursor.execute("""
            SELECT 
                completed_all,
                total_score as completed_count,
                total_time
            FROM users 
            WHERE id = %s
        """, (session['user_id'],))
        user_data = cursor.fetchone()

        if not user_data:
            flash('用户数据不存在', 'danger')
            return redirect(url_for('login'))

        completed_all = user_data['completed_all']
        completed_count = user_data['completed_count'] or 0

        # 动态确定当前应该做的题目（使用显示序号）
        current_display_number = 1
        if not completed_all:
            for display_info in display_mapping.values():
                actual_id = display_info['actual_id']
                cursor.execute("""
                    SELECT 1
                    FROM user_responses
                    WHERE user_id = %s AND template_id = %s
                    GROUP BY attempt_count
                    HAVING SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) = COUNT(*)
                    LIMIT 1
                """, (session['user_id'], actual_id))
                result = cursor.fetchone()
                if not result:
                    current_display_number = display_info['display_number']
                    break

        # 重置尝试次数
        session.pop('attempt_count', None)
        session.pop('current_problem', None)

        return render_template('dashboard.html',
                               username=session['username'],
                               current_problem=current_display_number,  # 使用显示序号
                               completed_count=completed_count,
                               completed_all=completed_all,
                               total_problems=total_problems,
                               display_mapping=display_mapping)  # 传递映射到模板

    except mysql.connector.Error as err:
        print(f"数据库查询错误: {err}")
        flash('数据库查询错误', 'danger')
        return redirect(url_for('home'))
    finally:
        cursor.close()
        conn.close()


@app.route('/stats')
@login_required
def statistics():
    """统计信息页面"""
    conn = None
    try:
        if 'user_id' not in session:
            flash('请先登录', 'warning')
            return redirect(url_for('login'))

        conn = get_db_connection()
        if not conn:
            flash('数据库连接失败', 'danger')
            return redirect(url_for('dashboard'))

        cursor = conn.cursor(dictionary=True)

        # 总体统计 - 添加错误处理
        cursor.execute("""
            WITH attempt_summary AS (
                SELECT
                    template_id,
                    attempt_count,
                    COUNT(*) AS total_answers,
                    SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS correct_answers,
                    MAX(time_taken) AS time_taken
                FROM user_responses
                WHERE user_id = %s
                GROUP BY template_id, attempt_count
            )
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN correct_answers = total_answers THEN 1 ELSE 0 END) AS correct_count,
                AVG(time_taken) AS avg_time
            FROM attempt_summary
        """, (session['user_id'],))

        stats_result = cursor.fetchone()

        # 处理空数据的情况
        if not stats_result or stats_result['total_count'] is None:
            stats = {
                'total_count': 0,
                'correct_count': 0,
                'avg_time': 0
            }
        else:
            # 转换Decimal类型为float
            stats = {
                'total_count': int(stats_result['total_count']),
                'correct_count': int(stats_result['correct_count'] or 0),
                'avg_time': float(stats_result['avg_time'] or 0)
            }

        # 各题目统计 - 添加错误处理
        cursor.execute("""
            WITH attempt_summary AS (
                SELECT
                    template_id,
                    attempt_count,
                    COUNT(*) AS total_answers,
                    SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS correct_answers,
                    MAX(time_taken) AS time_taken
                FROM user_responses
                WHERE user_id = %s
                GROUP BY template_id, attempt_count
            )
            SELECT
                t.template_name,
                COUNT(*) AS total,
                SUM(CASE WHEN s.correct_answers = s.total_answers THEN 1 ELSE 0 END) AS correct,
                AVG(s.time_taken) AS avg_time
            FROM attempt_summary s
            JOIN problem_templates t ON s.template_id = t.id
            GROUP BY s.template_id, t.template_name
            ORDER BY t.id
        """, (session['user_id'],))

        problem_stats_result = cursor.fetchall()

        # 转换problem_stats中的Decimal类型
        problem_stats = []
        for stat in problem_stats_result:
            problem_stats.append({
                'template_name': stat['template_name'],
                'total': int(stat['total']),
                'correct': int(stat['correct'] or 0),
                'avg_time': float(stat['avg_time'] or 0)
            })

        # 计算正确率
        accuracy = 0
        if stats['total_count'] > 0:
            accuracy = round(stats['correct_count'] / stats['total_count'] * 100, 1)

        print(
            f"[DEBUG] 统计数据: total_count={stats['total_count']}, correct_count={stats['correct_count']}, accuracy={accuracy}%")
        print(f"[DEBUG] 题目统计: {len(problem_stats)} 条记录")

        return render_template('stats.html',
                               accuracy=accuracy,
                               correct_count=stats['correct_count'],
                               total_count=stats['total_count'],
                               avg_time=round(stats['avg_time'], 1),
                               problem_stats=problem_stats,
                               username=session['username'])

    except Exception as e:
        print(f"[统计页面错误] {str(e)}")
        import traceback
        print(f"[详细错误] {traceback.format_exc()}")
        flash(f'获取统计信息失败: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))
    finally:
        if conn and conn.is_connected():
            conn.close()


@app.route('/debug/images')
def debug_images():
    import os
    static_path = os.path.join(app.root_path, 'static', 'images')
    files = os.listdir(static_path) if os.path.exists(static_path) else []
    return jsonify({
        'static_folder': app.static_folder,
        'images_path': static_path,
        'files': files
    })


@app.route('/debug/reload_templates', methods=['GET'])
def reload_templates():
    global TEMPLATE_CACHE, TEMPLATE_CACHE_TS
    TEMPLATE_CACHE = {}
    TEMPLATE_CACHE_TS = time.time()
    return jsonify({'success': True, 'message': '模板缓存已清空', 'timestamp': TEMPLATE_CACHE_TS})


@app.route('/history')
@login_required
def history():
    """获取答题历史"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 获取答题记录
        cursor.execute("""
            SELECT 
                r.id,
                t.template_name,
                r.problem_text,
                r.user_answer,
                r.correct_answer,
                r.is_correct,
                r.attempt_count,
                r.response_time,
                r.time_taken,
                t.id as template_id
            FROM user_responses r
            JOIN problem_templates t ON r.template_id = t.id
            WHERE r.user_id = %s
            ORDER BY r.response_time DESC
        """, (session['user_id'],))

        responses = cursor.fetchall()

        # 格式化时间
        for response in responses:
            if response['response_time']:
                response['formatted_time'] = response['response_time'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                response['formatted_time'] = '未知时间'

        # 获取统计信息
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as correct_count,
                AVG(time_taken) as avg_time
            FROM user_responses 
            WHERE user_id = %s
        """, (session['user_id'],))

        stats_result = cursor.fetchone()

        # 处理统计信息
        stats = None
        if stats_result and stats_result['total']:
            stats = {
                'total': int(stats_result['total']),
                'correct': int(stats_result['correct_count'] or 0),
                'avg_time': float(stats_result['avg_time'] or 0)
            }

        return render_template('history.html',
                               responses=responses,
                               stats=stats,
                               username=session['username'])

    except Exception as e:
        print(f"[系统错误] 获取答题历史失败: {str(e)}")
        flash('获取答题历史失败，请稍后再试', 'danger')
        return render_template('history.html',
                               responses=[],
                               stats=None,
                               username=session['username'])
    finally:
        if conn:
            conn.close()


@app.route('/debug/history')
@login_required
def debug_history():
    """调试历史记录"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 检查用户记录
    cursor.execute("SELECT COUNT(*) as count FROM user_responses WHERE user_id = %s", (session['user_id'],))
    user_count = cursor.fetchone()

    # 检查表结构
    cursor.execute("DESCRIBE user_responses")
    table_structure = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify({
        'user_id': session['user_id'],
        'user_response_count': user_count['count'],
        'table_structure': table_structure
    })


@app.route('/all_problems')
@login_required
def all_problems():
    """展示所有题目列表 - 使用显示序号"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 获取题目显示映射
        display_mapping = get_problem_display_info()

        # 获取所有题目模板按实际ID排序
        cursor.execute(
            "SELECT id, template_name, problem_text, variables, difficulty, image_filename FROM problem_templates ORDER BY id")
        templates = cursor.fetchall()

        problems = []

        for template in templates:
            # 获取显示序号
            display_number = get_display_number(template['id'])

            # 生成变量值
            variables = [v.strip() for v in template['variables'].split(',')] if template['variables'] else []
            var_values = {}

            for var in variables:
                var_values[var] = round(random.uniform(0, 20.0), 2)

            # 使用正则表达式格式化模板
            import re
            problem_text = template['problem_text']
            pattern = r'__(\w+)__'

            def replace_var(match):
                var_name = match.group(1)
                if var_name in var_values:
                    return str(var_values[var_name])
                else:
                    return match.group(0)

            problem_content = re.sub(pattern, replace_var, problem_text)

            # 检查题目是否已完成
            completed = has_full_correct_attempt(cursor, session['user_id'], template['id'])

            # 获取答题统计（如果已完成）
            stats = None
            if completed:
                stats_result = get_latest_full_correct_attempt(cursor, session['user_id'], template['id'])
                if stats_result:
                    stats = {
                        'time_taken': round(stats_result['time_taken'], 1),
                        'attempt_count': stats_result['attempt_count'],
                        'score': stats_result['score']
                    }

            problems.append({
                'id': template['id'],
                'display_number': display_number,  # 添加显示序号
                'name': template['template_name'],
                'content': problem_content,
                'var_values': var_values,
                'completed': completed,
                'stats': stats,
                'difficulty': template.get('difficulty', 'medium'),
                'image_filename': template.get('image_filename')
            })

        return render_template('all_problem.html',
                               problems=problems,
                               username=session['username'])

    except Exception as e:
        print(f"获取题目列表失败: {str(e)}")
        flash('获取题目列表失败', 'danger')
        return redirect(url_for('dashboard'))
    finally:
        if conn and conn.is_connected():
            conn.close()


@app.route('/refresh_problem/<int:problem_id>', methods=['POST'])
@login_required
def refresh_problem(problem_id):
    """刷新单个题目"""
    try:
        # 根据显示序号获取实际ID
        actual_id = get_actual_id(problem_id)
        if actual_id is None:
            return jsonify({'success': False, 'message': '无效的题目编号'})

        token, problem_data = fetch_problem_from_pool(actual_id)
        if not problem_data:
            token, problem_data = generate_and_cache_problem(actual_id)

        if not problem_data or not token:
            return jsonify({'success': False, 'message': '题目生成失败'})

        # 更新session中的题目状态
        if 'current_problem' in session and session['current_problem']['display_number'] == problem_id:
            session['current_problem'].update({
                'token': token,
                'total_attempts': 0,
                'answered_correctly': False,
                'start_time': time.time(),
                'actual_id': actual_id
            })

        return jsonify({'success': True, 'message': '题目刷新成功', 'token': token})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/refresh_all_problems', methods=['POST'])
@login_required
def refresh_all_problems():
    """刷新所有题目"""
    try:
        # 清除当前题目session，下次访问时会重新生成
        session.pop('current_problem', None)
        return jsonify({'success': True, 'message': '所有题目已刷新'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/problem_ajax/<int:problem_id>')  # 保持参数名为 problem_id
@login_required
def problem_ajax(problem_id):
    """支持Ajax的问题页面 - 内部将problem_id作为显示序号使用"""
    print(f"\n=== Ajax问题页面开始 ===")
    print(f"显示序号: {problem_id}")

    # 根据显示序号获取实际ID
    actual_id = get_actual_id(problem_id)
    if actual_id is None:
        flash('无效的题目编号', 'danger')
        return redirect(url_for('dashboard'))

    # 获取题目显示映射和总数
    display_mapping = get_problem_display_info()
    display_to_actual = build_display_to_actual_map()
    total_problems = len(display_mapping)

    # 1. 验证题目序号
    if problem_id < 1 or problem_id > total_problems:
        flash('无效的题目编号', 'danger')
        return redirect(url_for('dashboard'))

    # 2. 初始化或获取题目数据
    problem_data = None
    problem_token = None

    if ('current_problem' in session and
            session['current_problem'].get('display_number') == problem_id):
        problem_token = session['current_problem'].get('token')
        problem_data = get_problem_by_token(problem_token)
        if not problem_data:
            print("缓存中的题目已过期，重新获取新题目")

    if not problem_data:
        print(f"生成/获取新题目... 实际ID: {actual_id}")
        problem_token, problem_data = fetch_problem_from_pool(actual_id)

        if not problem_data:
            problem_token, problem_data = generate_and_cache_problem(actual_id)

        if not problem_data:
            flash('题目生成失败', 'danger')
            return redirect(url_for('dashboard'))

        session['current_problem'] = {
            'display_number': problem_id,
            'actual_id': actual_id,
            'token': problem_token,
            'total_attempts': 0,
            'answered_correctly': False,
            'start_time': time.time()
        }
        print(f"新题目生成成功，答案数量: {problem_data.get('answer_count', 1)}")
    else:
        # 确保最小状态存在
        session['current_problem'].setdefault('total_attempts', 0)
        session['current_problem'].setdefault('answered_correctly', False)
        session['current_problem'].setdefault('start_time', time.time())
        session['current_problem'].setdefault('token', problem_token)
        session['current_problem']['actual_id'] = actual_id

    # 3. 检查是否已经完成
    if session['current_problem'].get('answered_correctly', False):
        print(f"题目 {problem_id} 已完成")

    # 4. 渲染Ajax模板
    total_attempts = session['current_problem'].get('total_attempts', 0)
    answer_count = problem_data.get('answer_count', 1)

    # 确保token写回session（兼容旧数据）
    session['current_problem']['token'] = problem_token or session['current_problem'].get('token')
    session.modified = True

    print(f"渲染Ajax模板，显示序号: {problem_id}, 实际ID: {actual_id}")
    print(f"答案数量: {answer_count}, 累计尝试: {total_attempts}")
    print(f"当前题目参数: {problem_data['var_values']}")
    print(f"=== Ajax问题页面结束 ===\n")

    is_completed = is_problem_completed(session['user_id'], actual_id)

    return render_template('problem_ajax.html',
                           problem=problem_data,
                           problem_id=problem_id,  # 传递显示序号到模板
                           total_attempts=total_attempts,
                           answer_count=answer_count,
                           username=session['username'],
                           total_problems=total_problems,
                           display_mapping=display_mapping,
                           display_to_actual=display_to_actual,
                           is_completed=is_completed)


@app.route('/api/submit/<int:problem_id>', methods=['POST'])  # 保持参数名为 problem_id
@login_required
def api_submit(problem_id):
    """API接口：提交答案 - 内部将problem_id作为显示序号使用"""
    try:
        data = request.get_json()
        print(f"[API] 显示序号 {problem_id} 提交数据: {data}")

        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'})

        # 根据显示序号获取实际ID
        actual_id = get_actual_id(problem_id)
        if actual_id is None:
            return jsonify({'success': False, 'message': '无效的题目编号'})

        # 获取题目显示映射和总数
        display_mapping = get_problem_display_info()
        total_problems = len(display_mapping)

        # 验证会话
        if ('current_problem' not in session or
                session['current_problem']['display_number'] != problem_id):
            return jsonify({'success': False, 'message': '会话过期，请重新开始答题'})

        problem_token = session['current_problem'].get('token')
        problem_data = get_problem_by_token(problem_token)
        if not problem_data:
            return jsonify({'success': False, 'message': '题目已过期，请刷新后重试'})

        correct_answers = problem_data.get('correct_answers', [])
        answer_count = problem_data.get('answer_count', 1)
        time_taken = float(data.get('time_taken', 0))
        user_id = session['user_id']
        template_id = problem_data['template_id']
        problem_text = problem_data['problem_text']

        # 如果题目已完成，阻止重复作答
        if is_problem_completed(user_id, actual_id):
            return jsonify({
                'success': False,
                'message': '该题已完成，无需重复作答',
                'already_completed': True
            })

        print(f"[API DEBUG] 用户 {user_id} 提交问题 {problem_id} (实际ID: {actual_id})")
        print(f"模板ID: {template_id}")
        print(f"答案数量: {answer_count}")
        print(f"当前累计尝试次数: {session['current_problem']['total_attempts']}")
        print(f"答题用时: {time_taken}秒")
        print(f"正确答案: {correct_answers}")

        # 验证答题时间的合理性
        if time_taken < 0:
            print(f"[API WARNING] 无效的答题时间: {time_taken}秒，重置为0")
            time_taken = 0
        elif time_taken > 86400:  # 超过24小时
            print(f"[API WARNING] 答题时间异常长: {time_taken}秒，限制为3600秒")
            time_taken = 3600
        elif time_taken < 1:  # 少于1秒（可能有问题）
            print(f"[API WARNING] 答题时间过短: {time_taken}秒，可能计时器有问题")
        elif time_taken > 3600:  # 超过1小时
            print(f"[API INFO] 答题时间较长: {time_taken}秒")

        print(f"[API] 最终记录用时: {time_taken:.2f}秒")

        # 获取用户答案
        user_answers = []
        for i in range(answer_count):
            if answer_count == 1:
                user_answer = float(data.get('answer', 0))
                user_answers.append(user_answer)
            else:
                user_answer = float(data.get(f'answer{i + 1}', 0))
                user_answers.append(user_answer)

        print(f"用户答案: {user_answers}")

        # 验证每个答案
        is_correct_list = []
        all_correct = True

        for i, (user_answer, correct_answer) in enumerate(zip(user_answers, correct_answers)):
            # 使用不同的变量名避免冲突
            answer_is_correct = is_correct(user_answer, correct_answer)
            is_correct_list.append(answer_is_correct)
            if not answer_is_correct:
                all_correct = False
            print(
                f"答案{i + 1}: {user_answer} (正确: {correct_answer}, 结果: {'正确' if answer_is_correct else '错误'})")

        error_types = [
            classify_error_type(user_answer, correct_answer, is_correct)
            for user_answer, correct_answer, is_correct in zip(user_answers, correct_answers, is_correct_list)
        ]

        # 增加累计尝试次数
        session['current_problem']['total_attempts'] += 1
        total_attempts = session['current_problem']['total_attempts']

        # 保存答题记录 - 使用更新后的累计尝试次数
        save_success = save_user_response(
            user_id, template_id, problem_text, user_answers,
            correct_answers, is_correct_list, total_attempts, time_taken, error_types
        )

        if not save_success:
            print(f"[API ERROR] 保存答题记录失败")
            # 即使保存失败，也继续处理，但记录警告
            session['current_problem']['save_failed'] = True

        # 生成正确答案消息
        correct_answer_message = "正确答案: "
        if answer_count == 1:
            correct_answer_message += f"{correct_answers[0]:.2f}"
        else:
            correct_parts = []
            for i, correct_answer in enumerate(correct_answers):
                correct_parts.append(f"答案{i + 1} = {correct_answer:.2f}")
            correct_answer_message += ", ".join(correct_parts)

        # 更新会话状态
        new_problem_data = None
        response_data = {}

        if all_correct:
            # 回答正确后更新用户完成状态
            completed_all = update_user_completion_status(user_id)

            session['current_problem']['answered_correctly'] = True
            next_problem_id = problem_id + 1 if problem_id < total_problems else None

            # 构建成功消息
            message = f'🎉 回答正确！用时 {time_taken:.1f}秒，尝试 {total_attempts} 次。'

            response_data.update({
                'correct': True,
                'message': message,
                'time_taken': time_taken,
                'total_attempts': total_attempts,
                'next_problem': next_problem_id,
                'completed_all': completed_all if problem_id >= total_problems else False
            })

            # 如果完成所有题目，生成验证链接
            if completed_all and problem_id >= total_problems:
                verification_url = f"/api/user/{user_id}/completion"
                session['verification_url'] = verification_url
                response_data['verification_url'] = verification_url
                response_data['completion_message'] = '恭喜您完成了所有题目！'
        else:
            session['current_problem']['answered_correctly'] = False
            next_problem_id = problem_id

            # 答错时生成新题目（不再限制尝试次数）
            new_token, new_problem_data = fetch_problem_from_pool(actual_id)
            if not new_problem_data:
                new_token, new_problem_data = generate_and_cache_problem(actual_id)

            if new_problem_data:
                # 更新session中的题目数据和正确答案
                session['current_problem']['token'] = new_token
                session['current_problem']['start_time'] = time.time()

                # 构建错误消息
                message = f'❌ 答案不正确！用时 {time_taken:.1f}秒。{correct_answer_message}。已为您生成新题目，请重新作答。'

                response_data.update({
                    'correct': False,
                    'message': message,
                    'correct_answers': correct_answers,
                    'total_attempts': total_attempts,
                    'next_problem': next_problem_id,
                    'new_problem_generated': True,
                    'new_var_values': new_problem_data['var_values'],
                    'new_correct_answers': new_problem_data['correct_answers'],
                    'new_problem_text': new_problem_data['problem_text'],
                    'token': new_token
                })

                print(f"[API] 生成新题目参数: {new_problem_data['var_values']}")
                print(f"[API] 生成新正确答案: {new_problem_data['correct_answers']}")
            else:
                # 题目生成失败
                message = f'❌ 答案不正确！{correct_answer_message}。题目刷新失败，请重试。'
                response_data.update({
                    'correct': False,
                    'message': message,
                    'correct_answers': correct_answers,
                    'total_attempts': total_attempts,
                    'next_problem': next_problem_id,
                    'new_problem_generated': False
                })

        # 确保session被修改
        session.modified = True

        # 基础响应数据
        response_data.update({
            'success': True,
            'save_success': save_success,
            'user_answers': user_answers,
            'answer_count': answer_count,
            'problem_id': problem_id,
            'actual_id': actual_id
        })

        print(f"[API RESPONSE] 返回数据: {response_data}")
        return jsonify(response_data)

    except ValueError as e:
        print(f"[API ERROR] 数值转换错误: {str(e)}")
        return jsonify({'success': False, 'message': '请输入有效的数字格式'})
    except KeyError as e:
        print(f"[API ERROR] 缺少必要字段: {str(e)}")
        return jsonify({'success': False, 'message': f'缺少必要字段: {str(e)}'})
    except Exception as e:
        print(f"[API ERROR] 服务器错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'})


# 管理员主页
@app.route('/admin')
@login_required
def admin_dashboard():
    """管理员主页"""
    if session.get('username') != 'admin':
        flash('权限不足', 'danger')
        return redirect(url_for('dashboard'))

    # 获取统计数据
    stats = get_completion_stats()
    total_problems = get_total_problem_count()

    # 获取最近完成的学生
    recent_completions = get_students_by_completion(completed=True, limit=10)

    # 获取需要督促的学生
    incomplete_students = get_students_by_completion(completed=False, limit=10)

    return render_template('admin_dashboard.html',
                           stats=stats,
                           recent_completions=recent_completions,
                           incomplete_students=incomplete_students,
                           total_problems=total_problems)


@app.route('/admin/export/students/<status>')
@login_required
def admin_export_students(status):
    """导出已完成/未完成学生列表"""
    if session.get('username') != 'admin':
        flash('权限不足', 'danger')
        return redirect(url_for('dashboard'))

    if status not in {'completed', 'incomplete'}:
        flash('无效的导出类型', 'danger')
        return redirect(url_for('admin_dashboard'))

    completed = (status == 'completed')
    students = get_students_by_completion(completed=completed)
    total_problems = get_total_problem_count()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        '学生ID',
        '用户名',
        '完成状态',
        '完成题目数',
        '总题目数',
        '完成时间',
        '总用时(秒)',
        '注册时间'
    ])

    status_label = '已完成' if completed else '未完成'
    for student in students:
        completed_at = student['completed_at'].strftime('%Y-%m-%d %H:%M:%S') if student['completed_at'] else ''
        created_at = student['created_at'].strftime('%Y-%m-%d %H:%M:%S') if student['created_at'] else ''
        writer.writerow([
            student['id'],
            student['username'],
            status_label,
            student['total_score'] or 0,
            total_problems,
            completed_at,
            round(student['total_time'] or 0, 1),
            created_at
        ])

    filename = f"students_{status}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = Response(output.getvalue(), mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response


@app.route('/admin/export/overview')
@login_required
def admin_export_overview():
    """导出整体答题情况统计"""
    if session.get('username') != 'admin':
        flash('权限不足', 'danger')
        return redirect(url_for('dashboard'))

    stats = get_completion_stats()
    total_problems = get_total_problem_count()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        WITH attempt_summary AS (
            SELECT
                ur.user_id,
                ur.template_id,
                ur.attempt_count,
                COUNT(*) AS total_answers,
                SUM(CASE WHEN ur.is_correct THEN 1 ELSE 0 END) AS correct_answers,
                MAX(ur.time_taken) AS time_taken
            FROM user_responses ur
            JOIN users u ON ur.user_id = u.id
            WHERE u.username != 'admin'
            GROUP BY ur.user_id, ur.template_id, ur.attempt_count
        )
        SELECT
            COUNT(*) as total_attempts,
            SUM(time_taken) as total_time,
            AVG(time_taken) as avg_time,
            AVG(CASE WHEN correct_answers = total_answers THEN time_taken ELSE NULL END) as avg_correct_time
        FROM attempt_summary
    """)
    overall_stats = cursor.fetchone() or {}
    cursor.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        '总学生数',
        '已完成学生数',
        '未完成学生数',
        '完成率(%)',
        '平均正确题数',
        '平均用时(秒)',
        '今日完成人数',
        '总题目数',
        '总答题次数',
        '总答题时长(秒)',
        '平均答题时长(秒)',
        '平均正确答题时长(秒)'
    ])
    total_students = stats['stats']['total_students'] or 0
    completed_students = stats['stats']['completed_count'] or 0
    writer.writerow([
        total_students,
        completed_students,
        max(total_students - completed_students, 0),
        stats['stats']['completion_rate'] or 0,
        round(stats['stats']['avg_score'] or 0, 1),
        round(stats['stats']['avg_time'] or 0, 1),
        stats['today_stats']['today_completions'] or 0,
        total_problems,
        overall_stats.get('total_attempts') or 0,
        round(overall_stats.get('total_time') or 0, 1),
        round(overall_stats.get('avg_time') or 0, 1),
        round(overall_stats.get('avg_correct_time') or 0, 1)
    ])

    filename = f"overview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = Response(output.getvalue(), mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response


@app.route('/admin/export/problem-stats')
@login_required
def admin_export_problem_stats():
    """导出题目统计"""
    if session.get('username') != 'admin':
        flash('权限不足', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        WITH attempt_summary AS (
            SELECT
                ur.user_id,
                ur.template_id,
                ur.attempt_count,
                COUNT(*) AS total_answers,
                SUM(CASE WHEN ur.is_correct THEN 1 ELSE 0 END) AS correct_answers,
                MAX(ur.time_taken) AS time_taken
            FROM user_responses ur
            JOIN users u ON ur.user_id = u.id
            WHERE u.username != 'admin'
            GROUP BY ur.user_id, ur.template_id, ur.attempt_count
        )
        SELECT
            t.id as template_id,
            t.template_name,
            COUNT(a.attempt_count) as total_attempts,
            SUM(CASE WHEN a.correct_answers = a.total_answers THEN 1 ELSE 0 END) as correct_attempts,
            COUNT(DISTINCT CASE WHEN a.correct_answers = a.total_answers THEN a.user_id END) as completed_students,
            COUNT(DISTINCT a.user_id) as participant_students,
            AVG(a.time_taken) as avg_time,
            AVG(CASE WHEN a.correct_answers = a.total_answers THEN a.time_taken ELSE NULL END) as avg_correct_time,
            SUM(a.time_taken) as total_time_spent,
            COALESCE((
                SELECT error_type
                FROM user_responses ur2
                JOIN users u2 ON ur2.user_id = u2.id
                WHERE ur2.template_id = t.id AND u2.username != 'admin' AND ur2.is_correct = FALSE
                GROUP BY error_type
                ORDER BY COUNT(*) DESC
                LIMIT 1
            ), '暂无数据') as top_error_type
        FROM problem_templates t
        LEFT JOIN attempt_summary a ON t.id = a.template_id
        ORDER BY t.id
    """)
    problem_stats = cursor.fetchall()

    cursor.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        '题目ID',
        '题目名称',
        '总答题次数',
        '正确答题次数',
        '完成学生数',
        '参与学生数',
        '正确率(%)',
        '平均用时(秒)',
        '平均正确用时(秒)',
        '总用时(秒)',
        '最常见错误类型'
    ])

    for stat in problem_stats:
        total_attempts = stat['total_attempts'] or 0
        correct_attempts = stat['correct_attempts'] or 0
        correct_rate = round((correct_attempts / total_attempts) * 100, 1) if total_attempts else 0
        writer.writerow([
            stat['template_id'],
            stat['template_name'],
            total_attempts,
            correct_attempts,
            stat['completed_students'] or 0,
            stat['participant_students'] or 0,
            correct_rate,
            round(stat['avg_time'] or 0, 1),
            round(stat['avg_correct_time'] or 0, 1),
            round(stat['total_time_spent'] or 0, 1),
            stat['top_error_type']
        ])

    filename = f"problem_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = Response(output.getvalue(), mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response


@app.route('/admin/add_problem', methods=['GET', 'POST'])
@login_required
def admin_add_problem():
    """添加新题目"""
    if session.get('username') != 'admin':
        flash('权限不足', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        try:
            template_name = request.form['template_name']
            problem_text = request.form['problem_text']
            variables = request.form['variables']
            solution_formula = request.form['solution_formula']
            answer_count = int(request.form.get('answer_count', 1))
            difficulty = request.form.get('difficulty', 'medium')

            # 处理图片上传
            image_filename = None
            if 'problem_image' in request.files:
                file = request.files['problem_image']
                if file and file.filename != '':
                    image_filename = save_uploaded_file(file)
                    if image_filename:
                        # 在题目内容中插入图片
                        img_html = f'<div class="text-center mb-3"><img src="/static/images/{image_filename}" alt="{template_name}" class="problem-image img-fluid"><div class="image-caption text-muted">图：{template_name}</div></div>'
                        problem_text = img_html + problem_text

            conn = get_db_connection()
            cursor = conn.cursor()

            # 插入新题目模板
            cursor.execute("""
                INSERT INTO problem_templates 
                (template_name, problem_text, variables, solution_formula, answer_count, difficulty, image_filename)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (template_name, problem_text, variables, solution_formula, answer_count, difficulty, image_filename))

            conn.commit()
            cursor.close()
            conn.close()

            flash('题目添加成功！', 'success')
            return redirect(url_for('admin_manage_problems'))

        except Exception as e:
            print(f"添加题目失败: {str(e)}")
            flash(f'添加题目失败: {str(e)}', 'danger')

    return render_template('admin_add_problem.html')


@app.route('/admin/manage_problems')
@login_required
def admin_manage_problems():
    """管理所有题目"""
    if session.get('username') != 'admin':
        flash('权限不足', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM problem_templates ORDER BY id")
    templates = cursor.fetchall()

    # 获取显示序号映射
    display_mapping = get_problem_display_info()
    for template in templates:
        template['display_number'] = get_display_number(template['id'])

    cursor.close()
    conn.close()

    return render_template('admin_manage_problems.html',
                           templates=templates,
                           display_mapping=display_mapping)


@app.route('/admin/edit_problem/<int:template_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_problem(template_id):
    """编辑题目"""
    if session.get('username') != 'admin':
        flash('权限不足', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        try:
            template_name = request.form['template_name']
            problem_text = request.form['problem_text']
            variables = request.form['variables']
            solution_formula = request.form['solution_formula']
            answer_count = int(request.form.get('answer_count', 1))
            difficulty = request.form.get('difficulty', 'medium')
            remove_image = request.form.get('remove_image') == 'true'
            current_image = request.form.get('current_image', '')

            # 处理图片更新
            image_filename = current_image if current_image else None

            if remove_image:
                # 删除图片
                image_filename = None
                # 从问题文本中移除图片
                problem_text = re.sub(r'<div class="text-center mb-3">.*?</div>', '', problem_text, count=1,
                                      flags=re.DOTALL)
            elif 'problem_image' in request.files:
                file = request.files['problem_image']
                if file and file.filename != '':
                    # 上传新图片
                    image_filename = save_uploaded_file(file)
                    if image_filename:
                        # 在题目内容中插入图片
                        img_html = f'<div class="text-center mb-3"><img src="/static/images/{image_filename}" alt="{template_name}" class="problem-image img-fluid"><div class="image-caption text-muted">图：{template_name}</div></div>'
                        # 移除旧的图片并添加新的
                        problem_text = re.sub(r'<div class="text-center mb-3">.*?</div>', '', problem_text, count=1,
                                              flags=re.DOTALL)
                        problem_text = img_html + problem_text

            cursor.execute("""
                UPDATE problem_templates 
                SET template_name = %s, problem_text = %s, variables = %s, 
                    solution_formula = %s, answer_count = %s, difficulty = %s, image_filename = %s
                WHERE id = %s
            """, (template_name, problem_text, variables, solution_formula, answer_count, difficulty, image_filename,
                  template_id))

            conn.commit()
            flash('题目更新成功！', 'success')
            return redirect(url_for('admin_manage_problems'))

        except Exception as e:
            print(f"更新题目失败: {str(e)}")
            flash(f'更新题目失败: {str(e)}', 'danger')

    # 获取题目信息
    cursor.execute("SELECT * FROM problem_templates WHERE id = %s", (template_id,))
    template = cursor.fetchone()
    cursor.close()
    conn.close()

    if not template:
        flash('题目不存在', 'danger')
        return redirect(url_for('admin_manage_problems'))

    return render_template('admin_edit_problem.html', template=template)


@app.route('/admin/delete_problem/<int:template_id>')
@login_required
def admin_delete_problem(template_id):
    """删除题目并清理相关图片"""
    if session.get('username') != 'admin':
        flash('权限不足', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 先获取题目的图片信息
        cursor.execute("SELECT image_filename FROM problem_templates WHERE id = %s", (template_id,))
        template = cursor.fetchone()

        # 删除相关的答题记录
        cursor.execute("DELETE FROM user_responses WHERE template_id = %s", (template_id,))
        # 删除题目模板
        cursor.execute("DELETE FROM problem_templates WHERE id = %s", (template_id,))

        conn.commit()

        # 删除题目后刷新所有用户的完成状态和统计
        try:
            updated_count = update_all_users_completion_status()
            print(f"ℹ️ 已刷新 {updated_count} 个用户的完成状态")
        except Exception as update_error:
            print(f"⚠️ 删除题目后刷新完成状态失败: {update_error}")

        # 如果题目有专属图片，检查并删除图片文件
        if template and template['image_filename']:
            try:
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], template['image_filename'])
                if os.path.exists(image_path):
                    # 检查是否还有其他题目使用这个图片
                    cursor.execute("SELECT COUNT(*) as usage_count FROM problem_templates WHERE image_filename = %s",
                                   (template['image_filename'],))
                    usage = cursor.fetchone()
                    if usage['usage_count'] == 0:
                        os.remove(image_path)
                        print(f"✅ 已删除未使用的图片: {template['image_filename']}")
                    else:
                        print(f"ℹ️ 图片 {template['image_filename']} 仍被其他题目使用，保留文件")
            except Exception as e:
                print(f"⚠️ 删除图片文件失败: {e}")

        flash('题目删除成功！', 'success')
    except Exception as e:
        print(f"❌ 删除题目失败: {str(e)}")
        flash(f'删除题目失败: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin_manage_problems'))


@app.route('/admin/update_all_status')
@login_required
def update_all_status():
    """批量更新所有用户的完成状态"""
    if session.get('username') != 'admin':
        flash('权限不足', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        updated_count = update_all_users_completion_status()
        flash(f'成功更新 {updated_count} 个用户的完成状态', 'success')

    except Exception as e:
        print(f"批量更新状态失败: {e}")
        flash('更新状态失败', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin_dashboard'))


# 用户完成状态API
@app.route('/api/user/<int:user_id>/completion')
def check_completion(user_id):
    """检查用户完成状态 - 公开API"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT 
            u.username,
            u.completed_all,
            u.completed_at,
            u.total_score,
            u.total_time,
            COUNT(DISTINCT r.template_id) as completed_problems,
            MAX(r.response_time) as last_completion_time
        FROM users u
        LEFT JOIN user_responses r ON u.id = r.user_id AND r.is_correct = TRUE
        WHERE u.id = %s
        GROUP BY u.id
    """, (user_id,))

    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if result:
        return jsonify({
            'user_id': user_id,
            'username': result['username'],
            'completed_all': result['completed_all'],
            'completed_problems': result['completed_problems'],
            'total_score': result['total_score'],
            'total_time': result['total_time'],
            'completed_at': result['completed_at'],
            'last_completion_time': result['last_completion_time'],
            'verified': True
        })
    else:
        return jsonify({
            'user_id': user_id,
            'error': '用户不存在',
            'verified': False
        }), 404


# 管理员功能 - 学生完成情况
@app.route('/admin/students/<status>')
@login_required
def admin_students_by_status(status):
    """按完成状态查看学生列表"""
    if session.get('username') != 'admin':
        flash('权限不足', 'danger')
        return redirect(url_for('dashboard'))

    completed = (status == 'completed')
    students = get_students_by_completion(completed=completed)
    total_problems = get_total_problem_count()
    completion_stats = get_completion_stats()
    total_students = completion_stats['stats']['total_students'] or 0
    completed_students = completion_stats['stats']['completed_count'] or 0

    status_text = '已完成' if completed else '未完成'

    return render_template('admin_students.html',
                           students=students,
                           status=status,
                           status_text=status_text,
                           total_problems=total_problems,
                           total_students=total_students,
                           completed_students=completed_students,
                           username=session['username'])


# 管理员功能 - 学生详细答题情况
@app.route('/admin/student/<int:user_id>/details')
@login_required
def admin_student_details(user_id):
    """查看学生详细答题情况"""
    if session.get('username') != 'admin':
        flash('权限不足', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 获取学生基本信息
        cursor.execute("SELECT username, completed_all, total_score, total_time FROM users WHERE id = %s", (user_id,))
        student = cursor.fetchone()

        if not student:
            flash('学生不存在', 'danger')
            return redirect(url_for('admin_dashboard'))

        # 获取题目总数
        total_problems = get_total_problem_count()

        # 基于提交次数的统计（按 attempt_count 聚合）
        cursor.execute("""
            WITH attempt_summary AS (
                SELECT
                    template_id,
                    attempt_count,
                    COUNT(*) AS total_answers,
                    SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS correct_answers,
                    MAX(time_taken) AS time_taken,
                    MAX(response_time) AS last_response_time
                FROM user_responses
                WHERE user_id = %s
                GROUP BY template_id, attempt_count
            )
            SELECT
                t.id as template_id,
                t.template_name,
                COUNT(a.attempt_count) as total_attempts,
                SUM(CASE WHEN a.correct_answers = a.total_answers THEN 1 ELSE 0 END) as correct_attempts,
                MIN(CASE WHEN a.correct_answers = a.total_answers THEN a.time_taken ELSE NULL END) as best_time,
                AVG(a.time_taken) as avg_time,
                MAX(a.last_response_time) as last_attempt_time
            FROM problem_templates t
            LEFT JOIN attempt_summary a ON t.id = a.template_id
            GROUP BY t.id, t.template_name
            ORDER BY t.id
        """, (user_id,))

        problem_stats = cursor.fetchall()

        # 计算总体统计
        cursor.execute("""
            WITH attempt_summary AS (
                SELECT
                    template_id,
                    attempt_count,
                    COUNT(*) AS total_answers,
                    SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS correct_answers,
                    MAX(time_taken) AS time_taken
                FROM user_responses
                WHERE user_id = %s
                GROUP BY template_id, attempt_count
            )
            SELECT
                COUNT(*) as total_attempts,
                SUM(CASE WHEN correct_answers = total_answers THEN 1 ELSE 0 END) as total_correct,
                AVG(time_taken) as overall_avg_time
            FROM attempt_summary
        """, (user_id,))

        overall_stats = cursor.fetchone()

        return render_template('admin_student_details.html',
                               student=student,
                               problem_stats=problem_stats,
                               overall_stats=overall_stats,
                               total_problems=total_problems,
                               username=session['username'],
                               get_display_number=get_display_number)  # 传递函数到模板

    except Exception as e:
        print(f"获取学生详情失败: {str(e)}")
        import traceback
        print(f"详细错误: {traceback.format_exc()}")
        flash('获取学生详情失败', 'danger')
        return redirect(url_for('admin_dashboard'))
    finally:
        cursor.close()
        conn.close()


# 管理员功能 - 所有学生题目答题情况
@app.route('/admin/all_problems_stats')
@login_required
def admin_all_problems_stats():
    """查看所有学生对每道题的答题情况"""
    if session.get('username') != 'admin':
        flash('权限不足', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 题目层级统计（按提交次数统计）
        cursor.execute("""
            WITH attempt_summary AS (
                SELECT
                    ur.user_id,
                    ur.template_id,
                    ur.attempt_count,
                    COUNT(*) AS total_answers,
                    SUM(CASE WHEN ur.is_correct THEN 1 ELSE 0 END) AS correct_answers,
                    MAX(ur.time_taken) AS time_taken
                FROM user_responses ur
                JOIN users u ON ur.user_id = u.id
                WHERE u.username != 'admin'
                GROUP BY ur.user_id, ur.template_id, ur.attempt_count
            )
            SELECT
                t.id as template_id,
                t.template_name,
                COUNT(a.attempt_count) as total_attempts,
                SUM(CASE WHEN a.correct_answers = a.total_answers THEN 1 ELSE 0 END) as correct_attempts,
                COUNT(DISTINCT CASE WHEN a.correct_answers = a.total_answers THEN a.user_id END) as completed_students,
                COUNT(DISTINCT a.user_id) as participant_students,
                AVG(a.time_taken) as avg_time,
                AVG(CASE WHEN a.correct_answers = a.total_answers THEN a.time_taken ELSE NULL END) as avg_correct_time,
                SUM(a.time_taken) as total_time_spent,
                COALESCE((
                    SELECT error_type
                    FROM user_responses ur2
                    JOIN users u2 ON ur2.user_id = u2.id
                    WHERE ur2.template_id = t.id AND u2.username != 'admin' AND ur2.is_correct = FALSE
                    GROUP BY error_type
                    ORDER BY COUNT(*) DESC
                    LIMIT 1
                ), '暂无数据') as top_error_type
            FROM problem_templates t
            LEFT JOIN attempt_summary a ON t.id = a.template_id
            GROUP BY t.id, t.template_name
            ORDER BY t.id
        """)

        problem_stats = cursor.fetchall()

        # 计算正确率
        for stat in problem_stats:
            if stat['total_attempts'] and stat['total_attempts'] > 0:
                stat['correct_rate'] = round((stat['correct_attempts'] / stat['total_attempts']) * 100, 1)
            else:
                stat['correct_rate'] = 0

        # 获取学生总数（排除管理员）
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE username != 'admin'")
        total_students_result = cursor.fetchone()
        total_students = total_students_result['total'] if total_students_result else 0

        # 汇总总用时和分布
        cursor.execute("""
            WITH attempt_summary AS (
                SELECT
                    ur.user_id,
                    ur.template_id,
                    ur.attempt_count,
                    COUNT(*) AS total_answers,
                    SUM(CASE WHEN ur.is_correct THEN 1 ELSE 0 END) AS correct_answers,
                    MAX(ur.time_taken) AS time_taken
                FROM user_responses ur
                JOIN users u ON ur.user_id = u.id
                WHERE u.username != 'admin'
                GROUP BY ur.user_id, ur.template_id, ur.attempt_count
            )
            SELECT
                COUNT(*) as total_attempts,
                SUM(time_taken) as total_time,
                AVG(time_taken) as avg_time,
                AVG(CASE WHEN correct_answers = total_answers THEN time_taken ELSE NULL END) as avg_correct_time
            FROM attempt_summary
        """)
        overall_stats = cursor.fetchone() or {}
        overall_stats.setdefault('total_attempts', 0)
        overall_stats.setdefault('total_time', 0)
        overall_stats.setdefault('avg_time', 0)
        overall_stats.setdefault('avg_correct_time', 0)

        cursor.execute("""
            WITH attempt_summary AS (
                SELECT
                    ur.user_id,
                    ur.template_id,
                    ur.attempt_count,
                    HOUR(MAX(ur.response_time)) as hour_slot
                FROM user_responses ur
                JOIN users u ON ur.user_id = u.id
                WHERE u.username != 'admin'
                GROUP BY ur.user_id, ur.template_id, ur.attempt_count
            )
            SELECT hour_slot, COUNT(*) as attempts
            FROM attempt_summary
            GROUP BY hour_slot
            ORDER BY hour_slot
        """)
        time_distribution = cursor.fetchall()

        cursor.execute("""
            SELECT error_type, COUNT(*) as count
            FROM user_responses ur
            JOIN users u ON ur.user_id = u.id
            WHERE u.username != 'admin' AND ur.is_correct = FALSE
            GROUP BY error_type
            ORDER BY count DESC
        """)
        error_breakdown = cursor.fetchall()

        return render_template('admin_all_problems_stats.html',
                               problem_stats=problem_stats,
                               total_students=total_students,
                               overall_stats=overall_stats,
                               time_distribution=time_distribution,
                               error_breakdown=error_breakdown,
                               username=session['username'])

    except Exception as e:
        print(f"获取题目统计失败: {str(e)}")
        import traceback
        print(f"详细错误: {traceback.format_exc()}")
        flash(f'获取题目统计失败: {str(e)}', 'danger')
        return redirect(url_for('admin_dashboard'))
    finally:
        cursor.close()
        conn.close()


def is_mobile_device():
    """检测是否为移动设备"""
    user_agent = request.headers.get('User-Agent', '').lower()
    mobile_pattern = re.compile(r'mobile|android|webos|iphone|ipad|ipod|blackberry|windows phone')
    return bool(mobile_pattern.search(user_agent))


def is_touch_device():
    """检测是否为触摸设备（简化版）"""
    user_agent = request.headers.get('User-Agent', '').lower()
    touch_pattern = re.compile(r'mobile|android|iphone|ipad|ipod')
    return bool(touch_pattern.search(user_agent))


@app.context_processor
def inject_device_status():
    """向所有模板注入设备状态"""
    return {
        'is_mobile': is_mobile_device(),
        'is_touch': is_touch_device()
    }


@app.route('/api/user/completion_status')
@login_required
def api_user_completion_status():
    """获取用户所有题目的完成状态"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 获取所有题目模板
        cursor.execute("SELECT id FROM problem_templates ORDER BY id")
        templates = cursor.fetchall()

        completion_status = {}

        for template in templates:
            template_id = template['id']
            # 检查该题目是否已完成（有正确答题记录）
            completion_status[template_id] = has_full_correct_attempt(cursor, session['user_id'], template_id)

        cursor.close()
        conn.close()

        return jsonify({
            'success': True,
            'completion_status': completion_status
        })

    except Exception as e:
        print(f"获取完成状态失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取完成状态失败: {str(e)}'
        })


# 图片管理功能
@app.route('/admin/image_manager')
@login_required
def admin_image_manager():
    """图片管理页面"""
    if session.get('username') != 'admin':
        flash('权限不足', 'danger')
        return redirect(url_for('dashboard'))

    import os
    from datetime import datetime

    images = []
    images_path = os.path.join(app.root_path, 'static', 'images')

    if os.path.exists(images_path):
        for filename in os.listdir(images_path):
            if allowed_file(filename):
                file_path = os.path.join(images_path, filename)
                file_stat = os.stat(file_path)
                images.append({
                    'filename': filename,
                    'size': round(file_stat.st_size / 1024, 1),  # KB
                    'modified': datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                })

    return render_template('admin_image_manager.html', images=images)


@app.route('/admin/delete_image/<filename>')
@login_required
def admin_delete_image(filename):
    """删除图片"""
    if session.get('username') != 'admin':
        flash('权限不足', 'danger')
        return redirect(url_for('dashboard'))

    import os
    from werkzeug.utils import secure_filename

    # 安全检查
    filename = secure_filename(filename)
    image_path = os.path.join(app.root_path, 'static', 'images', filename)

    if os.path.exists(image_path):
        try:
            # 检查是否有题目在使用这个图片
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT id, template_name FROM problem_templates WHERE image_filename = %s", (filename,))
            using_templates = cursor.fetchall()
            cursor.close()
            conn.close()

            if using_templates:
                template_names = [t['template_name'] for t in using_templates]
                flash(f'无法删除图片，以下题目正在使用：{", ".join(template_names)}', 'danger')
            else:
                os.remove(image_path)
                flash('图片删除成功！', 'success')
        except Exception as e:
            print(f"删除图片失败: {str(e)}")
            flash(f'删除图片失败: {str(e)}', 'danger')
    else:
        flash('图片不存在', 'danger')

    return redirect(url_for('admin_image_manager'))


@app.route('/health')
def health_check():
    """健康检查端点"""
    try:
        # 检查数据库连接
        conn = get_db_connection()
        if conn and conn.is_connected():
            conn.close()
            return jsonify({'status': 'healthy', 'database': 'connected'})
        else:
            return jsonify({'status': 'unhealthy', 'database': 'disconnected'}), 500
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500


@app.route('/api/exam/status')
@login_required
def exam_system_status():
    """考试系统状态监控"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 获取系统统计
    cursor.execute("SELECT COUNT(*) as active_users FROM users WHERE completed_all = FALSE")
    active_users = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) as total_attempts FROM user_responses WHERE DATE(response_time) = CURDATE()")
    today_attempts = cursor.fetchone()

    cursor.close()
    conn.close()

    return jsonify({
        'active_users': active_users['active_users'],
        'today_attempts': today_attempts['total_attempts'],
        'server_time': datetime.now().isoformat(),
        'status': 'operational'
    })


if __name__ == '__main__':
    # 确保图片目录存在
    os.makedirs('static/images', exist_ok=True)


    # 初始化数据库
    initialize_database()

    # 确保默认图片存在
    ensure_default_images()

    # 创建管理员用户
    create_admin_user()

    # 修复可能存在的表结构问题
    repair_database()

    # 运行数据库诊断
    print("运行数据库诊断...")
    diagnose_database_issue()

    # 验证图片一致性
    print("验证图片一致性...")
    images_ok = verify_image_consistency()
    if not images_ok:
        print("⚠️ 警告: 部分图片文件缺失，请检查以上列表")

    prewarm_flag = os.getenv('PREWARM') == '1' or os.getenv('PORT') == '5000'
    if prewarm_flag:
        prewarm_pools()
    else:
        print("[PREWARM] 跳过预热，未满足 PREWARM 或端口条件")

    app.run(host='0.0.0.0', port=5000, debug=False)
