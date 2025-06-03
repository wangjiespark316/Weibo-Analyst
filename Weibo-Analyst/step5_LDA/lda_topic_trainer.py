# -*- coding: utf-8 -*-
import pymysql
import jieba
import os
import numpy as np
import random
import time
from collections import defaultdict, Counter
import multiprocessing as mp

# 数据库配置
DB_CONFIG = {
    'host': 'host.docker.internal',  # Docker环境使用
    'user': 'root',
    'password': '12345abc',
    'db': 'weibo_comments',
    'charset': 'utf8mb4'
}

class Document:
    __slots__ = ['words', 'length']
    def __init__(self):
        self.words = []
        self.length = 0

class DataPreProcessing:
    def __init__(self, table_name):
        self.docs_count = 0
        self.words_count = 0
        self.docs = []
        self.word2id = {}
        self.id2word = {}
        self.table_name = table_name
        self.stopwords = self.load_stopwords()
        
        # 初始化jieba分词器
        jieba.initialize()

    def load_stopwords(self):
        """加载停用词表"""
        stopwords = set()
        try:
            with open('stopwords.txt', 'r', encoding='utf-8') as f:
                for line in f:
                    stopwords.add(line.strip())
        except FileNotFoundError:
            print("未找到停用词文件，继续无停用词处理")
        return stopwords

    def process_text(self, text):
        """中文文本预处理：分词+过滤停用词和短词"""
        # 使用jieba进行中文分词
        words = jieba.lcut(text)
        return [word for word in words if len(word) > 1 and word not in self.stopwords]

    def parse_data(self):
        print(f"载入数据表: {self.table_name}")
        
        # 连接数据库
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        try:
            # 查询评论数据
            cursor.execute(f"SELECT comment FROM {self.table_name}")
            comments = [row[0] for row in cursor.fetchall()]
        finally:
            cursor.close()
            conn.close()

        word_freq = Counter()
        
        # 第一遍扫描：构建词表
        for comment in comments:
            if not comment:
                continue
            tokens = self.process_text(comment)
            word_freq.update(tokens)
        
        # 过滤低频词 (词频<3)
        valid_words = {word for word, freq in word_freq.items() if freq >= 3}
        self.word2id = {}
        self.id2word = {}
        
        # 第二遍扫描：构建文档和词表
        for comment in comments:
            if not comment:
                continue
                
            tokens = self.process_text(comment)
            if not tokens:
                continue
                
            doc = Document()
            for word in tokens:
                if word in valid_words:
                    if word not in self.word2id:
                        word_id = len(self.word2id)
                        self.word2id[word] = word_id
                        self.id2word[word_id] = word
                    doc.words.append(self.word2id[word])
            
            doc.length = len(doc.words)
            if doc.length > 5:  # 过滤短文档
                self.docs.append(doc)
        
        # 更新最终词表大小
        self.words_count = len(self.word2id)
        self.docs_count = len(self.docs)
        
        print(f"表: {self.table_name} | 过滤后词数: {self.words_count}")
        print(f"有效文档数: {self.docs_count} (平均长度: {sum(d.length for d in self.docs)//self.docs_count if self.docs_count > 0 else 0})")
        return self.docs_count > 0  # 返回是否有有效数据

