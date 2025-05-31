微博评论爬虫与分析系统
这是一个用于爬取微博评论、存储到数据库，并进行文本分析和关键词提取的Python工具集。

项目概述
该项目包含三个主要模块：

微博评论爬虫 - 从指定微博URL爬取评论并存储到MySQL数据库

评论分词处理 - 对数据库中的评论进行分词和停用词过滤

关键词提取 - 从分词结果中提取关键词

功能特点
✅ 支持微博移动端API爬取评论

✅ 自动从URL中提取微博ID

✅ 支持分页爬取和反爬虫策略

✅ 数据库存储结构化评论数据

✅ 自定义词典支持（搜狗、百度、腾讯等）

✅ 停用词过滤

✅ 基于词性的关键词提取

快速开始
环境要求
Python 3.7+

MySQL 5.7+

依赖库：requests, pymysql, jieba

安装依赖
bash
pip install -r requirements.txt
配置说明
在 weibo_spider_comments_mysql.py 中配置数据库连接信息：

python
DB_CONFIG = {
    'host': 'host.docker.internal',  # Docker环境使用
    'user': 'root',
    'password': '12345abc',
    'db': 'weibo_comments',
    'charset': 'utf8mb4'
}
更新微博Cookie：

python
WEIBO_COOKIE = 'YOUR_WEIBO_COOKIE_HERE'
在数据库中创建微博URL表：

sql
CREATE TABLE weibo_urls (
    id INT PRIMARY KEY, 
    url VARCHAR(500) NOT NULL
);
添加要爬取的微博URL：

sql
INSERT INTO weibo_urls (id, url) VALUES 
(101, 'https://weibo.com/xxx'),
(102, 'https://weibo.com/yyy');
运行流程
运行爬虫 (收集评论数据)

bash
python weibo_spider_comments_mysql.py
运行分词处理 (处理评论数据)

bash
python cut_words.py
运行关键词提取 (分析分词结果)

bash
python keywords_jieba.py
文件说明
文件名	功能描述
weibo_spider_comments_mysql.py	微博评论爬虫主程序
cut_words.py	评论分词处理程序
keywords_jieba.py	关键词提取程序
SogouLabDic.txt	搜狗词典文件
dict_*.txt	自定义词典文件
Stopword.txt	停用词表
my_dict.txt	用户自定义词典
输出文件
cut_data/data_full_{id}.dat - 分词结果

keywords/data_keywords_{id}.dat - 关键词提取结果

注意事项
微博Cookie需要定期更新，否则爬虫可能无法正常工作

确保MySQL服务已启动并正确配置

爬虫包含随机延迟机制以避免被封IP

分词处理需要依赖词典文件，请确保文件存在

支持处理微博短链接(自动转换为长ID)

自定义配置
修改weibo_ids列表选择要处理的微博

在my_dict.txt中添加领域特定词汇

调整MOBILE_HEADERS中的请求头参数

修改分词时的词性过滤规则

贡献指南
欢迎提交Issue和Pull Request！对于新功能或问题修复：


许可证
本项目采用 MIT 许可证 - 详情请参阅 LICENSE 文件

# Weibo-Analyst
