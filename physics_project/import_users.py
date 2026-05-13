import re
from openpyxl import load_workbook
import mysql.connector
from werkzeug.security import generate_password_hash

# ==================【你只需要改这里】==================

EXCEL_PATH = "实验模板.xlsx"   # Excel 文件路径（可相对/绝对）
DEFAULT_PASSWORD = "@ncst+学号后四位（入库前哈希）"

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "database": "physics_new3",
}

IMPORT_MODE = "skip"
# skip   = 已存在学号直接跳过
# update = 已存在学号则更新姓名（和密码）

RESET_PASSWORD = True
# True  = 导入时密码按“@ncst+学号后四位”生成并以哈希存储
# False = 不动已有用户密码

# =====================================================

ID_HEADERS = {
    "学号", "学生学号", "学号(必填)", "student_id", "studentid", "id", "账号", "用户名", "username"
}
NAME_HEADERS = {"姓名", "名字", "name", "student_name"}


def clean_student_id(value):
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None

    # 处理 20230001.0
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]

    # 科学计数法
    if "e" in s.lower():
        try:
            s = str(int(float(s)))
        except Exception:
            return None

    s = re.sub(r"\s+", "", s)
    s = re.sub(r"\D", "", s)
    return s if s else None


def normalize(s):
    return str(s).strip().lower() if s else ""


def find_col(header, candidates):
    for i, h in enumerate(header):
        if normalize(h) in {normalize(x) for x in candidates}:
            return i
    return None


def main():
    print("🚀 开始导入用户数据...")

    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        wb = load_workbook(EXCEL_PATH, data_only=True)
        sheet = wb.active
        rows = list(sheet.iter_rows(values_only=True))

        if not rows:
            print("⚠️ Excel 为空")
            return

        header = rows[0]
        id_idx = find_col(header, ID_HEADERS)
        name_idx = find_col(header, NAME_HEADERS)

        if id_idx is None:
            print("❌ 未找到学号列")
            print("可识别表头：", ID_HEADERS)
            return

        print(f"✅ 学号列位置：第 {id_idx + 1} 列")

        if IMPORT_MODE == "skip":
            if RESET_PASSWORD:
                sql = """
                INSERT IGNORE INTO users (username, password, name)
                VALUES (%s, %s, %s)
                """
            else:
                sql = """
                INSERT IGNORE INTO users (username, name)
                VALUES (%s, %s)
                """
        else:
            if RESET_PASSWORD:
                sql = """
                INSERT INTO users (username, password, name)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    password = VALUES(password)
                """
            else:
                sql = """
                INSERT INTO users (username, name)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name)
                """

        batch = []
        skipped = 0

        for r in rows[1:]:
            sid = clean_student_id(r[id_idx] if id_idx < len(r) else None)
            if not sid:
                skipped += 1
                continue

            name = ""
            if name_idx is not None and name_idx < len(r):
                name = str(r[name_idx]).strip() if r[name_idx] else ""

            if RESET_PASSWORD:
                initial_password = "@ncst" + sid[-4:].zfill(4)
                batch.append((sid, generate_password_hash(initial_password), name))
            else:
                batch.append((sid, name))

        if not batch:
            print("⚠️ 没有可导入的数据")
            return

        cursor.executemany(sql, batch)
        conn.commit()

        print("🎉 导入完成！")
        print(f"   尝试导入：{len(batch)} 条")
        print(f"   跳过无效：{skipped} 条")
        print(f"   模式：{IMPORT_MODE}")

    except Exception as e:
        conn.rollback()
        print("❌ 导入失败：", e)
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
