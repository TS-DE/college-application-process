import os
import pandas as pd
from sqlalchemy import create_engine

# 1. 建立数据库连接
engine = create_engine("mysql+pymysql://root:123456@localhost:3306/gaokao?charset=utf8mb4")
base_dir = "./gaokao_data/data/2025"
provinces = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]

def import_table(file_name, table_name):
    print(f"\n========== 开始合并 {file_name} -> {table_name} ==========")
    is_first_write = True
    
    for prov in provinces:
        file_path = os.path.join(base_dir, prov, file_name)
        if not os.path.exists(file_path):
            continue
            
        try:
            print(f"正在读取 {prov} 的 {file_name}...")
            # 全部字段强制按字符串读入，避免 pandas 瞎猜类型导致报错
            df = pd.read_csv(file_path, dtype=str)
            
            # 兼容处理：防止有些表里没有 province 字段
            if 'province' not in df.columns:
                df['province'] = prov
                
            if_exists_mode = "replace" if is_first_write else "append"
            
            df.to_sql(table_name, con=engine, if_exists=if_exists_mode, index=False, chunksize=2000)
            print(f"  [成功] {prov} 写入 {len(df)} 条")
            is_first_write = False
            
        except Exception as e:
            print(f"  [失败] {prov} 处理出错: {e}")

# 导入一分一段表
import_table("score-range.csv", "score_range_2025_all")

# 导入招生计划表
import_table("enrollment-plan.csv", "enrollment_plan_2025_all")