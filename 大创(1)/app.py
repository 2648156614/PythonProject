from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
import random
import sympy as sp
import time
import os
from functools import wraps

app = Flask(__name__, template_folder='templates')
app.secret_key = 'your_secret_key_here'

# 数据库配置
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '123456',
    'database': 'physics_new'
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
    if correct_answer == 0:
        return user_answer == 0
    tolerance = abs(correct_answer) * 0.01  # 1%容错
    return abs(user_answer - correct_answer) <= tolerance


def save_user_response(user_id, template_id, problem_text, user_answer, correct_answer, is_correct, attempt_count,
                       time_taken):
    """保存答题记录到数据库"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO user_responses 
            (user_id, template_id, problem_text, user_answer, 
             correct_answer, is_correct, attempt_count, time_taken, response_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (user_id, template_id, problem_text, user_answer,
              correct_answer, is_correct, attempt_count, time_taken))

        conn.commit()
        print(f"[SUCCESS] 记录保存成功，ID: {cursor.lastrowid}")
        return True
    except mysql.connector.Error as err:
        print(f"[DATABASE ERROR] 保存失败: {err}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn and conn.is_connected():
            conn.close()


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
    variables = [v.strip() for v in template['variables'].split(',')]  # 确保变量列表干净
    var_values = {}

    # 为每个变量生成随机值
    for var in variables:
        print(var)
        if var == 'v_terminal':
            var_values[var] = random.randint(3, 6)  # 整数终末速度 3-6 m/s
        elif var == 'v':
            # 确保 v 是整数且小于 v_terminal
            if 'v_terminal' in var_values:
                v_terminal = var_values['v_terminal']
                # 生成 1 到 (v_terminal-1) 的整数
                var_values[var] = random.randint(1, v_terminal - 1)
            else:
                # 如果 v_terminal 还没生成，先生成 v_terminal
                v_terminal = random.randint(3, 6)
                var_values['v_terminal'] = v_terminal
                var_values[var] = random.randint(1, v_terminal - 1)
        else:
            var_values[var] = random.randint(2, 4)


        # if var == 'a0' or var == 'a1' or var == 'a2':
        #     var_values[var] = round(random.uniform(1, 10), 1)
        # elif var == 'v0':
        #     var_values[var] = random.randint(2, 10)
        #
        # elif var == 'x1':
        #     var_values[var] = random.randint(1, 10)
        # elif var == 'm':
        #     var_values[var] = random.randint(2, 4)
        # elif var == 'K':
        #     var_values[var] = round(random.uniform(1, 4), 1)
        # elif var == 't1':
        #     var_values[var] = random.randint(1, 10)
        # elif var == 'v_terminal':
        #     var_values[var] = round(random.uniform(6, 10), 1)
        # elif var == 'v':
        #     var_values[var] = round(random.uniform(3, 6), 1)
        # elif var == 'k':
        #     var_values[var] = random.randint(1, 10)
        # elif var == 'A':
        #     var_values[var] = random.randint(1, 10)
        # elif var == 'depth':
        #     var_values[var] = round(random.uniform(5, 15), 1)
        # elif var == 'm0':
        #     var_values[var] = round(random.uniform(10, 20), 1)
        # elif var == 'm1':
        #     var_values[var] = random.randint(1, 2)
        # elif var == 'theta':
        #     var_values[var] = random.randint(10, 60)  # 随机角度（10-60度）
        # elif var == 'mu':
        #     var_values[var] = round(random.uniform(0.1, 0.9), 2)  # 摩擦系数（0.1-0.9）

    # 删除重复的变量处理代码（原代码中有重复部分）

    # 在所有基本变量定义后，计算衍生变量
    if 'A' in var_values:  # 第四题需要的衍生变量
        var_values['A_div_4'] = var_values['A'] / 4

    if 'depth' in var_values:  # 第五题需要的衍生变量
        var_values['leak_rate'] = round(random.uniform(0.1, 0.5), 1)

    # 生成问题文本
    try:
        problem_text = template['problem_text'].format(**var_values)
    except KeyError as e:
        print(f"模板格式化失败，缺失变量：{e}")
        raise

    # 计算正确答案
    x, t, h = sp.symbols('x t h')
    local_vars = {'x': x, 't': t, 'h': h, 'sp': sp, 'sqrt': sp.sqrt, 'exp': sp.exp, 'integrate': sp.integrate}
    local_vars.update(var_values)

    try:
        correct_answer = eval(template['solution_formula'], {}, local_vars)
        if isinstance(correct_answer, tuple):
            correct_answers = [float(a.evalf()) if hasattr(a, 'evalf') else float(a) for a in correct_answer]
        else:
            correct_answers = [
                float(correct_answer.evalf()) if hasattr(correct_answer, 'evalf') else float(correct_answer)]
    except:
        correct_answers = [0.0]

    return {
        'problem_text': problem_text,
        'var_values': var_values,
        'correct_answers': correct_answers,
        'template_id': template_id
    }


def save_user_response(user_id, template_id, problem_text, user_answer, correct_answer, is_correct, attempt_count,
                       time_taken):
    """保存用户答题记录（带详细日志）"""
    conn = None
    try:
        print(f"[DEBUG] 准备保存记录：用户{user_id}, 模板{template_id}, 答案{user_answer}")
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO user_responses 
            (user_id, template_id, problem_text, user_answer, 
             correct_answer, is_correct, attempt_count, time_taken)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (user_id, template_id, problem_text, user_answer,
              correct_answer, is_correct, attempt_count, time_taken))

        conn.commit()
        print("[DEBUG] 记录保存成功，ID:", cursor.lastrowid)
        return True
    except Exception as e:
        print(f"[ERROR] 保存失败: {str(e)}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn and conn.is_connected():
            conn.close()


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

    # 创建用户表（如果不存在）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) NOT NULL UNIQUE,
        password VARCHAR(100) NOT NULL,
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
        solution_formula TEXT NOT NULL
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
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (template_id) REFERENCES problem_templates(id)
    )
    """)

    # 插入问题模板（如果不存在）
    templates = [
        # 问题1：加速度与速度的关系
        {
            'name': '加速度与速度的关系',
            'text': r"""
                <div class="math-formula">
                <h5>题目描述：</h5>
                <p>一质点沿x轴运动，其加速度 \( \vec{a} \) 与位置坐标 \( x \) 的关系为：</p>
                \[ \vec{a} = a_0 + a_1x + a_2x^2 \quad (\text{SI单位制}) \]
                <p>其中：</p>
                <ul>
                    <li>\( a_0 = {{ problem.var_values.a0 }} \, \text{m/s}^2 \)</li>
                    <li>\( a_1 = {{ problem.var_values.a1 }} \, \text{s}^{-2} \)</li>
                    <li>\( a_2 = {{ problem.var_values.a2 }} \, \text{m}^{-1}\text{s}^{-2} \)</li>
                </ul>
                <p>如果质点在原点处的速度为 \( v_0 = {{ problem.var_values.v0 }} \, \text{m/s} \)，试求其在 \( x_1 = {{ problem.var_values.x1 }} \, \text{m} \) 时的速度 \( v \)。</p>

                <div class="alert alert-info mt-3">
                    <h5><i class="bi bi-lightbulb"></i> 解题提示：</h5>
                    <p>利用加速度与速度的关系：\( a = \frac{dv}{dt} = v \frac{dv}{dx} \)</p>
                    <p>分离变量后积分：\( \int v dv = \int a dx \)</p>
                </div>
            </div>
               """,
            'variables': 'a0,a1,a2,v0,x1',
            'formula': "sqrt(v0**2 + 2*(a0*x1 + (a1/2)*x1**2 + (a2/3)*x1**3))"
        },

        # 问题2：子弹击入木块做功问题（修正版）
        {
            'name': '子弹击入木块做功问题',
            'text': r"""
            <div class="math-formula">
            <h5>题目描述：</h5>
            <p>质量为 \( M = {{ problem.var_values.M }} \, \text{kg} \) 的木块静止在光滑的水平面上。质量为 \( m = {{ problem.var_values.m }} \, \text{kg} \)、速率为 \( v = {{ problem.var_values.v }} \, \text{m/s} \) 的子弹沿水平方向打入木块并陷在其中。</p>
            <p>试计算：</p>
            <ol>
                <li>木块对子弹所作的功 \( W_1 \)（绝对值）</li>
                <li>子弹对木块所作的功 \( W_2 \)</li>
            </ol>
            </div>
           """,
            'variables': 'M,m,v',
            'formula': "(1/2)*m*v**2 - (1/2)*m*( (m*v)/(m+M) )**2, (1/2)*M*( (m*v)/(m+M) )**2"
        },

        # 问题3：雨滴下降的加速度
        {
            'name': '雨滴下降的加速度',
            'text': r"""
               <div class="math-formula">
            <h5>题目描述：</h5>
            <p>质量为 \( m \) 的雨滴下降时，因受空气阻力，在落地前已是匀速运动，其终末速率为 \( v_1 = {{ problem.var_values.v_terminal }} \, \text{m/s} \)。</p>
            <p>空气阻力大小与雨滴速率的平方成正比：</p>
            \[ \vec{F}_{\text{阻}} = -k\vec{v}^2 \]
            <p>试求当雨滴下降速率为 \( v = {{ problem.var_values.v }} \, \text{m/s} \) 时，其加速度 \( \vec{a} \) 的大小。</p>

            <div class="alert alert-info mt-3">
                <h5><i class="bi bi-lightbulb"></i> 解题提示：</h5>
                <p>终末速度时受力平衡：\( mg = kv_1^2 \)</p>
                <p>任意速度时牛顿第二定律：\( ma = mg - kv^2 \)</p>
                <p>重力加速度 \( g = 9.8 \, \text{m/s}^2 \)</p>
            </div>
        </div>
               """,
            'variables': 'v,v1',
            'formula': "9.8 * (1 - (v**2) / (v_terminal**2))"
        },

        # 问题4：质点受引力的速度
        {
            'name': '质点受引力的速度',
            'text': r"""
            <div class="math-formula">
                <h5>题目描述：</h5>
                <p>已知一质量为 \( m = {{ problem.var_values.m }} \, \text{kg} \) 的质点在x轴上运动，质点只受到指向原点的引力作用，引力大小与质点离原点的距离 \( x \) 的平方成反比：</p>
                \[ \vec{F} = -\frac{k}{x^2}\hat{i} \]
                <p>其中比例系数 \( k = {{ problem.var_values.k }} \, \text{N}\cdot\text{m}^2 \)。</p>
                <p>设质点在 \( x = A = {{ problem.var_values.A }} \, \text{m} \) 时的速度为零，求质点在 \( x = \frac{A}{4} = {{ problem.var_values.A/4 }} \, \text{m} \) 处的速度的大小 \( v \)。</p>

                <div class="alert alert-info mt-3">
                <h5><i class="bi bi-lightbulb"></i> 解题提示：</h5>
                <p>利用动能定理：\( W = \Delta K \)</p>
                <p>功的计算：\( W = \int_{x_1}^{x_2} F dx \)</p>
                <p>动能变化：\( \Delta K = \frac{1}{2}mv_2^2 - \frac{1}{2}mv_1^2 \)</p>
                </div>
            </div>
               """,
            'variables': 'm, k, A',
            'formula': "sqrt(2 * k * (1/(A/4) - 1/A) / m)"
        },

        # 问题5：提水桶的功
        {
            'name': '提水桶的功',
            'text': r"""
            <div class="math-formula">
                <h5>题目描述：</h5>
                <p>一人从 \( h = {{ problem.var_values.h }} \, \text{m} \) 深的井中提水，已知：</p>
                <ul>
                    <li>起始时桶中装有 \( m_0 = {{ problem.var_values.m0 }} \, \text{kg} \) 的水</li>
                    <li>桶的质量为 \( m_1 = {{ problem.var_values.m1 }} \, \text{kg} \)</li>
                    <li>由于水桶漏水，每升高 \( 1 \, \text{m} \) 要漏去 \( u = {{ problem.var_values.u }} \, \text{kg} \) 的水</li>
                </ul>
                <p>求水桶匀速地从井中提到井口，人所作的功 \( W \)。</p>

                <div class="alert alert-info mt-3">
                    <h5><i class="bi bi-lightbulb"></i> 解题提示：</h5>
                    <p>总质量随高度变化：\( m(h) = (m_0 + m_1) - uh \)</p>
                    <p>功的计算：\( W = \int_0^H F(h) dh = \int_0^H m(h)g dh \)</p>
                    <p>重力加速度 \( g = 9.8 \, \text{m/s}^2 \)</p>
                </div>
            </div>
               """,
            'variables': 'h,m0,m1,u',
            'formula': "abs(9.8 * ((m0 + m1) * h - (u/2) * h**2))"
        }
    ]

    # 插入模板到数据库
    for template in templates:
        cursor.execute("SELECT id FROM problem_templates WHERE template_name = %s", (template['name'],))
        if not cursor.fetchone():
            cursor.execute("""
                   INSERT INTO problem_templates (template_name, problem_text, variables, solution_formula)
                   VALUES (%s, %s, %s, %s)
               """, (
                template['name'],
                template['text'],
                template['variables'],
                template['formula']
            ))

    conn.commit()
    cursor.close()
    conn.close()




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
    # 检查用户当前应该做哪道题
    current_problem = 1
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        for problem_id in range(1, 6):
            cursor.execute("""
                SELECT COUNT(*) FROM user_responses 
                WHERE user_id = %s AND template_id = %s AND is_correct = TRUE
            """, (session['user_id'], problem_id))
            if cursor.fetchone()[0] == 0:
                current_problem = problem_id
                break
    except mysql.connector.Error as err:
        print(f"数据库查询错误: {err}")
        flash('数据库查询错误', 'danger')
    finally:
        cursor.close()
        conn.close()

    # 重置尝试次数
    session.pop('attempt_count', None)
    session.pop('current_problem', None)

    return render_template('dashboard.html',
                           username=session['username'],
                           current_problem=current_problem)


