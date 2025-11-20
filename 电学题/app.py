import traceback
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import mysql.connector
import random
import sympy as sp
import time
import os
import re
from functools import wraps
from math import pi, log

app = Flask(__name__, template_folder='templates',static_folder='static',static_url_path='/static')
app.secret_key = 'your_secret_key_here'

# 数据库配置
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '123456',
    'database': 'physics_new2'
}


def get_db_connection():
    """获取数据库连接"""
    try:
        conn = mysql.connector.connect(**db_config)
        return conn
    except mysql.connector.Error as err:
        print(f"数据库连接失败：{err}")
        return None


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
    """判断答案是否正确（允许1%误差）"""
    print(f"[DEBUG is_correct] 用户答案: {user_answer}, 正确答案: {correct_answer}")

    # 处理None值
    if user_answer is None or correct_answer is None:
        print(f"[DEBUG is_correct] 答案为空，返回False")
        return False

    if correct_answer == 0:
        result = user_answer == 0
        print(f"[DEBUG is_correct] 正确答案为0，比较结果: {result}")
        return result

    tolerance = abs(correct_answer) * 0.01  # 1%容错
    difference = abs(user_answer - correct_answer)
    result = difference <= tolerance

    print(f"[DEBUG is_correct] 容错范围: ±{tolerance:.6f}")
    print(f"[DEBUG is_correct] 实际差异: {difference:.6f}")
    print(f"[DEBUG is_correct] 是否在容错范围内: {result}")

    return result


