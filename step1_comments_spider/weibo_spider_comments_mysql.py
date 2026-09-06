#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import random
import requests
import pymysql
import logging
import sys
import json
import re
import html
import os
from urllib.parse import urlparse, parse_qs, unquote

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

# 数据库配置
DB_CONFIG = {
    'host': os.getenv('MYSQL_HOST', '127.0.0.1'),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', ''),
    'db': os.getenv('MYSQL_DATABASE', 'weibo_comments'),
    'charset': 'utf8mb4'
}

# 微博Cookie - 从环境变量读取（GitHub Actions 用 WEIBO_COOKIE secret）
WEIBO_COOKIE = os.getenv('WEIBO_COOKIE', '')

# 移动端API头
MOBILE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1",
    "Cookie": WEIBO_COOKIE,
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://m.weibo.cn/"
}

def clean_html_tags(text):
    """清除HTML标签"""
    if not text:
        return ""
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text)

def test_db_connection():
    """测试数据库连接"""
    try:
        with pymysql.connect(**DB_CONFIG) as db:
            logging.info("✅ 数据库连接成功")
            return True
    except pymysql.err.OperationalError as e:
        logging.error(f"❌ 数据库连接失败: {e}")
        logging.error("请检查以下配置:")
        logging.error(f"主机: {DB_CONFIG['host']}")
        logging.error(f"用户: {DB_CONFIG['user']}")
        logging.error(f"数据库: {DB_CONFIG['db']}")
        logging.error(f"错误详情: {str(e)}")
        return False
    except Exception as e:
        logging.error(f"❌ 未知数据库错误: {e}")
        return False

def get_weibo_url(index):
    """从数据库获取微博URL"""
    try:
        with pymysql.connect(**DB_CONFIG,
            cursorclass=pymysql.cursors.DictCursor) as db:
            with db.cursor() as cursor:
                cursor.execute("SELECT url FROM weibo_urls WHERE id = %s", (index,))
                result = cursor.fetchone()
                
                if result:
                    logging.info(f"✅ 成功获取微博 {index} 的URL")
                    return result['url']
                else:
                    logging.warning(f"⚠️ 未找到微博 {index} 的URL")
                    logging.warning("请确保数据库中存在该ID的记录:")
                    logging.warning(f"示例SQL: INSERT INTO weibo_urls (id, url) VALUES ({index}, '你的微博URL');")
                    return None
    except pymysql.err.ProgrammingError as e:
        if "doesn't exist" in str(e):
            logging.error(f"❌ 表不存在错误: {e}")
            logging.error("请创建表: CREATE TABLE weibo_urls (id INT PRIMARY KEY, url VARCHAR(500) NOT NULL);")
        else:
            logging.error(f"❌ SQL错误: {e}")
        return None
    except Exception as e:
        logging.error(f"❌ 获取URL失败: {e}")
        return None