@app.route('/problem/<int:problem_id>', methods=['GET', 'POST'])
@login_required
def problem(problem_id):
    """处理问题展示和答案提交"""
    # 验证题目ID范围
    if problem_id < 1 or problem_id > 5:
        flash('无效的题目编号', 'danger')
        return redirect(url_for('dashboard'))

    # 检查前置题目是否完成（问题2-5需要先完成前一题）
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
        problem_data = generate_problem_from_template(problem_id)
        if not problem_data:
            flash('题目生成失败', 'danger')
            return redirect(url_for('dashboard'))

        session['current_problem'] = {
            'id': problem_id,
            'data': problem_data,
            'attempt_count': 0,
            'answered_correctly': False,
            'start_time': time.time()  # 记录开始答题时间
        }
        print(f"[DEBUG] 初始问题 {problem_id}，开始时间: {session['current_problem']['start_time']}")

    # 获取当前问题数据
    problem_data = session['current_problem']['data']
    attempt_count = session['current_problem']['attempt_count']
    start_time = session['current_problem'].get('start_time', time.time())

    # 处理答案提交
    if request.method == 'POST':
        try:
            # 计算答题用时（秒）
            time_taken = round(time.time() - start_time, 2)

            user_id = session['user_id']
            template_id = problem_data['template_id']
            problem_text = problem_data['problem_text']
            correct_answers = problem_data['correct_answers']

            # 调试信息
            print(f"\n[DEBUG] 用户 {user_id} 提交问题 {problem_id}")
            print(f"模板ID: {template_id}")
            print(f"尝试次数: {attempt_count + 1}")
            print(f"答题用时: {time_taken}秒")

            # 处理不同题型的答案
            if problem_id == 2:  # 第二题有双答案
                user_answer_v = float(request.form.get('answer_v', 0))
                user_answer_depth = float(request.form.get('answer_depth', 0))

                correct_v = is_correct(user_answer_v, correct_answers[0])
                correct_depth = is_correct(user_answer_depth, correct_answers[1])

                print(f"答案1: {user_answer_v} (正确: {correct_answers[0]}, 结果: {'正确' if correct_v else '错误'})")
                print(
                    f"答案2: {user_answer_depth} (正确: {correct_answers[1]}, 结果: {'正确' if correct_depth else '错误'})")

                # 保存两个答题记录
                save_success = all([
                    save_user_response(
                        user_id, template_id, problem_text, user_answer_v,
                        correct_answers[0], correct_v, attempt_count + 1, time_taken
                    ),
                    save_user_response(
                        user_id, template_id, problem_text, user_answer_depth,
                        correct_answers[1], correct_depth, attempt_count + 1, time_taken
                    )
                ])

                if correct_v and correct_depth:
                    session['current_problem']['answered_correctly'] = True
                    session['current_problem']['attempt_count'] = 0
                    flash('回答正确！即将进入下一题', 'success')
                    return redirect(url_for('problem', problem_id=3))
                else:
                    session['current_problem']['attempt_count'] += 1
                    if not save_success:
                        flash('部分答题记录保存失败', 'warning')

            else:  # 其他单答案题目
                user_answer = float(request.form.get('answer', 0))
                correct = is_correct(user_answer, correct_answers[0])

                print(f"用户答案: {user_answer} (正确: {correct_answers[0]}, 结果: {'正确' if correct else '错误'})")

                # 保存答题记录
                save_success = save_user_response(
                    user_id, template_id, problem_text, user_answer,
                    correct_answers[0], correct, attempt_count + 1, time_taken
                )

                if correct:
                    session['current_problem']['answered_correctly'] = True
                    session['current_problem']['attempt_count'] = 0
                    flash('回答正确！', 'success')
                    next_problem = problem_id + 1
                    if next_problem <= 5:
                        return redirect(url_for('problem', problem_id=next_problem))
                    else:
                        flash('恭喜你完成所有题目！', 'success')
                        return redirect(url_for('dashboard'))
                elif not save_success:
                    flash('答题记录保存失败', 'warning')

            # 处理尝试次数限制
            attempt_count = session['current_problem']['attempt_count']
            if attempt_count >= 3:
                print(f"[WARNING] 用户 {user_id} 问题 {problem_id} 超过最大尝试次数")
                session.pop('current_problem', None)
                flash('很遗憾，三次尝试均失败，请从首页重新开始！', 'danger')
                return redirect(url_for('dashboard'))

            # 重置计时器
            session['current_problem']['start_time'] = time.time()

        except ValueError:
            flash('请输入有效的数字', 'danger')
        except Exception as e:
            print(f"[ERROR] 问题处理异常: {str(e)}")
            flash('处理答案时发生错误', 'danger')

    # 检查是否已经正确回答过（防止通过URL跳过）
    if session['current_problem'].get('answered_correctly', False):
        next_problem = problem_id + 1
        if next_problem <= 5:
            return redirect(url_for('problem', problem_id=next_problem))
        else:
            return redirect(url_for('dashboard'))

    # 渲染问题模板
    template_file = f'problem{problem_id}.html'
    return render_template(template_file,
                           problem=problem_data,
                           username=session['username'],
                           attempt_count=attempt_count)


