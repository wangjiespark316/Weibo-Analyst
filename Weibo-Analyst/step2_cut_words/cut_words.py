#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博评论分词处理
"""
import jieba
import pymysql
import logging
import os

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 数据库配置（与爬虫一致）
DB_CONFIG = {
    'host': 'host.docker.internal',
    'user': 'root',
    'password': '12345abc',
    'db': 'weibo_comments',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

# 加载词典和停用词
def load_resources():
    """加载分词词典和停用词"""
    try:
        jieba.load_userdict("SogouLabDic.txt")
        jieba.load_userdict("dict_baidu_utf8.txt")
        jieba.load_userdict("dict_pangu.txt")
        jieba.load_userdict("dict_sougou_utf8.txt")
        jieba.load_userdict("dict_tencent_utf8.txt")
        jieba.load_userdict("my_dict.txt")
        logging.info("✅ 自定义词典加载成功")
        
        with open('Stopword.txt', 'r', encoding='utf-8') as f:
            stopwords = {line.strip() for line in f}
        logging.info(f"✅ 停用词表加载成功，共 {len(stopwords)} 个停用词")
        return stopwords
    except Exception as e:
        logging.error(f"❌ 资源加载失败: {e}")
        return None

def process_comments(weibo_ids, stopwords):
    """处理指定微博的评论"""
    try:
        # 创建存储目录
        os.makedirs("cut_data", exist_ok=True)
        
        with pymysql.connect(**DB_CONFIG) as db:
            for index in weibo_ids:
                table_name = f"comments_{index}"
                output_file = f"cut_data/data_full_{index}.dat"
                
                logging.info(f"📊 开始处理微博 {index} 的评论...")
                
                # 获取评论数据
                with db.cursor() as cursor:
                    cursor.execute(f"SELECT comment FROM `{table_name}`")
                    comments = cursor.fetchall()
                
                if not comments:
                    logging.warning(f"⚠️ 微博 {index} 没有评论数据")
                    continue
                
                # 处理并保存分词结果
                with open(output_file, "w", encoding='utf-8') as fo:
                    for i, comment in enumerate(comments):
                        text = comment['comment']
                        seg_list = jieba.cut(text)
                        
                        # 过滤停用词并写入文件
                        filtered_words = [word for word in seg_list if word.strip() and word not in stopwords]
                        fo.write(' '.join(filtered_words) + '\n')
                        
                        if (i + 1) % 100 == 0:
                            logging.info(f"✂️ 已处理 {i+1}/{len(comments)} 条评论")
                
                logging.info(f"✅ 微博 {index} 分词完成! 共处理 {len(comments)} 条评论")
                logging.info(f"💾 结果保存至: {output_file}")
                
        return True
    except pymysql.err.ProgrammingError as e:
        if "doesn't exist" in str(e):
            logging.error(f"❌ 表不存在: {table_name}")
            logging.error("请先运行爬虫程序收集评论数据")
        else:
            logging.error(f"❌ 数据库错误: {e}")
        return False
    except Exception as e:
        logging.error(f"❌ 处理失败: {e}")
        return False

if __name__ == '__main__':
    # 需要处理的微博ID列表（与爬虫一致）
    weibo_ids = [101, 102, 103, 104, 105]
    
    logging.info("\n" + "="*60)
    logging.info("微博评论分词处理启动")
    logging.info("="*60)
    
    # 加载词典资源
    stopwords = load_resources()
    if not stopwords:
        exit(1)
    
    # 处理评论
    if process_comments(weibo_ids, stopwords):
        logging.info("\n🎉 所有微博评论分词处理完成!")
    else:
        logging.error("\n❌ 处理过程中遇到错误")