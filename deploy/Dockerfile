# 高考志愿填报系统 · 后端镜像（含前端 dist 静态托管）
# 构建：docker build -t gaokao-backend:latest -f deploy/Dockerfile .
# 说明：后端 FastAPI 启动后自动托管 frontend/dist（SPA 回退），无需单独前端容器

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 先复制依赖清单并安装（善用镜像分层缓存）
COPY backend/requirements.txt backend/requirements.txt
# 国内网络加速：如 pypi.org 直连缓慢，可改用清华源（实测间歇性故障，故默认官方源）
# ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
#     PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
# 先升级 pip：python:3.11-slim 内置 pip 24.0 在复杂依赖解析时存在哈希校验误报（2026-11-02 实测多次），
# 升级至 pip 26.x 后下载校验正常
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r backend/requirements.txt

# 复制后端源码与前端构建产物
# 注意：backend/.env、chroma_db、knowledge_files、data 等由 .dockerignore 排除，
#       运行期通过 docker-compose 的 env_file 与目录挂载提供
COPY backend backend
COPY frontend/dist frontend/dist

WORKDIR /app/backend

EXPOSE 8000

# HOST 固定 0.0.0.0：容器外访问入口由 compose 端口映射提供
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