def generate_problem_from_template(template_id):
    """从模板生成具体问题"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM problem_templates WHERE id = %s", (template_id,))
    template = cursor.fetchone()
    cursor.close()
    conn.close()

    if not template:
        return None

    # 解析变量
    variables = [v.strip() for v in template['variables'].split(',')] if template['variables'] else []
    var_values = {}

    # 为每个变量生成随机值
    for var in variables:

        if var == 'r' or var == 'a' or var == 'd' or var == 'x' or var == 'AC' or var == 'L':
            var_values[var] = random.randint(5, 20)
        elif var == 'R':
            var_values[var] = random.randint(5, 20)
        elif var == 'i':
            var_values[var] = round(random.uniform(0.01, 0.05), 3)
        elif var == 'N':
            var_values[var] = random.randint(50, 200)
        elif var == 'B' or var == 'B0':
            var_values[var] = round(random.uniform(0.1, 0.5), 2)
        elif var == 'A':
            var_values[var] = round(random.uniform(0.01, 0.05), 3)
        elif var == 'omega':
            var_values[var] = random.randint(10, 50)
        elif var == 'l':
            var_values[var] = round(random.uniform(0.1, 0.5), 2)
        elif var == 'v':
            var_values[var] = round(random.uniform(1, 5), 1)
        elif var == 'dBdt' or var == 'alpha':
            var_values[var] = round(random.uniform(0.1, 1.0), 1)
        elif var == 'I':
            var_values[var] = random.randint(1, 5)
        elif var == 'm':
            var_values[var] = round(random.uniform(0.1, 0.5), 2)
        elif var == 'rho':
            var_values[var] = round(random.uniform(1.7e-8, 2.0e-8), 2)
        elif var == 'density':
            var_values[var] = 8960
        elif var == 'L':
            var_values[var] = 400  # 固定长度
        elif var == 'h':
            var_values[var] = 4  # 固定高度
        elif var == 'v':
            var_values[var] = random.randint(300, 400)  # 速度300-400km/h
        elif var == 'B':
            var_values[var] = random.randint(35, 45)
        else:
            var_values[var] = random.randint(2, 4)


    # 使用正则表达式格式化模板
    import re
    problem_text = template['problem_text']

    # 第一步：替换所有变量
    pattern1 = r'\{\{\s*problem\.var_values\.(\w+)\s*\}\}'
    pattern2 = r'\{\s*(\w+)\s*\}'  # 备用模式

    def replace_var(match):
        var_name = match.group(1)
        full_match = match.group(0)

        # 排除在数学公式、单位符号和文本中的变量名
        if '\\text' in full_match or '\\,' in full_match or '\\mathrm' in full_match:
            return match.group(0)

        unit_indicators = ['\\text', '\\,', '\\mathrm', '\\unit']
        if any(indicator in full_match for indicator in unit_indicators):
            return match.group(0)

        if var_name in var_values:
            return str(var_values[var_name])
        else:
            return match.group(0)

    problem_content = re.sub(pattern1, replace_var, problem_text)
    problem_content = re.sub(pattern2, replace_var, problem_content)

    # 第二步：关键修复 - 手动替换所有图片URL
    problem_content = problem_content.replace(
        "src=\"{{ url_for('static', filename='images/problem3.png') }}\"",
        "src=\"/static/images/problem3.png\""
    )
    problem_content = problem_content.replace(
        "src=\"{{ url_for('static', filename='images/problem4.png') }}\"",
        "src=\"/static/images/problem4.png\""
    )
    problem_content = problem_content.replace(
        "src=\"{{ url_for('static', filename='images/problem5.png') }}\"",
        "src=\"/static/images/problem5.png\""
    )
    problem_content = problem_content.replace(
        "src=\"{{ url_for('static', filename='images/problem7.png') }}\"",
        "src=\"/static/images/problem7.png\""
    )
    problem_content = problem_content.replace(
        "src=\"{{ url_for('static', filename='images/problem8.png') }}\"",
        "src=\"/static/images/problem8.png\""
    )

    # 调试输出
    print(f"=== 问题生成调试 ===")
    print(f"模板ID: {template_id}")
    print(f"是否包含图片URL: {'/static/images/' in problem_content}")
    print(f"问题内容片段: {problem_content[:500]}")

    # 计算正确答案
    x, t, h = sp.symbols('x t h')
    local_vars = {
        'x': x, 't': t, 'h': h, 'sp': sp, 'sqrt': sp.sqrt, 'exp': sp.exp,
        'integrate': sp.integrate, 'pi': pi, 'log': log, 'sin': sp.sin, 'cos': sp.cos
    }
    local_vars.update(var_values)

    try:
        correct_answer = eval(template['solution_formula'], {}, local_vars)
        if isinstance(correct_answer, tuple):
            correct_answers = [float(a.evalf()) if hasattr(a, 'evalf') else float(a) for a in correct_answer]
        else:
            correct_answers = [
                float(correct_answer.evalf()) if hasattr(correct_answer, 'evalf') else float(correct_answer)]

        answer_count = template.get('answer_count', 1)
        if len(correct_answers) != answer_count:
            correct_answers = [correct_answers[0]] * answer_count
    except Exception as e:
        print(f"计算答案失败: {e}")
        answer_count = template.get('answer_count', 1)
        correct_answers = [0.0] * answer_count

    return {
        'problem_text': problem_content,
        'var_values': var_values,
        'correct_answers': correct_answers,
        'template_id': template_id,
        'answer_count': template.get('answer_count', 1),
        'template_name': template['template_name']
    }


def save_user_response(user_id, template_id, problem_text, user_answers, correct_answers, is_correct_list,
                       attempt_count, time_taken):
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

        for i, (user_answer, correct_answer, is_correct) in enumerate(
                zip(user_answers, correct_answers, is_correct_list)):
            try:
                print(
                    f"正在保存答案 {i + 1}: user_answer={user_answer}, correct_answer={correct_answer}, is_correct={is_correct}")

                cursor.execute("""
                    INSERT INTO user_responses 
                    (user_id, template_id, problem_text, user_answer, 
                     correct_answer, is_correct, attempt_count, time_taken, answer_index)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (user_id, template_id, truncated_problem_text, user_answer,
                      correct_answer, is_correct, attempt_count, time_taken, i))

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
    """初始化数据库"""
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

    # 创建问题模板表（如果不存在）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS problem_templates (
        id INT AUTO_INCREMENT PRIMARY KEY,
        template_name VARCHAR(100) NOT NULL,
        problem_text TEXT NOT NULL,
        variables TEXT NOT NULL,
        solution_formula TEXT NOT NULL,
        answer_count INT DEFAULT 1,
        difficulty VARCHAR(20) DEFAULT 'medium'
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

    # 插入电磁学题目模板 - 使用直接图片路径
    templates = [
        # 题目1：闭合圆形线圈的感应电流
        {
            'name': '闭合圆形线圈的感应电流',
            'text': r"""
                <div class="math-formula">
                    <h5>题目描述：</h5>
                    <p>用导线制成一半径为 \( r = {{ problem.var_values.r }} \, \text{cm} \) 的闭合圆形线圈，其电阻 \( R = {{ problem.var_values.R }} \, \Omega \)，均匀磁场垂直于线圈平面。</p>
                    <p>欲使电路中有一稳定的感应电流 \( i = {{ problem.var_values.i }} \, \text{A} \)，求 \( B \) 的变化率 \( \frac{dB}{dt} \)。</p>

                    <div class="alert alert-info mt-3">
                        <h5><i class="bi bi-lightbulb"></i> 解题提示：</h5>
                        <p>法拉第电磁感应定律：\( \varepsilon = -\frac{d\Phi}{dt} \)</p>
                        <p>磁通量：\( \Phi = B \cdot S = B \cdot \pi r^2 \)</p>
                        <p>感应电流：\( i = \frac{\varepsilon}{R} \)</p>
                    </div>
                </div>
            """,
            'variables': 'r,R,i',
            'formula': "i * R / (pi * (r/100)**2)",  # dB/dt = iR/(πr²)
            'answer_count': 1
        },

        {
            'name': '高铁电磁感应问题',
            'text': r"""
        <div class="math-formula">
        <h5>题目描述：</h5>
        <p>中国是目前世界上高速铁路运行里程最长的国家，已知"复兴号"高铁长度为 L = {{ problem.var_values.L }} m，车厢高 h = {{ problem.var_values.h }} m，正常行驶速度 v = {{ problem.var_values.v }} km/h。</p>
        <p>假设地面附近地磁场的水平分量约为 B = {{ problem.var_values.B }} μT，将列车视为一整块导体，只考虑地磁场的水平分量。</p>
        <p>则"复兴号"列车在自西向东正常行驶的过程中，求车头与车尾之间的电势差大小（单位：μV）。</p>

        <div class="alert alert-info mt-3">
            <h5><i class="bi bi-lightbulb"></i> 解题提示：</h5>
            <p>1. 速度单位换算：km/h → m/s</p>
            <p>2. 磁场单位换算：μT → T</p>
            <p>3. 导体在磁场中运动产生的感应电动势：ε = BLv</p>
            <p>4. 最终结果单位转换为微伏(μV)：1 V = 10⁶ μV</p>
        </div>
        </div>
        """,
            'variables': 'L,h,v,B',
            'formula': "B * L * (v / 3.6) ",  # 结果单位改为微伏(μV)
            'answer_count': 1
        },

        # 题目3：等边三角形金属框转动电动势 - 使用直接路径
        {
            'name': '等边三角形金属框转动电动势',
            'text': r"""
                <div class="math-formula">
                    <h5>题目描述：</h5>
                    <div class="text-center mb-3">
                        <img src="/static/images/problem3.png" 
                             alt="等边三角形金属框示意图" class="problem-image img-fluid">
                        <div class="image-caption text-muted">图2：等边三角形金属框转动示意图</div>
                    </div>
                    <p>如图所示，等边三角形的金属框，边长为 \( l = {{ problem.var_values.l }} \, \text{m} \)，放在均匀磁场 \( B = {{ problem.var_values.B }} \, \text{T} \) 中。</p>
                    <p>\( ab \) 边平行于磁感强度 \( B \)，当金属框绕 \( ab \) 边以角速度 \( \omega = {{ problem.var_values.omega }} \, \text{rad/s} \) 转动时：</p>
                    <ol>
                        <li>求 \( bc \) 边上沿 \( bc \) 的电动势</li>
                        <li>求 \( ca \) 边上沿 \( ca \) 的电动势</li>
                        <li>求金属框内的总电动势</li>
                    </ol>
                    <div class="alert alert-info mt-3">
                        <h5><i class="bi bi-lightbulb"></i> 解题提示：</h5>
                        <p>动生电动势：\( \varepsilon = \int (\vec{v} \times \vec{B}) \cdot d\vec{l} \)</p>
                        <p>考虑各边的运动情况和磁场方向</p>
                    </div>
                </div>
            """,
            'variables': 'l,B,omega',
            'formula': "(3/8) * B * omega * l**2, -(3/8) * B * omega * l**2,0",
            'answer_count': 3
        },

        # 题目4：动生电动势与感生电动势 - 使用直接路径
        {
            'name': '动生电动势与感生电动势',
            'text': r"""
                <div class="math-formula">
                    <h5>题目描述：</h5>
                    <div class="text-center mb-3">
                        <img src="/static/images/problem4.png" 
                             alt="导体AC运动示意图" class="problem-image img-fluid">
                        <div class="image-caption text-muted">图3：导体AC在变化磁场中运动示意图</div>
                    </div>
                    <p>导体 \( AC \) 以速度 \( v = {{ problem.var_values.v }} \, \text{m/s} \) 运动。</p>
                    <p>设 \( AC = {{ problem.var_values.AC }} \, \text{cm} \)，均匀磁场随时间的变化率 \( \frac{dB}{dt} = {{ problem.var_values.dBdt }} \, \text{T/s} \)。</p>
                    <p>某一时刻 \( B = {{ problem.var_values.B }} \, \text{T} \)，\( x = {{ problem.var_values.x }} \, \text{cm} \)，求：</p>
                    <ol>
                        <li>这时动生电动势的大小</li>
                        <li>总感应电动势的大小</li>
                        <li>动生电动势随 \( AC \) 运动的变化趋势（增大填1，减小填-1）</li>
                    </ol>
                    <div class="alert alert-info mt-3">
                        <h5><i class="bi bi-lightbulb"></i> 解题提示：</h5>
                        <p>动生电动势：导体切割磁感线产生</p>
                        <p>感生电动势：磁场变化产生</p>
                        <p>总电动势为两者之和</p>
                    </div>
                </div>
            """,
            'variables': 'v,AC,dBdt,B,x',
            'formula': "B * v * (AC/100), (B * v * (AC/100)) + (dBdt * (x/100) * (AC/100)), 1",
            'answer_count': 3
        },

        # 题目5：折形金属导线运动电势差 - 使用直接路径
        {
            'name': '折形金属导线运动电势差',
            'text': r"""
            <div class="math-formula">
                <h5>题目描述：</h5>
                <div class="text-center mb-3">
                    <img src="/static/images/problem5.png" 
                         alt="折形金属导线示意图" class="problem-image img-fluid">
                    <div class="image-caption text-muted">图4：折形金属导线在磁场中运动示意图</div>
                </div>
                <p>\( aOc \) 为一折成 \( 30^\circ \) 角的金属导线（\( aO = Oc = L = {{ problem.var_values.L }} \, \text{m} \)），位于 \( xy \) 平面中。</p>
                <p>其中 \( aO \) 段与 \( x \) 轴夹角为 \( 30^\circ \)，\( Oc \) 段与 \( x \) 轴夹角为 \( 30^\circ \)，两段在 \( O \) 点相接。</p>
                <p>磁感强度为 \( B = {{ problem.var_values.B }} \, \text{T} \) 的匀强磁场垂直于 \( xy \) 平面。</p>
                <ol>
                    <li>当 \( aOc \) 以速度 \( v = {{ problem.var_values.v }} \, \text{m/s} \) 沿 \( x \) 轴正向运动时，导线上 \( a, c \) 两点间电势差 \( U_{ac} \)</li>
                    <li>当 \( aOc \) 以速度 \( v \) 沿 \( y \) 轴正向运动时，判断 \( a, c \) 两点电势高低（a点高填1，c点高填-1）</li>
                </ol>
                <div class="alert alert-info mt-3">
                    <h5><i class="bi bi-lightbulb"></i> 解题提示：</h5>
                    <p>动生电动势公式：\( \varepsilon = \int (\vec{v} \times \vec{B}) \cdot d\vec{l} \)</p>
                    <p>考虑不同运动方向时各段的电动势，注意30度角的影响</p>
                    <p>总电势差为各段电动势的代数和</p>
                </div>
            </div>
        """,
            'variables': 'L,B,v',
            'formula': "B * v * L /2 , -1",
            'answer_count': 2
        },

        # 题目6：磁铁插入线圈的感应现象
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

                    <div class="alert alert-info mt-3">
                        <h5><i class="bi bi-lightbulb"></i> 解题提示：</h5>
                        <p>感应电荷量：\( q = \frac{\Delta\Phi}{R} \)</p>
                        <p>做功与功率和时间有关</p>
                    </div>
                </div>
            """,
            'variables': '',
            'formula': "1, 0",  # 第一个答案用1表示相同，第二个用0表示不同
            'answer_count': 2
        },

        # 题目7：双圆线圈的感应电流 - 使用直接路径
        {
            'name': '双圆线圈的感应电流',
            'text': r"""
                <div class="math-formula">
                    <h5>题目描述：</h5>
                    <div class="text-center mb-3">
                        <img src="/static/images/problem7.png" 
                             alt="双圆线圈示意图" class="problem-image img-fluid">
                        <div class="image-caption text-muted">图5：双圆线圈在变化磁场中示意图</div>
                    </div>
                    <p>电阻为 \( R = {{ problem.var_values.R }} \, \Omega \) 的闭合线圈折成半径分别为 \( a = {{ problem.var_values.a }} \, \text{cm} \) 和 \( 2a \) 的两个圆，</p>
                    <p>将其置于与两圆平面垂直的匀强磁场内，磁感应强度按 \( B = B_0 \sin(\omega t) \) 的规律变化。</p>
                    <p>已知 \( B_0 = {{ problem.var_values.B0 }} \, \text{T} \)，\( \omega = {{ problem.var_values.omega }} \, \text{rad/s} \)，求线圈中感应电流的最大值。</p>
                    <div class="alert alert-info mt-3">
                        <h5><i class="bi bi-lightbulb"></i> 解题提示：</h5>
                        <p>法拉第电磁感应定律</p>
                        <p>总电动势为两个线圈电动势之和</p>
                        <p>感应电流最大值</p>
                    </div>
                </div>
            """,
            'variables': 'R,a,B0,omega',
            'formula': "(pi * omega * B0 / R) * ((a/100)**2 + (2*a/100)**2)",
            'answer_count': 1
        },

        # 题目8：铜制回路的感应电流
        {
            'name': '铜制回路的感应电流',
            'text': r"""
            <div class="math-formula">
                <h5>题目描述：</h5>
                <p>有一磁感强度为 \( B \) 的均匀磁场，以恒定的变化率 \( \frac{dB}{dt} = {{ problem.var_values.dBdt }} \, \text{T/s} \) 在变化。</p>
                <p>把一块质量为 \( m = {{ problem.var_values.m }} \, \text{kg} \) 的铜，拉成截面半径为 \( r = {{ problem.var_values.r }} \, \text{m} \) 的导线，</p>
                <p>并用它做成一个半径为 \( R = {{ problem.var_values.R }} \, \text{m} \) 的圆形回路。圆形回路的平面与磁感强度 \( B \) 垂直。</p>
                <p>试求这回路中的感应电流。</p>
                <p>其中铜的电阻率 \( \rho = 1.7 \times 10^{-7} \, \Omega\cdot\text{m} \)，铜的密度 \( d = {{ problem.var_values.density }} \, \text{kg/m}^3 \)。</p>

                <div class="alert alert-info mt-3">
                    <h5><i class="bi bi-lightbulb"></i> 解题提示：</h5>
                    <p>导线长度与质量关系</p>
                    <p>回路电阻计算</p>
                    <p>感应电动势与电流关系</p>
                </div>
            </div>
        """,
            'variables': 'dBdt,m,r,R,density',  # 移除了rho，因为现在是固定值
            'formula': "(m * dBdt) / (4 * pi * 1.7e-7 * density)",  # I = (m dB/dt)/(4πρd)，ρ固定为1.7e-7
            'answer_count': 1
        }
    ]

    # 插入模板到数据库
    for template in templates:
        cursor.execute("SELECT id FROM problem_templates WHERE template_name = %s", (template['name'],))
        if not cursor.fetchone():
            cursor.execute("""
                   INSERT INTO problem_templates (template_name, problem_text, variables, solution_formula, answer_count)
                   VALUES (%s, %s, %s, %s, %s)
               """, (
                template['name'],
                template['text'],
                template['variables'],
                template['formula'],
                template['answer_count']
            ))

    conn.commit()
    cursor.close()
    conn.close()


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


def update_existing_templates():
    """更新现有模板的图片URL"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 更新所有题目的图片URL
    updates = [
        (2, "src=\"{{ url_for('static', filename='images/problem2.png') }}\"", 'src="/static/images/problem2.png"'),
        (3, "src=\"{{ url_for('static', filename='images/problem3.png') }}\"", 'src="/static/images/problem3.png"'),
        (4, "src=\"{{ url_for('static', filename='images/problem4.png') }}\"", 'src="/static/images/problem4.png"'),
        (5, "src=\"{{ url_for('static', filename='images/problem5.png') }}\"", 'src="/static/images/problem5.png"'),
        (7, "src=\"{{ url_for('static', filename='images/problem7.png') }}\"", 'src="/static/images/problem7.png"'),
        (8, "src=\"{{ url_for('static', filename='images/problem8.png') }}\"", 'src="/static/images/problem8.png"')
    ]

    for problem_id, old_url, new_url in updates:
        cursor.execute(f"""
            UPDATE problem_templates 
            SET problem_text = REPLACE(problem_text, %s, %s)
            WHERE id = %s
        """, (old_url, new_url, problem_id))
        print(f"更新题目 {problem_id} 的图片URL")

    conn.commit()
    cursor.close()
    conn.close()
    print("所有模板图片URL更新完成")

def update_user_completion_status(user_id):
    """更新用户完成状态"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 检查是否完成所有题目
        cursor.execute("""
            SELECT COUNT(DISTINCT template_id) as completed_count 
            FROM user_responses 
            WHERE user_id = %s AND is_correct = TRUE
        """, (user_id,))
        completed_count = cursor.fetchone()['completed_count']

        # 计算总分和总用时
        cursor.execute("""
            SELECT 
                COUNT(*) as total_score,
                SUM(time_taken) as total_time
            FROM user_responses 
            WHERE user_id = %s AND is_correct = TRUE
        """, (user_id,))
        stats = cursor.fetchone()

        completed_all = completed_count >= 9  # 现在有9道题

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

        # 确定当前应该做的题目
        current_problem = 1
        if not completed_all:
            for problem_id in range(1, 10):  # 现在有9道题
                cursor.execute("""
                    SELECT COUNT(*) as count FROM user_responses 
                    WHERE user_id = %s AND template_id = %s AND is_correct = TRUE
                """, (session['user_id'], problem_id))
                result = cursor.fetchone()
                if result['count'] == 0:
                    current_problem = problem_id
                    break

        # 重置尝试次数
        session.pop('attempt_count', None)
        session.pop('current_problem', None)

        return render_template('dashboard.html',
                               username=session['username'],
                               current_problem=current_problem,
                               completed_count=completed_count,
                               completed_all=completed_all,
                               total_problems=8)  # 总题目数设为8，与模板一致

    except mysql.connector.Error as err:
        print(f"数据库查询错误: {err}")
        flash('数据库查询错误', 'danger')
        return redirect(url_for('home'))
    finally:
        cursor.close()
        conn.close()

@app.route('/problem/<int:problem_id>', methods=['GET', 'POST'])
@login_required
def problem(problem_id):
    """处理问题展示和答案提交 - 修复变量引用错误"""
    print(f"\n=== 问题页面开始 ===")
    print(f"问题ID: {problem_id}")
    print(f"请求方法: {request.method}")

    # 验证题目ID范围
    if problem_id < 1 or problem_id > 9:  # 现在有9道题
        flash('无效的题目编号', 'danger')
        return redirect(url_for('dashboard'))

    # 检查前置题目是否完成
    if problem_id > 1:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM user_responses
            WHERE user_id = %s AND template_id = %s AND is_correct = TRUE
        """, (session['user_id'], problem_id - 1))
        if cursor.fetchone()[0] == 0:
            flash(f'请先完成第{problem_id - 1}题!', 'danger')
            return redirect(url_for('problem', problem_id=problem_id - 1))
        cursor.close()
        conn.close()

    # 初始化或获取题目数据
    if 'current_problem' not in session or session['current_problem']['id'] != problem_id:
        print("生成新题目...")
        problem_data = generate_problem_from_template(problem_id)
        if not problem_data:
            flash('题目生成失败', 'danger')
            return redirect(url_for('dashboard'))

        session['current_problem'] = {
            'id': problem_id,
            'data': problem_data,
            'attempt_count': 0,
            'answered_correctly': False,
            'start_time': time.time()
        }
        print(f"新题目生成成功，答案数量: {problem_data.get('answer_count', 1)}")

    # 获取当前问题数据
    problem_data = session['current_problem']['data']
    attempt_count = session['current_problem']['attempt_count']
    start_time = session['current_problem'].get('start_time', time.time())
    answer_count = problem_data.get('answer_count', 1)

    print(f"当前问题数据: {problem_data.keys()}")
    print(f"尝试次数: {attempt_count}")
    print(f"答案数量: {answer_count}")

    # 处理答案提交
    if request.method == 'POST':
        print("处理POST请求...")
        try:
            # 计算答题用时（秒）
            time_taken = round(time.time() - start_time, 2)
            print(f"答题用时: {time_taken}秒")

            user_id = session['user_id']
            template_id = problem_data['template_id']
            problem_text = problem_data['problem_text']
            correct_answers = problem_data['correct_answers']

            print(f"用户ID: {user_id}")
            print(f"模板ID: {template_id}")
            print(f"正确答案: {correct_answers}")
            print(f"表单数据: {request.form}")

            # 处理不同题型的答案
            if answer_count > 1:
                print(f"多答案题目处理，期望{answer_count}个答案")
                user_answers = []
                is_correct_list = []
                all_correct = True

                # 获取所有答案
                for i in range(answer_count):
                    answer_key = f'answer{i + 1}' if answer_count > 1 else 'answer'
                    user_answer = float(request.form.get(answer_key, 0))
                    user_answers.append(user_answer)

                    # 验证答案
                    if i < len(correct_answers):
                        correct = is_correct(user_answer, correct_answers[i])
                        is_correct_list.append(correct)
                        if not correct:
                            all_correct = False
                        print(
                            f"答案{i + 1}: 用户={user_answer}, 正确={correct_answers[i]}, 结果={'正确' if correct else '错误'}")
                    else:
                        print(f"❌ 答案{i + 1}超出正确答案范围")
                        is_correct_list.append(False)
                        all_correct = False

                # 保存答题记录
                save_success = save_user_response(
                    user_id, template_id, problem_text, user_answers,
                    correct_answers, is_correct_list, attempt_count + 1, time_taken
                )

                if all_correct:
                    session['current_problem']['answered_correctly'] = True
                    session['current_problem']['attempt_count'] = 0
                    flash('回答正确！即将进入下一题', 'success')
                    next_problem = problem_id + 1
                    if next_problem <= 9:  # 现在有9道题
                        return redirect(url_for('problem', problem_id=next_problem))
                    else:
                        flash('恭喜你完成所有题目！', 'success')
                        return redirect(url_for('dashboard'))
                else:
                    session['current_problem']['attempt_count'] += 1

                    # 答错时生成新题目
                    attempts_remaining = 3 - session['current_problem']['attempt_count']
                    if attempts_remaining > 0:
                        new_problem_data = generate_problem_from_template(problem_id)
                        if new_problem_data:
                            session['current_problem']['data'] = new_problem_data
                            session['current_problem']['start_time'] = time.time()

                            # 生成正确答案消息
                            correct_parts = []
                            for i, correct_answer in enumerate(correct_answers):
                                correct_parts.append(f"答案{i + 1} = {correct_answer:.2f}")
                            correct_message = "正确答案: " + ", ".join(correct_parts)

                            flash(f'答案不正确！{correct_message}。已为您生成新题目，请重新作答。', 'warning')
                        else:
                            flash('答案不正确！题目刷新失败，请重试。', 'warning')
                    else:
                        correct_parts = []
                        for i, correct_answer in enumerate(correct_answers):
                            correct_parts.append(f"答案{i + 1} = {correct_answer:.2f}")
                        correct_message = "正确答案: " + ", ".join(correct_parts)
                        flash(f'答案不正确！{correct_message}。尝试次数已用完！', 'danger')

                    if not save_success:
                        flash('部分答题记录保存失败', 'warning')

            else:
                # 单答案题目处理 - 修复变量名冲突
                print("单答案题目处理")
                user_answer = float(request.form.get('answer', 0))

                # 修复：使用不同的变量名，避免与函数名冲突
                answer_correct = False
                if correct_answers and len(correct_answers) > 0:
                    answer_correct = is_correct(user_answer, correct_answers[0])
                else:
                    print("❌ 正确答案列表为空")
                    flash('题目数据错误，请刷新页面重试', 'danger')
                    return redirect(url_for('problem', problem_id=problem_id))

                print(
                    f"用户答案: {user_answer}, 正确答案: {correct_answers[0]}, 结果: {'正确' if answer_correct else '错误'}")

                # 保存答题记录
                save_success = save_user_response(
                    user_id, template_id, problem_text, [user_answer],
                    correct_answers, [answer_correct], attempt_count + 1, time_taken
                )

                if answer_correct:
                    session['current_problem']['answered_correctly'] = True
                    session['current_problem']['attempt_count'] = 0
                    flash('回答正确！', 'success')
                    next_problem = problem_id + 1
                    if next_problem <= 9:  # 现在有9道题
                        return redirect(url_for('problem', problem_id=next_problem))
                    else:
                        flash('恭喜你完成所有题目！', 'success')
                        return redirect(url_for('dashboard'))
                else:
                    session['current_problem']['attempt_count'] += 1

                    # 答错时生成新题目
                    attempts_remaining = 3 - session['current_problem']['attempt_count']
                    if attempts_remaining > 0:
                        new_problem_data = generate_problem_from_template(problem_id)
                        if new_problem_data:
                            session['current_problem']['data'] = new_problem_data
                            session['current_problem']['start_time'] = time.time()
                            flash(f'答案不正确！正确答案: {correct_answers[0]:.2f}。已为您生成新题目，请重新作答。',
                                  'warning')
                        else:
                            flash(f'答案不正确！正确答案: {correct_answers[0]:.2f}。题目刷新失败，请重试。', 'warning')
                    else:
                        flash(f'答案不正确！正确答案: {correct_answers[0]:.2f}。尝试次数已用完！', 'danger')

                    if not save_success:
                        flash('答题记录保存失败', 'warning')

            # 处理尝试次数限制
            attempt_count = session['current_problem']['attempt_count']
            if attempt_count >= 3:
                print(f"尝试次数已用完")
                session.pop('current_problem', None)
                flash('很遗憾，三次尝试均失败，请从首页重新开始！', 'danger')
                return redirect(url_for('dashboard'))

            # 重置计时器
            session['current_problem']['start_time'] = time.time()

        except ValueError as e:
            print(f"❌ 数值转换错误: {e}")
            flash('请输入有效的数字', 'danger')
        except Exception as e:
            print(f"❌ 处理答案时发生错误: {str(e)}")
            import traceback
            print(f"详细错误信息:\n{traceback.format_exc()}")
            flash('处理答案时发生错误，请重试', 'danger')

    # 检查是否已经正确回答过（防止通过URL跳过）
    if session['current_problem'].get('answered_correctly', False):
        next_problem = problem_id + 1
        if next_problem <= 9:  # 现在有9道题
            return redirect(url_for('problem', problem_id=next_problem))
        else:
            return redirect(url_for('dashboard'))

    # 渲染问题模板
    template_file = f'problem{problem_id}.html'
    print(f"渲染模板: {template_file}")
    print(f"=== 问题页面结束 ===\n")

    return render_template(template_file,
                           problem=problem_data,
                           username=session['username'],
                           attempt_count=attempt_count)


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
            SELECT 
                COUNT(*) as total_count,
                SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct_count,
                AVG(time_taken) as avg_time
            FROM user_responses 
            WHERE user_id = %s
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
            SELECT 
                t.template_name,
                COUNT(*) as total,
                SUM(CASE WHEN r.is_correct THEN 1 ELSE 0 END) as correct,
                AVG(r.time_taken) as avg_time
            FROM user_responses r
            JOIN problem_templates t ON r.template_id = t.id
            WHERE r.user_id = %s
            GROUP BY t.id, t.template_name
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


