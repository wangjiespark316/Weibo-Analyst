微博分析师（Weibo Analyst）
微博评论爬虫与分析系统 是一个基于 Python 的工具集，用于从微博爬取评论、存储至数据库，并进行文本分析与关键词提取。

🧩 项目概述
本项目包含三个主要模块：

微博评论爬虫：从指定微博 URL 爬取评论并存储至 MySQL 数据库

评论分词处理：对评论进行分词与停用词过滤

关键词提取：基于分词结果提取关键词

✨ 功能特点
✅ 支持调用微博移动端 API 获取评论

✅ 自动从微博 URL 中提取微博 ID

✅ 支持分页爬取与反爬虫策略（如 User-Agent 随机化、请求间隔）

✅ 评论数据结构化存入 MySQL

✅ 支持多搜索引擎（搜狗、百度、腾讯）关键词挖掘

✅ 停用词过滤与自定义词典支持

✅ 基于词性的关键词提取逻辑

🚀 快速开始
✅ 环境要求
Python 3.7+

MySQL 5.7+

依赖库：requests、pymysql、jieba

📦 安装依赖
bash
复制
编辑
pip install -r requirements.txt
⚙️ 配置说明
在 weibo_spider_comments_mysql.py 中配置数据库连接信息：

python
复制
编辑
DB_CONFIG = {
    'host': 'host.docker.internal',  # Docker 环境使用
    'user': 'root',
    'password': '12345abc',
    'db': 'weibo_comments',
    'charset': 'utf8mb4'
}
设置微博 Cookie：

python
复制
编辑
WEIBO_COOKIE = 'YOUR_WEIBO_COOKIE_HERE'
🗄️ 数据库配置
创建微博 URL 表
sql
复制
编辑
CREATE TABLE weibo_urls (
    id INT PRIMARY KEY,
    url VARCHAR(500) NOT NULL
);
添加待爬取的微博 URL：
sql
复制
编辑
INSERT INTO weibo_urls (id, url) VALUES
(101, 'https://weibo.com/xxx'),
(102, 'https://weibo.com/yyy');
🔁 运行流程
1. 运行爬虫（收集评论）
bash
复制
编辑
python weibo_spider_comments_mysql.py
2. 分词处理（处理评论数据）
bash
复制
编辑
python cut_words.py
3. 关键词提取（分析分词结果）
bash
复制
编辑
python keywords_jieba.py
📂 文件说明
文件名	功能描述
weibo_spider_comments_mysql.py	微博评论爬虫主程序
cut_words.py	评论分词处理
keywords_jieba.py	关键词提取程序
SogouLabDic.txt	搜狗词典文件
dict_*.txt	自定义词典文件
Stopword.txt	停用词列表
my_dict.txt	用户自定义词典
cut_data/data_full_{id}.dat	分词结果文件
keywords/data_keywords_{id}.dat	关键词提取结果

⚠️ 注意事项
微博 Cookie 需要定期更新，防止爬虫失效

确保 MySQL 服务已正常启动并配置正确

爬虫内置随机延迟机制，避免单 IP 被封禁

分词依赖多个词典文件，运行前需确保文件存在

支持自动转换微博短链接为长 ID

可通过配置 weibo_ids 指定处理的微博 ID

可在 my_dict.txt 中添加行业/领域术语

可调整 MOBILE_HEADERS 请求头参数

可修改分词时的词性过滤逻辑

🙌 贡献指南
欢迎提交 Issue 和 Pull Request！对于新功能、Bug 修复等，欢迎一起完善本项目。

📄 许可证
本项目采用 MIT 许可证 - 详情请参阅 LICENSE.md 文件。
