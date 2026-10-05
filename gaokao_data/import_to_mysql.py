import pandas as pd
from sqlalchemy import create_engine

# MySQL 连接配置（根据你的实际配置修改）
DB_USER = 'root'
DB_PASSWORD = '123456'
DB_HOST = 'localhost'
DB_PORT = '3306'
DB_NAME = 'gaokao'

# 创建数据库连接引擎
engine = create_engine(f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}')

# 先确保数据库存在（需手动创建或运行一次创建语句）
# CREATE DATABASE IF NOT EXISTS gaokao DEFAULT CHARACTER SET utf8mb4;

# 定义需要导入的文件和对应的表名
files_to_import = {
    'data/2024/henan/enrollment-plan.csv': 'enrollment_plan_2024_henan',
    'data/2024/henan/school-admission.csv': 'school_admission_2024_henan',
    'data/2024/henan/major-admission.csv': 'major_admission_2024_henan',
    'data/2024/henan/score-range.csv': 'score_range_2024_henan',
    'data/2025/henan/enrollment-plan.csv': 'enrollment_plan_2025_henan',
    'data/2025/henan/school-admission.csv': 'school_admission_2025_henan',
    'data/2025/henan/major-admission.csv': 'major_admission_2025_henan',
    'data/2025/henan/score-range.csv': 'score_range_2025_henan',
}

for csv_path, table_name in files_to_import.items():
    try:
        print(f'正在读取 {csv_path} ...')
        df = pd.read_csv(csv_path, encoding='utf-8')

        # 导入 MySQL
        df.to_sql(
            name=table_name,
            con=engine,
            if_exists='replace',  # 首次导入用 replace，后续可改 append
            index=False,
            chunksize=1000,  # 分批写入，避免内存溢出
            method='multi'
        )
        print(f'✅ {table_name} 导入成功，共 {len(df)} 行')

    except FileNotFoundError:
        print(f'❌ 文件不存在：{csv_path}')
    except Exception as e:
        print(f'❌ {table_name} 导入失败：{e}')