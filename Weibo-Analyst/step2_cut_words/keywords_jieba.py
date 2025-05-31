#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博评论关键词提取
"""
from jieba import analyse
import logging
import os

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 关键词提取配置
def extract_keywords(weibo_ids):
    """为每个微博提取关键词"""
    try:
        # 创建存储目录
        os.makedirs("keywords", exist_ok=True)
        
        # 允许的词性（名词、动词、形容词等）
        allow_pos = ('ns', 'nr', 'nt', 'nz', 'nl', 'n', 'vn', 'vd', 'vg', 'v', 'vf', 'a', 'an', 'i')
        
        for index in weibo_ids:
            input_file = f"cut_data/data_full_{index}.dat"
            output_file = f"keywords/data_keywords_{index}.dat"
            
            if not os.path.exists(input_file):
                logging.warning(f"⚠️ 分词文件不存在: {input_file}")
                continue
                
            logging.info(f"🔍 开始提取微博 {index} 的关键词...")
            
            with open(input_file, "r", encoding='utf-8') as fin, \
                 open(output_file, "w", encoding='utf-8') as fout:
                
                line_count = 0
                for line in fin:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # 提取关键词（每条评论单独处理）
                    keywords = analyse.extract_tags(line, allowPOS=allow_pos)
                    if keywords:
                        fout.write(' '.join(keywords) + '\n')
                    
                    line_count += 1
                    if line_count % 100 == 0:
                        logging.info(f"📌 已处理 {line_count} 条评论")
            
            logging.info(f"✅ 微博 {index} 关键词提取完成!")
            logging.info(f"💾 结果保存至: {output_file}")
        
        return True
    except Exception as e:
        logging.error(f"❌ 关键词提取失败: {e}")
        return False

if __name__ == '__main__':
    # 需要处理的微博ID列表（与爬虫一致）
    weibo_ids = [101, 102, 103, 104, 105]
    
    logging.info("\n" + "="*60)
    logging.info("微博评论关键词提取启动")
    logging.info("="*60)
    
    # 执行关键词提取
    if extract_keywords(weibo_ids):
        logging.info("\n🎉 所有微博关键词提取完成!")
    else:
        logging.error("\n❌ 处理过程中遇到错误")