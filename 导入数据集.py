from huggingface_hub import snapshot_download

# 下载河南 2024 和 2025 年的数据
snapshot_download(
    repo_id="choucsan/Gaokao-Compass-11M",
    repo_type="dataset",
    local_dir="./gaokao_data",  # 下载到当前项目下的 gaokao_data 文件夹
    allow_patterns=["data/2024/henan/*", "data/2025/henan/*"],  # 只下载河南数据
)
print("下载完成！")