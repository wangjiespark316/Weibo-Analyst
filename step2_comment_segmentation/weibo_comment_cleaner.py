# -*- coding: utf-8 -*-
import pymysql
import jieba
import re
import os
import argparse
import configparser
from collections import defaultdict, Counter
from tqdm import tqdm

class WeiboCommentProcessor:
    def __init__(self, config_file='db_config.ini'):
        # 获取当前脚本所在目录
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # 拼接配置文件的完整路径
        config_path = os.path.join(script_dir, config_file)
        
        self.config = self.load_config(config_path)
        self.stopwords = self.load_stopwords()
        self.custom_dict = "custom_dict.txt"
        
        # 加载自定义词典
        custom_dict_path = os.path.join(script_dir, self.custom_dict)
        if os.path.exists(custom_dict_path):
            jieba.load_userdict(custom_dict_path)
    
    def load_config(self, config_file):
        """加载配置文件"""
        config = configparser.ConfigParser()
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"配置文件不存在: {config_file}")
            
        config.read(config_file)
        
        # 添加配置项存在性检查
        if not config.has_section('database'):
            raise ValueError("配置文件中缺少 [database] 部分")

        return {
            'host': config.get('database', 'host', fallback='localhost'),
            'port': config.getint('database', 'port', fallback=3306),
            'user': config.get('database', 'user'),
            'password': config.get('database', 'password'),
            'database': config.get('database', 'database'),
            'charset': config.get('database', 'charset', fallback='utf8mb4')
        }
    
    def load_stopwords(self, stopwords_file='stopwords.txt'):
        """加载停用词表"""
        stopwords = set()
        if os.path.exists(stopwords_file):
            with open(stopwords_file, 'r', encoding='utf-8') as f:
                for line in f:
                    word = line.strip()
                    if word:
                        stopwords.add(word)
        return stopwords
    
    def get_db_connection(self):
        """创建数据库连接"""
        return pymysql.connect(
            host=self.config['host'],
            port=self.config['port'],
            user=self.config['user'],
            password=self.config['password'],
            database=self.config['database'],
            charset=self.config['charset'],
            cursorclass=pymysql.cursors.DictCursor
        )
    
    def clean_comment(self, text):
        """清洗评论文本"""
        if not isinstance(text, str):
            return ""
        
        # 移除URL
        text = re.sub(r'https?://\S+|www\.\S+', '', text)
        # 移除表情符号 [表情]
        text = re.sub(r'\[.*?\]', '', text)
        # 移除话题标签 #话题#
        text = re.sub(r'#.*?#', '', text)
        # 移除@用户
        text = re.sub(r'@\S+', '', text)
        # 移除非中文字符（保留中文和常见标点）
        text = re.sub(r'[^\u4e00-\u9fa5，。！？、；：]', '', text)
        return text.strip()
    
    def tokenize_comment(self, comment):
        """分词处理评论"""
        cleaned_text = self.clean_comment(comment)
        if not cleaned_text:
            return []
        
        # 分词处理
        words = jieba.cut(cleaned_text)
        # 过滤停用词和单字
        filtered_words = [
            word for word in words 
            if word not in self.stopwords and 
               len(word) > 1 and 
               not word.isspace()
        ]
        return filtered_words
    
    def fetch_comments(self):
        connection = self.get_db_connection()
        comments_by_table = defaultdict(list)
        
        try:
            with connection.cursor() as cursor:
                print("获取评论表...")
                cursor.execute("SHOW TABLES LIKE 'comments_%'")
                table_key = cursor.description[0][0]
                comment_tables = [row[table_key] for row in cursor.fetchall()]
                
                print(f"发现 {len(comment_tables)} 个评论表")
                
                for table in tqdm(comment_tables, desc="处理评论表"):
                    try:
                        # 直接使用表名作为标识
                        table_name = table
                        sql = f"SELECT comment FROM `{table}`"
                        cursor.execute(sql)
                        
                        for row in cursor.fetchall():
                            comments_by_table[table_name].append(row['comment'])
                    except Exception as e:
                        print(f"处理表 {table} 时出错: {str(e)}")
                        continue
        
        finally:
            connection.close()
        
        print(f"获取到 {len(comments_by_table)} 个表的评论数据")
        return comments_by_table
    
    def process_comments(self, output_dir, all_comments_filename=None):
        """处理评论并保存结果"""
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
        
        # 获取按表分组的评论
        comments_by_table = self.fetch_comments()
        
        # 准备所有评论的输出文件路径
        all_comments_file = None
        if all_comments_filename:
            # 确保all_comments.txt保存在output_dir目录下
            all_comments_file = os.path.join(output_dir, all_comments_filename)
        
        # 处理每个表的评论
        table_word_counts = {}
        
        # 打开所有评论文件（如果需要）
        all_out = None
        if all_comments_file:
            all_out = open(all_comments_file, 'w', encoding='utf-8')
        
        for table_name, comments in tqdm(comments_by_table.items(), desc="处理表评论"):
            # 使用表名作为文件名基础
            #comments_file = os.path.join(output_dir, f"comments_{table_name}.txt")
            #word_freq_file = os.path.join(output_dir, f"word_freq_{table_name}.txt")

            # 去除表名的前缀 'comments_' (输出的文件名从comments_comments_1.txt变为comments_1.txt)
            table_suffix = table_name.replace("comments_", "")
            comments_file = os.path.join(output_dir, f"comments_{table_suffix}.txt")
            word_freq_file = os.path.join(output_dir, f"word_freq_{table_suffix}.txt")

            
            
            # 词频统计
            word_freq = Counter()
            
            with open(comments_file, 'w', encoding='utf-8') as f_out:
                for comment in comments:
                    tokens = self.tokenize_comment(comment)
                    if not tokens:
                        continue
                    
                    # 写入表特定文件
                    f_out.write(" ".join(tokens) + "\n")
                    
                    # 写入所有评论文件
                    if all_out:
                        all_out.write(" ".join(tokens) + "\n")
                    
                    # 更新词频
                    word_freq.update(tokens)
            
            # 保存当前表的词频统计
            with open(word_freq_file, 'w', encoding='utf-8') as f_freq:
                for word, count in word_freq.most_common(200):
                    f_freq.write(f"{word}\t{count}\n")
            
            # 保存到全局统计
            table_word_counts[table_name] = word_freq
        
        # 关闭所有评论文件
        if all_out:
            all_out.close()
        
        # 保存全局词频统计到输出目录
        global_word_freq_file = os.path.join(output_dir, "global_word_freq.txt")
        self.save_global_word_frequencies(table_word_counts, global_word_freq_file)
        
        print(f"处理完成！所有文件保存在: {output_dir}")
        if all_comments_file:
            print(f"所有评论合并文件: {all_comments_file}")
        print(f"全局词频文件: {global_word_freq_file}")
    
    def save_global_word_frequencies(self, table_word_counts, output_file):
        """保存全局词频统计结果到指定文件"""
        # 合并所有表的词频
        global_freq = Counter()
        for freq in table_word_counts.values():
            global_freq.update(freq)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            for word, count in global_freq.most_common(500):
                f.write(f"{word}\t{count}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='微博评论预处理工具')
    parser.add_argument('--output_dir', type=str, default='weibo_comments', 
                        help='输出目录，所有文件将保存在此目录下')
    parser.add_argument('--all_comments', type=str, default='all_comments.txt',
                        help='所有评论合并文件的名称（将保存在输出目录下）')
    parser.add_argument('--config', type=str, default='db_config.ini',
                        help='数据库配置文件路径')
    parser.add_argument('--stopwords', type=str, default='stopwords.txt',
                        help='停用词文件路径')
    
    args = parser.parse_args()
    
    # 获取当前脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 解析输出目录路径
    output_dir = os.path.join(script_dir, args.output_dir)
    
    processor = WeiboCommentProcessor(config_file=args.config)
    processor.process_comments(
        output_dir=output_dir,
        all_comments_filename=args.all_comments
    )