class LDAModel:
    def __init__(self, dpre, K=10, alpha=0.1, beta=0.01, iterations=1000, topN=20):
        self.dpre = dpre
        self.K = K
        self.alpha = alpha
        self.beta = beta
        self.iterations = iterations
        self.topN = topN
        self.rng = np.random.default_rng(42)
        
        # 稀疏矩阵存储
        self.nw = np.zeros((dpre.words_count, K), dtype=np.int32)
        self.nd = np.zeros((dpre.docs_count, K), dtype=np.int32)
        self.nwsum = np.zeros(K, dtype=np.int32)
        self.ndsum = np.zeros(dpre.docs_count, dtype=np.int32)
        self.Z = []

        # 初始化主题分配
        print(f"初始化主题分配 [主题数={K}]...")
        for m, doc in enumerate(dpre.docs):
            z_current = []
            for w in doc.words:
                topic = self.rng.integers(0, K)
                z_current.append(topic)
                self.nw[w, topic] += 1
                self.nd[m, topic] += 1
                self.nwsum[topic] += 1
            self.ndsum[m] = doc.length
            self.Z.append(z_current)

        self.theta = np.zeros((dpre.docs_count, K))
        self.phi = np.zeros((K, dpre.words_count))

    def train(self):
        print(f"开始LDA训练 [主题数={self.K}, 迭代={self.iterations}]...")
        start_time = time.time()
        
        for it in range(self.iterations):
            for m in range(self.dpre.docs_count):
                doc = self.dpre.docs[m]
                for n in range(doc.length):
                    w = doc.words[n]
                    topic = self.Z[m][n]
                    
                    # 移除当前词计数
                    self.nw[w, topic] -= 1
                    self.nd[m, topic] -= 1
                    self.nwsum[topic] -= 1
                    
                    # 计算主题概率分布
                    p_topic = (self.nw[w, :] + self.beta) * (self.nd[m, :] + self.alpha)
                    p_topic /= (self.nwsum + self.dpre.words_count * self.beta) * (self.ndsum[m] + self.K * self.alpha)
                    
                    # 归一化并采样新主题
                    p_topic /= np.sum(p_topic)
                    new_topic = self.rng.choice(self.K, p=p_topic)
                    
                    # 更新计数
                    self.Z[m][n] = new_topic
                    self.nw[w, new_topic] += 1
                    self.nd[m, new_topic] += 1
                    self.nwsum[new_topic] += 1

            if (it + 1) % 50 == 0 or it == 0:
                elapsed = time.time() - start_time
                print(f"迭代 {it+1}/{self.iterations} | 用时: {elapsed:.1f}s | 主题分布熵: {self.topic_entropy():.3f}")

        self.compute_theta_phi()
        print(f"训练完成! 总用时: {time.time()-start_time:.1f}秒")

    def topic_entropy(self):
        """计算主题分布熵以监控收敛"""
        topic_dist = self.nwsum / np.sum(self.nwsum)
        return -np.sum(topic_dist * np.log(topic_dist + 1e-9))

    def compute_theta_phi(self):
        """计算文档-主题和主题-词分布"""
        self.theta = (self.nd + self.alpha) / (self.ndsum[:, None] + self.K * self.alpha)
        self.phi = (self.nw.T + self.beta) / (self.nwsum[:, None] + self.dpre.words_count * self.beta)

    def save_results(self, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        print(f"保存结果到: {output_dir}")
        
        # 1. 主题关键词
        with open(os.path.join(output_dir, "topics_keywords.txt"), "w", encoding="utf-8") as f:
            for k in range(self.K):
                top_indices = np.argsort(self.phi[k])[::-1][:self.topN]
                top_words = [(self.dpre.id2word[i], self.phi[k, i]) for i in top_indices]
                f.write(f"主题#{k} (权重: {self.nwsum[k]/np.sum(self.nwsum):.3f}):\n")
                for word, prob in top_words:
                    f.write(f"  {word}: {prob:.4f}\n")
                f.write("\n")
        
        # 2. 文档主题分布
        np.savetxt(os.path.join(output_dir, "doc_topics.csv"), self.theta, delimiter=",")
        
        # 3. 主题可视化 (TSNE降维)
        try:
            from sklearn.manifold import TSNE
            import matplotlib.pyplot as plt
            
            tsne = TSNE(n_components=2, perplexity=min(5, self.K-1), random_state=42)
            topic_emb = tsne.fit_transform(self.phi)
            
            plt.figure(figsize=(12, 10))
            plt.scatter(topic_emb[:, 0], topic_emb[:, 1], s=100, c='r', alpha=0.7)
            for k in range(self.K):
                plt.annotate(f"T{k}", (topic_emb[k, 0], topic_emb[k, 1]), fontsize=12)
            plt.title(f"LDA Topics Visualization - {os.path.basename(output_dir)}")
            plt.savefig(os.path.join(output_dir, "topics_tsne.png"))
            print("生成主题可视化图")
        except ImportError:
            print("警告: 缺少sklearn/matplotlib, 跳过可视化")
        
        # 4. 主题-词矩阵 (稀疏存储)
        np.savez_compressed(os.path.join(output_dir, "topic_word_matrix.npz"), data=self.phi)
        
        print(f"结果保存完成! 包含: 主题关键词/文档分布/可视化")

def process_table(table_name, output_base_dir, K=10, iterations=500):
    """处理单个评论表的函数"""
    print(f"\n{'='*60}")
    print(f"处理表: {table_name}")
    print(f"{'='*60}")
    
    # 创建表专属输出目录
    output_dir = os.path.join(output_base_dir, table_name)
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        # 数据预处理
        dpre = DataPreProcessing(table_name)
        has_data = dpre.parse_data()
        
        if not has_data or dpre.docs_count == 0:
            print(f"表 {table_name} 无有效数据，跳过")
            return
        
        # 自动调整迭代次数
        actual_iter = max(100, min(iterations, 1000))  # 确保在合理范围内
        if dpre.docs_count > 10000:
            actual_iter = 300
        
        # 训练LDA模型
        lda = LDAModel(dpre, K=K, alpha=0.1, beta=0.01, 
                      iterations=actual_iter, topN=15)
        lda.train()
        lda.save_results(output_dir)
        
        print(f"{table_name} 处理完成! 结果保存在: {output_dir}")
    except Exception as e:
        print(f"处理表 {table_name} 时出错: {str(e)}")

if __name__ == "__main__":
    # 配置参数
    OUTPUT_BASE_DIR = "/workspace/step5_LDA/results"
    N_TOPICS = 15
    N_ITER = 500
    
    # 获取所有评论表
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES LIKE 'comments_%'")
        comment_tables = [row[0] for row in cursor.fetchall()]
        print(f"找到评论表: {comment_tables}")
    except Exception as e:
        print(f"数据库连接失败: {str(e)}")
        comment_tables = []
    finally:
        if conn:
            conn.close()
    
    if not comment_tables:
        print("未找到评论表，退出程序")
        exit(1)
    
    # 创建进程池并行处理
    pool = mp.Pool(processes=min(mp.cpu_count(), len(comment_tables)))
    
    # 为每个表启动处理进程
    results = []
    for table in comment_tables:
        res = pool.apply_async(process_table, 
                              args=(table, OUTPUT_BASE_DIR, N_TOPICS, N_ITER))
        results.append(res)
    
    # 等待所有进程完成
    pool.close()
    pool.join()
    
    # 检查结果
    for res in results:
        try:
            res.get()  # 获取结果（如有异常会在此抛出）
        except Exception as e:
            print(f"处理出错: {str(e)}")
    
    print("\n所有表处理完成! 结果保存在:", OUTPUT_BASE_DIR)