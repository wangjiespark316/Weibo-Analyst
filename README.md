# Weibo-Analyst · 微博舆情分析 Dashboard

微博评论采集、分词、词云、情感 / LDA 分析与可视化的完整项目，含 FastAPI 后端与 Vue 看板。

- 在线地址：https://analyst.vertexlab.tech
- 前端：`step10_agent_app/dashboard/`（Vue 3 + Vite + Element Plus + ECharts）
- 后端：`step7_api_service/`（FastAPI，路由见 `routers/`，数据来自 MySQL `weibo_comments`）
- 数据处理：`step1` ~ `step9`（爬虫、分词、词云、情感、LDA、调度）

## 本地运行

- 后端：`cd step7_api_service`，复制 `config.py.example` 为 `config.py` 填数据库，`uvicorn main:app --reload`
- 前端：`cd step10_agent_app/dashboard`，`npm install`，`npm run dev`（开发态 `/api` 走 Vite 代理）

## 部署

前端 `npm run build` 产物部署到服务器 `/var/www/analyst`；nginx 托管静态页，
并将 `/api/` 反向代理到后端（当前由服务器端反代在线后端）；
`analyst.vertexlab.tech` 解析到国内服务器，底部含 ICP 备案号。

> 服务器地址、账号、Token、密钥不在仓库记录。