@app.route('/stats')
@login_required
def statistics():  # 使用唯一函数名
    """统计信息页面"""
    try:
        if 'user_id' not in session:
            flash('请先登录', 'warning')
            return redirect(url_for('login'))

        conn = get_db_connection()
        if not conn:
            flash('数据库连接失败', 'danger')
            return redirect(url_for('dashboard'))

        cursor = conn.cursor(dictionary=True)

        # 总体统计
        cursor.execute("""
            SELECT 
                COUNT(*) as total_count,
                SUM(is_correct) as correct_count,
                AVG(time_taken) as avg_time
            FROM user_responses 
            WHERE user_id = %s
        """, (session['user_id'],))

        stats = cursor.fetchone() or {
            'total_count': 0,
            'correct_count': 0,
            'avg_time': 0
        }

        # 各题目统计
        cursor.execute("""
            SELECT 
                t.template_name,
                COUNT(*) as total,
                SUM(CASE WHEN r.is_correct THEN 1 ELSE 0 END) as correct
            FROM user_responses r
            JOIN problem_templates t ON r.template_id = t.id
            WHERE r.user_id = %s
            GROUP BY t.template_name
        """, (session['user_id'],))

        problem_stats = cursor.fetchall()

        accuracy = 0
        if stats['total_count'] > 0:
            accuracy = round(stats['correct_count'] / stats['total_count'] * 100, 1)

        return render_template('stats.html',
                               accuracy=accuracy,
                               correct_count=stats['correct_count'],
                               total_count=stats['total_count'],
                               avg_time=round(stats['avg_time'], 1),
                               problem_stats=problem_stats,
                               username=session['username'])

    except Exception as e:
        print(f"[统计页面错误] {str(e)}")
        flash('获取统计信息失败', 'danger')
        return redirect(url_for('dashboard'))
    finally:
        if conn and conn.is_connected():
            conn.close()