@app.route('/history')
@login_required
def history():
    """获取答题历史（带完整错误处理）"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 修复SQL查询
        cursor.execute("""
            SELECT 
                r.id,
                t.template_name,
                r.problem_text,
                r.user_answer,
                r.correct_answer,
                r.is_correct,
                r.attempt_count,
                DATE_FORMAT(r.response_time, '%Y-%m-%d %H:%i:%s') as formatted_time,
                r.time_taken,
                t.id as template_id
            FROM user_responses r
            JOIN problem_templates t ON r.template_id = t.id
            WHERE r.user_id = %s
            ORDER BY r.response_time DESC
        """, (session['user_id'],))

        responses = cursor.fetchall()

        # 获取统计信息 - 修复字段名
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct_count,
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

        print(f"[DEBUG] 答题记录数量: {len(responses)}")
        print(f"[DEBUG] 统计信息: {stats}")

        return render_template('history.html',
                               responses=responses,
                               stats=stats,
                               username=session['username'])

    except Exception as e:
        print(f"[系统错误] 获取答题历史失败: {str(e)}")
        import traceback
        print(f"[详细错误] {traceback.format_exc()}")
        flash('获取答题历史失败，请稍后再试', 'danger')
        return render_template('history.html',
                               responses=[],
                               stats=None,
                               username=session['username'])
    finally:
        if conn:
            conn.close()

@app.route('/all_problems')
@login_required
def all_problems():
    """展示所有题目列表"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 获取所有题目模板
        cursor.execute(
            "SELECT id, template_name, problem_text, variables, difficulty FROM problem_templates ORDER BY id")
        templates = cursor.fetchall()

        problems = []

        for template in templates:
            # 生成变量值
            variables = [v.strip() for v in template['variables'].split(',')] if template['variables'] else []
            var_values = {}

            # 生成随机变量值
            for var in variables:
                if var == 'r' or var == 'a' or var == 'd' or var == 'x' or var == 'AC' or var == 'L':
                    var_values[var] = random.randint(5, 20)
                elif var == 'R':
                    var_values[var] = random.randint(5, 20)
                elif var == 'i':
                    var_values[var] = round(random.uniform(0.01, 0.05), 3)
                elif var == 'N':
                    var_values[var] = random.randint(50, 200)
                elif var == 'B' or var == 'B0':
                    var_values[var] = round(random.uniform(0.1, 0.5), 2)
                elif var == 'A':
                    var_values[var] = round(random.uniform(0.01, 0.05), 3)
                elif var == 'omega':
                    var_values[var] = random.randint(10, 50)
                elif var == 'l':
                    var_values[var] = round(random.uniform(0.1, 0.5), 2)
                elif var == 'v':
                    var_values[var] = round(random.uniform(1, 5), 1)
                elif var == 'dBdt' or var == 'alpha':
                    var_values[var] = round(random.uniform(0.1, 1.0), 1)
                elif var == 'I':
                    var_values[var] = random.randint(1, 5)
                elif var == 'm':
                    var_values[var] = round(random.uniform(0.1, 0.5), 2)
                elif var == 'rho':
                    var_values[var] = round(random.uniform(1.7e-8, 2.0e-8), 2)
                elif var == 'density':
                    var_values[var] = 8960
                else:
                    var_values[var] = random.randint(2, 4)

            # 使用正则表达式格式化模板
            import re
            problem_text = template['problem_text']

            pattern1 = r'\{\{\s*problem\.var_values\.(\w+)\s*\}\}'
            pattern2 = r'\{\s*(\w+)\s*\}'  # 备用模式

            def replace_var(match):
                var_name = match.group(1)
                if var_name in var_values:
                    return str(var_values[var_name])
                else:
                    return match.group(0)

            problem_content = re.sub(pattern1, replace_var, problem_text)
            problem_content = re.sub(pattern2, replace_var, problem_content)

            # 检查题目是否已完成
            cursor.execute("""
                SELECT COUNT(*) as completed 
                FROM user_responses 
                WHERE user_id = %s AND template_id = %s AND is_correct = TRUE
            """, (session['user_id'], template['id']))
            completed = cursor.fetchone()['completed'] > 0

            # 获取答题统计（如果已完成）
            stats = None
            if completed:
                cursor.execute("""
                    SELECT time_taken, attempt_count, 
                           CASE WHEN is_correct THEN 100 ELSE 0 END as score
                    FROM user_responses 
                    WHERE user_id = %s AND template_id = %s AND is_correct = TRUE
                    ORDER BY response_time DESC LIMIT 1
                """, (session['user_id'], template['id']))
                stats_result = cursor.fetchone()
                if stats_result:
                    stats = {
                        'time_taken': round(stats_result['time_taken'], 1),
                        'attempt_count': stats_result['attempt_count'],
                        'score': stats_result['score']
                    }

            problems.append({
                'id': template['id'],
                'name': template['template_name'],
                'content': problem_content,
                'var_values': var_values,
                'completed': completed,
                'stats': stats,
                'difficulty': template.get('difficulty', 'medium')
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
        # 重新生成题目数据
        problem_data = generate_problem_from_template(problem_id)

        if not problem_data:
            return jsonify({'success': False, 'message': '题目生成失败'})

        # 更新session中的题目数据
        if 'current_problem' in session and session['current_problem']['id'] == problem_id:
            session['current_problem']['data'] = problem_data
            session['current_problem']['attempt_count'] = 0
            session['current_problem']['answered_correctly'] = False
            session['current_problem']['start_time'] = time.time()

        return jsonify({'success': True, 'message': '题目刷新成功'})
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


@app.route('/problem_ajax/<int:problem_id>')
@login_required
def problem_ajax(problem_id):
    """支持Ajax的问题页面 - 完整实现"""
    print(f"\n=== Ajax问题页面开始 ===")
    print(f"问题ID: {problem_id}")

    # 1. 验证题目ID
    if problem_id < 1 or problem_id > 9:  # 现在有9道题
        flash('无效的题目编号', 'danger')
        return redirect(url_for('dashboard'))

    # 2. 检查前置题目（如果需要）
    if problem_id > 1:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM user_responses
            WHERE user_id = %s AND template_id = %s AND is_correct = TRUE
        """, (session['user_id'], problem_id - 1))
        if cursor.fetchone()[0] == 0:
            flash(f'请先完成第{problem_id - 1}题!', 'danger')
            return redirect(url_for('problem_ajax', problem_id=problem_id - 1))
        cursor.close()
        conn.close()

    # 3. 初始化或获取题目数据
    if 'current_problem' not in session or session['current_problem']['id'] != problem_id:
        print("生成新题目...")
        problem_data = generate_problem_from_template(problem_id)
        if not problem_data:
            flash('题目生成失败', 'danger')
            return redirect(url_for('dashboard'))

        session['current_problem'] = {
            'id': problem_id,
            'data': problem_data,
            'total_attempts': 0,  # 改为累计尝试次数
            'answered_correctly': False,
            'start_time': time.time()
        }
        print(f"新题目生成成功，答案数量: {problem_data.get('answer_count', 1)}")

    # 4. 检查是否已经完成
    if session['current_problem'].get('answered_correctly', False):
        next_problem = problem_id + 1
        if next_problem <= 9:  # 现在有9道题
            return redirect(url_for('problem_ajax', problem_id=next_problem))
        else:
            return redirect(url_for('dashboard'))

    # 5. 渲染Ajax模板
    problem_data = session['current_problem']['data']
    total_attempts = session['current_problem']['total_attempts']
    answer_count = problem_data.get('answer_count', 1)

    print(f"渲染Ajax模板，问题ID: {problem_id}, 答案数量: {answer_count}, 累计尝试: {total_attempts}")
    print(f"当前题目参数: {problem_data['var_values']}")
    print(f"=== Ajax问题页面结束 ===\n")

    return render_template('problem_ajax.html',
                           problem=problem_data,
                           problem_id=problem_id,
                           total_attempts=total_attempts,  # 改为累计尝试次数
                           answer_count=answer_count,
                           username=session['username'])


@app.route('/api/submit/<int:problem_id>', methods=['POST'])
@login_required
def api_submit(problem_id):
    """API接口：提交答案（支持动态答案数量）- 修改为使用前端传递的正确答案"""
    try:
        data = request.get_json()
        print(f"[API] 问题 {problem_id} 提交数据: {data}")

        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'})

        # 验证会话
        if 'current_problem' not in session:
            return jsonify({'success': False, 'message': '会话过期，请重新开始答题'})

        problem_data = session['current_problem']['data']

        # 关键修改：使用前端传递的正确答案，而不是session中的旧答案
        correct_answers = data.get('correct_answers')
        if not correct_answers:
            # 如果前端没有传递正确答案，则使用session中的（兼容性处理）
            correct_answers = problem_data['correct_answers']
            print(f"[API WARNING] 使用session中的正确答案: {correct_answers}")
        else:
            print(f"[API] 使用前端传递的正确答案: {correct_answers}")

        answer_count = problem_data.get('answer_count', 1)
        time_taken = float(data.get('time_taken', 0))
        user_id = session['user_id']
        template_id = problem_data['template_id']
        problem_text = problem_data['problem_text']

        print(f"[API DEBUG] 用户 {user_id} 提交问题 {problem_id}")
        print(f"模板ID: {template_id}")
        print(f"答案数量: {answer_count}")
        print(f"当前累计尝试次数: {session['current_problem']['total_attempts']}")
        print(f"答题用时: {time_taken}秒")
        print(f"正确答案: {correct_answers}")

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

        # 增加累计尝试次数
        session['current_problem']['total_attempts'] += 1
        total_attempts = session['current_problem']['total_attempts']

        # 保存答题记录 - 使用更新后的累计尝试次数
        save_success = save_user_response(
            user_id, template_id, problem_text, user_answers,
            correct_answers, is_correct_list, total_attempts, time_taken
        )

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

        if all_correct:
            # 回答正确后更新用户完成状态
            completed_all = update_user_completion_status(user_id)

            session['current_problem']['answered_correctly'] = True
            next_problem = problem_id + 1 if problem_id < 9 else None  # 现在有9道题
            message = '🎉 回答正确！'

            # 如果完成所有题目，生成验证链接
            if completed_all and problem_id >= 9:
                verification_url = f"/api/user/{user_id}/completion"
                session['verification_url'] = verification_url
        else:
            session['current_problem']['answered_correctly'] = False
            next_problem = problem_id

            # 答错时生成新题目（不再限制尝试次数）
            new_problem_data = generate_problem_from_template(problem_id)
            if new_problem_data:
                # 更新session中的题目数据和正确答案
                session['current_problem']['data'] = new_problem_data
                session['current_problem']['start_time'] = time.time()
                message = f'❌ 答案不正确！{correct_answer_message}。已为您生成新题目，请重新作答。'
            else:
                message = f'❌ 答案不正确！{correct_answer_message}。题目刷新失败，请重试。'

        response_data = {
            'success': True,
            'correct': all_correct,
            'message': message,
            'correct_answers': correct_answers,
            'total_attempts': total_attempts,
            'next_problem': next_problem,
            'save_success': save_success,
            'user_answers': user_answers,
            'answer_count': answer_count
        }

        # 如果生成了新题目，返回新题目的参数
        if new_problem_data:
            response_data['new_problem_generated'] = True
            response_data['new_var_values'] = new_problem_data['var_values']
            response_data['new_correct_answers'] = new_problem_data['correct_answers']
            response_data['new_problem_text'] = new_problem_data['problem_text']
        else:
            response_data['new_problem_generated'] = False

        print(f"[API RESPONSE] 返回数据: {response_data}")
        return jsonify(response_data)

    except ValueError as e:
        print(f"[API ERROR] 数值转换错误: {str(e)}")
        return jsonify({'success': False, 'message': '请输入有效的数字格式'})
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

    # 获取最近完成的学生
    recent_completions = get_students_by_completion(completed=True, limit=10)

    # 获取需要督促的学生
    incomplete_students = get_students_by_completion(completed=False, limit=10)

    return render_template('admin_dashboard.html',
                           stats=stats,
                           recent_completions=recent_completions,
                           incomplete_students=incomplete_students)






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
        # 获取所有用户
        cursor.execute("SELECT id FROM users")
        users = cursor.fetchall()

        updated_count = 0
        for user in users:
            if update_user_completion_status(user['id']):
                updated_count += 1

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

    status_text = '已完成' if completed else '未完成'

    return render_template('admin_students.html',
                           students=students,
                           status=status,
                           status_text=status_text,
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

        # 修复SQL查询 - 简化查询逻辑
        cursor.execute("""
            SELECT 
                t.id as template_id,
                t.template_name,
                COUNT(r.id) as total_attempts,
                SUM(CASE WHEN r.is_correct = TRUE THEN 1 ELSE 0 END) as correct_attempts,
                MIN(CASE WHEN r.is_correct = TRUE THEN r.time_taken ELSE NULL END) as best_time,
                AVG(r.time_taken) as avg_time,
                MAX(r.response_time) as last_attempt_time
            FROM problem_templates t
            LEFT JOIN user_responses r ON t.id = r.template_id AND r.user_id = %s
            GROUP BY t.id, t.template_name
            ORDER BY t.id
        """, (user_id,))

        problem_stats = cursor.fetchall()

        # 计算总体统计
        cursor.execute("""
            SELECT 
                COUNT(*) as total_attempts,
                SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as total_correct,
                AVG(time_taken) as overall_avg_time
            FROM user_responses 
            WHERE user_id = %s
        """, (user_id,))

        overall_stats = cursor.fetchone()

        return render_template('admin_student_details.html',
                               student=student,
                               problem_stats=problem_stats,
                               overall_stats=overall_stats,
                               username=session['username'])

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
        # 修复SQL查询 - 简化查询逻辑
        cursor.execute("""
            SELECT 
                t.id as template_id,
                t.template_name,
                COUNT(DISTINCT u.id) as total_students,
                COUNT(DISTINCT CASE WHEN ur.is_correct = TRUE THEN u.id ELSE NULL END) as completed_students,
                COUNT(ur.id) as total_attempts,
                SUM(CASE WHEN ur.is_correct = TRUE THEN 1 ELSE 0 END) as correct_attempts,
                AVG(CASE WHEN ur.is_correct = TRUE THEN ur.time_taken ELSE NULL END) as avg_correct_time,
                AVG(ur.time_taken) as avg_time
            FROM problem_templates t
            CROSS JOIN users u
            LEFT JOIN user_responses ur ON t.id = ur.template_id AND u.id = ur.user_id
            WHERE u.username != 'admin'
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

        return render_template('admin_all_problems_stats.html',
                               problem_stats=problem_stats,
                               total_students=total_students,
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


if __name__ == '__main__':
    # 初始化数据库
    initialize_database()
    # 创建管理员用户
    create_admin_user()  # 添加这一行
    # 更新现有模板
    update_existing_templates()
    # 修复可能存在的表结构问题
    repair_database()
    # 运行数据库诊断
    print("运行数据库诊断...")
    diagnose_database_issue()

    app.run(host='0.0.0.0', port=5000, debug=False)