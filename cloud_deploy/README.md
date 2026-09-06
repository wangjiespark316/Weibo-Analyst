# 微博舆情系统 - MySQL 上云部署指南

> 架构：TiDB Cloud（免费 MySQL）+ Render（免费 API）+ GitHub Actions（免费定时爬虫）
> 0 成本 7×24 常驻，数据量 < 1GB

---

## 架构总览

```
[GitHub Actions]                [TiDB Cloud]               [Render]
 定时爬虫 (cron)   ──写入──▶  免费 MySQL 集群   ◀──读取──  FastAPI 服务
 每天拉微博数据                     (云上常驻)               (免费 750h/月)
      │                                                      │
      └────────────── 日报推送（飞书群机器人 webhook）─────────┘
```

---

## 已完成的自动化改造

| 文件 | 改动 |
|---|---|
| `cloud_deploy/cloud_db.py` | 统一连接模块，支持 DATABASE_URL + TLS，本地/云端自动切换 |
| `cloud_deploy/sql/weibo_core_tables_tidb.sql` | TiDB 兼容版数据导出（4 张核心表，1.8MB） |
| `cloud_deploy/Dockerfile` | Render 部署用 Dockerfile |
| `cloud_deploy/requirements.txt` | 云端依赖 |
| `cloud_deploy/.env.example` | 环境变量模板 |
| `.github/workflows/crawler.yml` | 定时爬虫 GitHub Actions |
| `step7_api_service/database.py` | 支持 DATABASE_URL 环境变量 + TiDB TLS |
| `step7_api_service/main.py` | 支持 PORT 环境变量 + 云端 CORS |

---

## 第一步：TiDB Cloud 建免费集群（你操作）

1. 登录 https://tidbcloud.com → **Create Cluster**
2. 选 **Serverless**（免费档）
3. 区域选 **AWS Singapore**（国内访问友好）
4. 创建完成后点 **Connect**：
   - 选择 **Connect with a SQL client**
   - 复制连接串，形如：`mysql://<user>:<password>@<host>.aws.tidbcloud.com:4000/test?ssl_mode=VERIFY_IDENTITY`
   - 下载 CA 证书（可选，pymysql 用系统 CA 即可）
5. 用 mysql CLI 或 Sequel Ace 连接后，创建数据库：
   ```sql
   CREATE DATABASE weibo_comments CHARACTER SET utf8mb4;
   ```
6. 导入数据（在项目根目录执行）：
   ```bash
   mysql -h <host> -P 4000 -u <user> -p weibo_comments < cloud_deploy/sql/weibo_core_tables_tidb.sql
   ```
   或在 TiDB Cloud 控制台的 **SQL Editor** 中粘贴执行。

> 免费额度：5GiB 行存储 + 50M RU/月，当前数据仅 3.75MB，远用不完。

---

## 第二步：本地验证云端连接（我可以协助）

设置环境变量后本地运行 FastAPI，验证能读到 TiDB 数据：

```bash
export DATABASE_URL="mysql://<user>:<password>@<host>.aws.tidbcloud.com:4000/weibo_comments?ssl-mode=VERIFY_IDENTITY"

# 测试连接
.venv/bin/python cloud_deploy/cloud_db.py

# 启动 FastAPI
.venv/bin/uvicorn step7_api_service.main:app --host 127.0.0.1 --port 8000

# 验证接口
curl http://127.0.0.1:8000/api/hot-weibo?limit=5
```

---

## 第三步：Render 部署 FastAPI（你操作）

1. 登录 https://render.com → **New + → Web Service**
2. 连接你的 GitHub 仓库
3. 配置：
   - **Runtime**: Docker
   - **Dockerfile Path**: `cloud_deploy/Dockerfile`
   - **Instance Type**: Free
4. 环境变量（Advanced → Environment Variables）：
   | Key | Value |
   |---|---|
   | `DATABASE_URL` | TiDB 连接串（含密码） |
5. 点 **Deploy**，等待 2-3 分钟
6. 部署完成后访问：`https://<服务名>.onrender.com/api/hot-weibo`

### 防休眠（重要）

Render 免费实例 15 分钟无请求就休眠。用 UptimeRobot 定时唤醒：
1. 注册 https://uptimerobot.com（免费）
2. Add New Monitor → Type: HTTP(s)
3. URL: `https://<服务名>.onrender.com/health`
4. 间隔: 10 分钟

---

## 第四步：GitHub Actions 定时爬虫（你操作）

1. 把代码推送到 GitHub：
   ```bash
   git init
   git add .
   git commit -m "weibo sentiment service"
   git branch -M main
   git remote add origin git@github.com:<你的用户名>/<仓库名>.git
   git push -u origin main
   ```

2. 配置 Secrets（仓库 Settings → Secrets and variables → Actions）：
   | Secret 名 | 值 |
   |---|---|
   | `DATABASE_URL` | TiDB 连接串 |
   | `WEIBO_COOKIE` | 微博登录 Cookie |

3. 手动触发一次测试：Actions → weibo-crawler → Run workflow

4. 之后每天北京时间 09:20 自动运行

---

## 第五步：飞书日报推送（可选）

1. 在飞书群添加自定义机器人，复制 Webhook
2. GitHub Secrets 添加 `FEISHU_WEBHOOK`
3. 在 crawler.yml 中加飞书推送步骤（参考部署手册第 6 节）

---

## 验证清单

- [ ] TiDB 集群连接成功，4 张核心表数据已导入
- [ ] 本地用 DATABASE_URL 运行 FastAPI，5 个接口返回云库数据
- [ ] Render 部署成功，公网访问 `/api/hot-weibo` 返回数据
- [ ] UptimeRobot 监控显示服务在线
- [ ] GitHub Actions 手动触发成功，爬虫写入 TiDB
- [ ] 日报生成并存储在 `step9_scheduler/reports/`

---

## 常见坑

| 现象 | 原因 | 解决 |
|---|---|---|
| 连接报 SSL 错误 | TiDB Serverless 强制 TLS | 连接串加 `ssl-mode=VERIFY_IDENTITY` |
| Render 返回 503 | 服务休眠冷启动 | UptimeRobot 间隔 < 15 分钟 |
| 爬虫在 Actions 失败 | 微博反爬/缺 Cookie | 配置 `WEIBO_COOKIE` secret |
| API 第一次请求慢 | TiDB Serverless 冷启动 | 正常，几秒后恢复 |
