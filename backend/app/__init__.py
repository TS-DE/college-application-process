"""FastAPI 应用入口（app 包）。"""

import os

# 0.19.0：protobuf 兼容开关前移。
#
# ## 为什么必须放在这里
# `chromadb` 依赖的 `*_pb2.py` 是旧版 protoc 生成的，与 protobuf 7.x 的 C 扩展不兼容，
# 导入时会报 "Descriptors cannot be created directly"。设成纯 Python 实现即可绕过。
#
# 这个变量**必须在任何 google.protobuf 导入之前**生效：
# 0.17.1 把它放在 `backend/.env` 里，靠 config 先于 chromadb 被导入的偶然顺序；
# 换一个入口脚本（比如测试直接 import chromadb）就会失效。
# `app/__init__.py` 在任何 `app.*` 子模块之前执行，是唯一稳定的位置。
# .env 里的同名配置保留不删，作为双保险。
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
