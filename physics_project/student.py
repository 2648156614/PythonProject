import mysql.connector
import csv

 # 使用原始字符串

# 或者
csv_path = 'C:/student/student.csv'  # 使用正斜杠

# 连接数据库
conn = mysql.connector.connect(
    host='localhost',
    user='root',
    password='123456',
    database='physics_new3'
)

cursor = conn.cursor()

try:
    # 打开文件
    with open(csv_path, 'r', encoding='utf-8') as file:
        reader = csv.reader(file)

        # 跳过标题行（如果有）
        try:
            next(reader)
        except StopIteration:
            print("⚠️ CSV文件为空")

        data = []
        for row in reader:
            if row and len(row) > 0:
                student_id = row[0].strip()
                # 确保学号是数字
                if student_id and student_id.isdigit():
                    data.append((student_id, '123456'))
                    print(f"添加学生: {student_id}")

        # 批量插入
        if data:
            sql = "INSERT INTO users (username, password) VALUES (%s, %s)"
            cursor.executemany(sql, data)
            conn.commit()
            print(f"✅ 成功插入 {len(data)} 条记录")
        else:
            print("⚠️ 没有找到有效数据")

except FileNotFoundError:
    print(f"❌ 文件未找到，请检查路径: {csv_path}")
    print("当前路径应该是: C:\\Users\\26481\\Desktop\\student.csv")
except Exception as e:
    print(f"❌ 导入失败: {str(e)}")
    conn.rollback()

cursor.close()
conn.close()