def create_comments_table(index):
    """创建评论存储表（确保表结构正确）"""
    try:
        with pymysql.connect(**DB_CONFIG) as db:
            with db.cursor() as cursor:
                table_name = f"comments_{index}"
                
                # 先删除旧表（如果存在）以确保新结构
                cursor.execute(f"DROP TABLE IF EXISTS `{table_name}`")
                
                # 创建新表（包含所有需要的列）
                cursor.execute(f"""
                    CREATE TABLE `{table_name}` (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id VARCHAR(50),
                        username VARCHAR(100),  # 确保列名正确
                        comment TEXT,
                        like_count INT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
                logging.info(f"✅ 表 {table_name} 创建成功（新结构）")
                return True
    except Exception as e:
        logging.error(f"❌ 创建表失败: {e}")
        return False

def save_comment(index, user_id, username, comment, like_count):
    """保存评论到数据库"""
    try:
        with pymysql.connect(**DB_CONFIG) as db:
            with db.cursor() as cursor:
                table_name = f"comments_{index}"
                cursor.execute(f"""
                    INSERT INTO `{table_name}` (user_id, username, comment, like_count)
                    VALUES (%s, %s, %s, %s)
                """, (user_id, username, comment, like_count))
                db.commit()
                logging.debug(f"💾 保存评论: {comment[:30]}...")
                return True
    except Exception as e:
        logging.error(f"❌ 保存评论失败: {e}")
        return False

def extract_weibo_id(url):
    """从微博URL中提取微博ID"""
    try:
        # 解码URL以防编码问题
        decoded_url = unquote(url)
        
        # 尝试从URL中直接获取ID
        parsed = urlparse(decoded_url)
        path_segments = parsed.path.strip('/').split('/')
        
        # 检查是否是移动端URL格式：/detail/{weibo_id}
        if 'detail' in path_segments:
            weibo_id = path_segments[-1]
            if weibo_id.isdigit():
                return weibo_id
        
        # 检查是否是移动端URL格式：/status/{weibo_id}
        if 'status' in path_segments:
            weibo_id = path_segments[-1]
            if weibo_id.isdigit():
                return weibo_id
        
        # 尝试从查询参数中获取ID
        query_params = parse_qs(parsed.query)
        
        # 优先尝试获取mid参数
        if 'mid' in query_params:
            weibo_id = query_params['mid'][0]
            if weibo_id.isdigit():
                return weibo_id
        
        # 尝试获取id参数
        if 'id' in query_params:
            weibo_id = query_params['id'][0]
            if weibo_id.isdigit():
                return weibo_id
        
        # 尝试从URL末尾提取数字ID
        match = re.search(r'(\d{10,})$', parsed.path)
        if match:
            return match.group(1)
        
        # 尝试从URL中提取短ID（base62格式）
        match = re.search(r'[^a-zA-Z0-9]([a-zA-Z0-9]{9})$', parsed.path)
        if match:
            base62_id = match.group(1)
            logging.info(f"🔍 检测到短ID格式: {base62_id}")
            return get_mid_from_short_id(base62_id)
        
        logging.error(f"❌ 无法从URL提取微博ID: {url}")
        return None
    except Exception as e:
        logging.error(f"❌ 提取微博ID出错: {e}")
        return None

def get_mid_from_short_id(short_id):
    """将短ID(base62)转换为数字ID(mid)"""
    try:
        url = f"https://m.weibo.cn/status/{short_id}"
        logging.info(f"🌐 请求短ID转换URL: {url}")
        
        response = requests.get(url, headers=MOBILE_HEADERS, timeout=15)
        response.raise_for_status()
        
        # 从响应中提取数字ID
        match = re.search(r'"id":\s*"(\d{16,})"', response.text)
        if match:
            mid = match.group(1)
            logging.info(f"✅ 成功转换短ID: {short_id} -> {mid}")
            return mid
        
        # 尝试另一种模式
        match = re.search(r'weibo\.com/\d+/(\d{16,})', response.text)
        if match:
            mid = match.group(1)
            logging.info(f"✅ 成功提取数字ID: {mid}")
            return mid
        
        logging.error("❌ 无法从页面提取数字ID")
        return None
    except Exception as e:
        logging.error(f"❌ 短ID转换失败: {e}")
        return None

def get_comments_from_api(weibo_id, max_id=None):
    """从移动端API获取评论数据"""
    if max_id and max_id != "0":
        url = f"https://m.weibo.cn/comments/hotflow?id={weibo_id}&mid={weibo_id}&max_id={max_id}&max_id_type=0"
    else:
        url = f"https://m.weibo.cn/comments/hotflow?id={weibo_id}&mid={weibo_id}&max_id_type=0"
    
    logging.info(f"🌐 请求API: {url}")
    
    try:
        response = requests.get(url, headers=MOBILE_HEADERS, timeout=15)
        response.raise_for_status()
        
        # 检查响应内容
        if response.text.strip() == "":
            logging.error("❌ API返回空响应")
            return None
        
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ API请求失败: {e}")
        return None
    except json.JSONDecodeError:
        logging.error(f"❌ JSON解析失败，原始响应: {response.text[:200]}...")
        return None

def crawl_comments(url, index):
    """爬取微博评论（使用移动端API）"""
    if not url:
        logging.error("❌ URL为空，无法爬取")
        return 0
    
    logging.info(f"🌐 开始爬取微博 {index}: {url}")
    
    # 从URL中提取微博ID
    weibo_id = extract_weibo_id(url)
    if not weibo_id:
        # 尝试从URL末尾直接提取数字ID
        match = re.search(r'(\d{16,})$', url)
        if match:
            weibo_id = match.group(1)
            logging.info(f"✅ 从URL末尾提取到微博ID: {weibo_id}")
        else:
            logging.error("❌ 无法获取微博ID，停止爬取")
            return 0
    
    logging.info(f"🔍 使用微博ID: {weibo_id}")
    
    comments_data = []
    max_id = None
    page = 1
    total_comments = 0
    max_retries = 3
    
    while True:
        logging.info(f"📖 正在获取第 {page} 页评论...")
        
        retry_count = 0
        data = None
        
        while retry_count < max_retries:
            data = get_comments_from_api(weibo_id, max_id)
            if data:
                break
            retry_count += 1
            logging.warning(f"⚠️ 第 {retry_count} 次重试...")
            time.sleep(random.uniform(3, 8))
        
        if not data:
            logging.error("❌ 多次尝试后仍无法获取数据，终止抓取")
            break
        
        # 检查API返回状态
        if data.get("ok") != 1:
            error_msg = data.get("msg", "未知错误")
            logging.error(f"❌ API返回错误: {error_msg}")
            
            # 如果是请求太频繁的错误，等待一段时间再重试
            if "请求过于频繁" in error_msg or "max_id" in error_msg:
                wait_time = random.uniform(15, 30)
                logging.warning(f"⏳ 检测到请求限制，等待 {wait_time:.1f} 秒...")
                time.sleep(wait_time)
                continue
            else:
                break
        
        # 解析评论数据
        comment_list = data.get("data", {}).get("data", [])
        if not comment_list:
            logging.info("✅ 没有更多评论")
            break
        
        logging.info(f"✅ 本页获取到 {len(comment_list)} 条评论")
        
        for comment in comment_list:
            try:
                # 处理特殊字符和HTML实体
                content = comment.get("text", "")
                content = html.unescape(content)
                content = clean_html_tags(content)
                
                # 保存评论到数据库
                if save_comment(
                    index,
                    str(comment["user"]["id"]),  # 确保user_id是字符串
                    comment["user"]["screen_name"],
                    content,
                    comment.get("like_count", 0)
                ):
                    total_comments += 1
            except KeyError as e:
                logging.warning(f"⚠️ 解析评论时缺少关键字段: {e}")
            except Exception as e:
                logging.error(f"❌ 保存评论时出错: {e}")
        
        # 检查是否有下一页
        max_id = data.get("data", {}).get("max_id")
        if not max_id or max_id == "0" or max_id == 0:
            logging.info("✅ 已到最后一页")
            break
        
        page += 1
        # 随机延迟防止被封
        delay = random.uniform(8, 20)
        logging.info(f"⏳ 等待 {delay:.2f} 秒后继续...")
        time.sleep(delay)
    
    logging.info(f"🎉 微博 {index} 爬取完成! 共获取 {total_comments} 条评论")
    return total_comments

def main():
    logging.info("\n" + "="*60)
    logging.info("微博评论爬虫启动（移动端API版）")
    logging.info("="*60)
    
    # 验证Cookie
    if WEIBO_COOKIE == 'YOUR_ACTUAL_WEIBO_COOKIE':
        logging.error("❌ 请更新WEIBO_COOKIE配置")
        logging.error("从浏览器获取有效的微博Cookie")
        return
    
    # 测试数据库连接
    if not test_db_connection():
        return
    
    # 需要爬取的微博ID列表
    weibo_ids = [1, 2, 3, 4, 5,]
    total_all_comments = 0
    
    for index in weibo_ids:
        logging.info("\n" + "="*60)
        logging.info(f"开始处理微博 {index}")
        logging.info("="*60)
        
        url = get_weibo_url(index)
        if not url:
            continue
            
        if create_comments_table(index):
            comments_count = crawl_comments(url, index)
            total_all_comments += comments_count
        else:
            logging.error(f"❌ 无法为微博 {index} 创建表")
    
    logging.info("\n" + "="*60)
    logging.info(f"所有微博处理完成! 共爬取 {total_all_comments} 条评论")
    logging.info("="*60)

if __name__ == '__main__':
    main()