@app.route('/history')
@login_required
def show_history():
    """获取答题历史（带详细调试）"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            flash('请先登录', 'warning')
            return redirect(url_for('login'))

        print(f"[DEBUG] 查询用户{user_id}的历史记录")

        conn = get_db_connection()
        if not conn:
            flash('数据库连接失败', 'danger')
            return render_template('history.html', responses=[])

        cursor = conn.cursor(dictionary=True)

        # 查询历史记录
        cursor.execute("""
            SELECT * FROM user_responses 
            WHERE user_id = %s 
            ORDER BY response_time DESC
        """, (user_id,))

        responses = cursor.fetchall()
        print(f"[DEBUG] 查询到{len(responses)}条记录")

        # 如果没有记录，检查数据库连接和表结构
        if not responses:
            print("[DEBUG] 无记录，检查数据库...")
            cursor.execute("SHOW TABLES LIKE 'user_responses'")
            if not cursor.fetchone():
                print("[ERROR] user_responses表不存在！")

            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            if not cursor.fetchone():
                print(f"[ERROR] 用户ID {user_id} 不存在！")

        return render_template('history.html',
                               responses=responses,
                               username=session.get('username', ''))

    except Exception as e:
        print(f"[ERROR] 历史记录查询失败: {str(e)}")
        flash('获取历史记录失败，请稍后再试', 'danger')
        return render_template('history.html', responses=[])
    finally:
        if conn and conn.is_connected():
            conn.close()


@app.route('/history')
@login_required
def history():
    """获取答题历史（带完整错误处理）"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 获取基础答题历史
        cursor.execute("""
            SELECT 
                r.id,
                t.template_name,
                r.problem_text,
                r.user_answer,
                r.correct_answer,
                r.is_correct,
                r.attempt_count,
                DATE_FORMAT(r.response_time, '%%Y-%%m-%%d %%H:%%i:%%s') as formatted_time,
                r.time_taken,
                t.id as template_id
            FROM user_responses r
            JOIN problem_templates t ON r.template_id = t.id
            WHERE r.user_id = %s
            ORDER BY r.response_time DESC
        """, (session['user_id'],))

        responses = cursor.fetchall()

        # 获取统计信息
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(is_correct) as correct,
                AVG(time_taken) as avg_time
            FROM user_responses 
            WHERE user_id = %s
        """, (session['user_id'],))
        stats = cursor.fetchone()

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


if __name__ == '__main__':
    # 初始化数据库
    initialize_database()
    # 修复可能存在的表结构问题
    repair_database()
    app.run(debug=True)