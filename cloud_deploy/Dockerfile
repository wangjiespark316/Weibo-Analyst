# 微博舆情 API - Dockerfile（Render 部署用）
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY cloud_deploy/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码（step7_api_service 是 FastAPI 服务）
COPY step7_api_service/ ./step7_api_service/

# TiDB CA 证书（如使用自定义 CA，取消注释并放入 certs/ 目录）
# COPY certs/tidb-ca.pem /app/certs/tidb-ca.pem
# ENV TIDB_CA_PATH=/app/certs/tidb-ca.pem

# Render 会自动注入 PORT 环境变量
EXPOSE 8000

# 启动命令（host 必须 0.0.0.0，Render 才能访问）
CMD ["uvicorn", "step7_api_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
