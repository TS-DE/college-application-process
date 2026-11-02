import os
import pandas as pd
from sqlalchemy import create_engine

# 1. 建立数据库连接 (请替换为你自己的密码)
engine = create_engine("mysql+pymysql://root:123456@localhost:3306/gaokao?charset=utf8mb4")

base_dir = "./gaokao_data/data/2025"
provinces = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]

# ★ 修复点：把 VARCHAR 改成 'str'，强制让 pandas 当成字符串处理
dtype_mapping = {
    'university_code': 'str',
    'major_code': 'str',
    'major_group': 'str',
    'province': 'str'
}

is_first_write = True

for prov in provinces:
    file_path = os.path.join(base_dir, prov, "major-admission.csv")
    
    if not os.path.exists(file_path):
        continue
        
    try:
        print(f"正在读取 {prov} 数据...")
        # 读取 CSV，强制指定关键字段类型
        df = pd.read_csv(file_path, dtype=dtype_mapping)
        
        if 'province' not in df.columns:
            df['province'] = prov
            
        # ★ 修复点：第一次写入用 'replace' (重建表)，后面用 'append' (追加)
        if_exists_mode = "replace" if is_first_write else "append"
        
        # 分批写入 MySQL 总表
        df.to_sql("major_admission_2025_all", con=engine, if_exists=if_exists_mode, index=False, chunksize=2000)
        
        print(f"  [成功] {prov} 写入 {len(df)} 条数据")
        is_first_write = False  # 第一次成功后，后续改为追加
        
    except Exception as e:
        print(f"  [失败] {prov} 处理出错: {e}")

print("所有省份 major_admission 数据合并入库完成！")