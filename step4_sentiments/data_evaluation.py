#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博评论情感分析 - 适配实际数据库结构
"""
import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 导入其他模块
from snownlp import SnowNLP
import matplotlib.pyplot as plt
import logging
import pymysql
import numpy as np
import matplotlib as mpl
import warnings

# -------------------- 全局字体配置 --------------------
# 禁用所有 matplotlib 警告
warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib.font_manager")

# 设置默认字体
mpl.rcParams['font.family'] = 'sans-serif'
mpl.rcParams['font.sans-serif'] = ['DejaVu Sans']
mpl.rcParams['axes.unicode_minus'] = False

# 字体路径配置
FONT_PATHS = [
    os.path.join(SCRIPT_DIR, "fonts", "msyh.ttf"),
    os.path.join(SCRIPT_DIR, "fonts", "simhei.ttf"),
    os.path.join(SCRIPT_DIR, "msyh.ttf"),
    "/usr/share/fonts/truetype/microsoft/msyh.ttf",
    "/usr/share/fonts/truetype/msyh.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
]

# 备选字体列表
CHINESE_FONTS = [
    'WenQuanYi Micro Hei', 
    'WenQuanYi Zen Hei', 
    'Noto Sans CJK SC',
    'Microsoft YaHei', 
    'SimHei', 
    'KaiTi', 
    'SimSun',
    'DejaVu Sans'
]

def setup_chinese_font():
    """配置中文字体支持"""
    import matplotlib.font_manager as fm
    from matplotlib import rcParams
    
    # 尝试多种字体路径
    for font_path in FONT_PATHS:
        if os.path.exists(font_path):
            try:
                # 注册字体
                fm.fontManager.addfont(font_path)
                font_prop = fm.FontProperties(fname=font_path)
                font_name = font_prop.get_name()
                
                # 设置全局字体
                rcParams['font.family'] = 'sans-serif'
                rcParams['font.sans-serif'] = [font_name]
                rcParams['axes.unicode_minus'] = False
                
                logging.info(f"✅ 使用中文字体文件: {font_path}")
                return font_prop
            except Exception as e:
                logging.warning(f"⚠️ 字体文件 {font_path} 加载失败: {str(e)}")
    
    # 尝试使用系统字体
    available_fonts = fm.get_font_names()
    for font_name in CHINESE_FONTS:
        if font_name in available_fonts:
            try:
                rcParams['font.family'] = 'sans-serif'
                rcParams['font.sans-serif'] = [font_name]
                rcParams['axes.unicode_minus'] = False
                logging.info(f"✅ 使用系统字体: {font_name}")
                return fm.FontProperties(family=font_name)
            except:
                continue
    
    # 使用通用回退方案
    logging.warning("⚠️ 使用通用回退字体 DejaVu Sans")
    rcParams['font.family'] = 'sans-serif'
    rcParams['font.sans-serif'] = ['DejaVu Sans']
    rcParams['axes.unicode_minus'] = False
    return fm.FontProperties(family='DejaVu Sans')

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(SCRIPT_DIR, "sentiment_analysis.log"))
    ]
)

# 初始化字体
chinese_font = setup_chinese_font()
# -------------------- 字体配置结束 --------------------

# 数据库配置
DB_CONFIG = {
    'host': 'host.docker.internal',
    'user': 'root',
    'password': os.getenv('MYSQL_PASSWORD', ''),
    'db': 'weibo_comments',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

def analyze_sentiment(weibo_ids):
    """分析指定微博评论的情感倾向（适配实际数据库结构）"""
    try:
        # 确保输出目录存在
        output_dir = os.path.join(SCRIPT_DIR, "sentiment_results")
        os.makedirs(output_dir, exist_ok=True)
        
        # 连接数据库
        db = pymysql.connect(**DB_CONFIG)
        cursor = db.cursor()
        
        # 遍历每个微博ID
        for weibo_id in weibo_ids:
            logging.info(f"🔍 开始分析微博ID: {weibo_id}")
            
            # 构建表名
            table_name = f"comments_{weibo_id}"
            logging.info(f"📝 使用评论表: {table_name}")
            
            # 检查表是否存在
            cursor.execute(f"SHOW TABLES LIKE '{table_name}'")
            if not cursor.fetchone():
                logging.error(f"❌ 表 {table_name} 不存在")
                continue
                
            # 获取表结构以验证列名
            cursor.execute(f"DESCRIBE {table_name}")
            columns = [col['Field'] for col in cursor.fetchall()]
            
            # 确定评论内容列名
            content_column = None
            for col in ['comment', 'comment_content', 'content']:
                if col in columns:
                    content_column = col
                    break
            
            if not content_column:
                logging.error(f"❌ 表 {table_name} 中未找到评论内容列")
                continue
                
            logging.info(f"📝 使用评论内容列: {content_column}")
            
            # 构建查询
            sql = f"SELECT {content_column} FROM {table_name}"
            
            try:
                cursor.execute(sql)
                comments = cursor.fetchall()
                logging.info(f"📊 找到 {len(comments)} 条评论")
            except pymysql.Error as e:
                logging.error(f"❌ 查询评论表 {table_name} 失败: {str(e)}")
                continue
            
            if not comments:
                logging.warning(f"⚠️ 微博ID {weibo_id} 没有找到评论")
                continue
                
            # 分析情感
            sentiments = []
            for i, comment in enumerate(comments):
                try:
                    content = comment[content_column]
                    if not content.strip():
                        continue
                        
                    s = SnowNLP(content)
                    sentiments.append(s.sentiments)
                    
                    # 每处理100条评论输出一次进度
                    if (i + 1) % 100 == 0:
                        logging.info(f"📊 已处理 {i+1}/{len(comments)} 条评论")
                except Exception as e:
                    logging.error(f"❌ 分析评论失败: {str(e)}")
                    continue
            
            # 计算平均情感值
            if not sentiments:
                logging.warning(f"⚠️ 微博ID {weibo_id} 没有有效的情感分析结果")
                continue
                
            avg_sentiment = np.mean(sentiments)
            logging.info(f"📊 微博ID {weibo_id} 平均情感值: {avg_sentiment:.4f}")
            
            # 分类情感
            positive = sum(1 for s in sentiments if s > 0.6)
            neutral = sum(1 for s in sentiments if 0.4 <= s <= 0.6)
            negative = sum(1 for s in sentiments if s < 0.4)
            total = len(sentiments)
            
            # 绘制饼图
            labels = ['正面', '中性', '负面']
            sizes = [positive, neutral, negative]
            colors = ['#66b3ff', '#99ff99', '#ff9999']
            
            plt.figure(figsize=(8, 6), dpi=100)
            
            # 使用更简洁的百分比显示
            def format_percent(p):
                return f'{p:.1f}%'
            
            wedges, texts, autotexts = plt.pie(
                sizes, 
                labels=labels, 
                colors=colors, 
                autopct=format_percent,
                shadow=True, 
                startangle=90
            )
            
            # 在饼图中心添加总数信息
            plt.text(0, 0, f'总评论数: {total}', 
                     ha='center', va='center', 
                     fontsize=12)
            
            plt.axis('equal')
            plt.title(f'微博ID {weibo_id} 评论情感分布', fontsize=14)
            
            # 添加图例
            plt.legend(wedges, labels,
                      title="情感分类",
                      loc="center left",
                      bbox_to_anchor=(1, 0, 0.5, 1))
            
            # 保存图表
            output_path = os.path.join(output_dir, f"sentiment_{weibo_id}.png")
            plt.tight_layout()
            plt.savefig(output_path, bbox_inches='tight', dpi=300)
            plt.close()
            logging.info(f"💾 保存情感分析图表至: {output_path}")
            
            # 保存原始数据
            data_path = os.path.join(output_dir, f"sentiment_data_{weibo_id}.txt")
            with open(data_path, 'w', encoding='utf-8') as f:
                f.write(f"微博ID: {weibo_id}\n")
                f.write(f"评论数量: {len(comments)}\n")
                f.write(f"有效评论: {len(sentiments)}\n")
                f.write(f"正面评论: {positive}\n")
                f.write(f"中性评论: {neutral}\n")
                f.write(f"负面评论: {negative}\n")
                f.write(f"平均情感值: {avg_sentiment:.4f}\n")
                f.write("\n情感分布:\n")
                f.write(f"正面 (>0.6): {positive/total*100:.2f}% ({positive})\n")
                f.write(f"中性 (0.4-0.6): {neutral/total*100:.2f}% ({neutral})\n")
                f.write(f"负面 (<0.4): {negative/total*100:.2f}% ({negative})\n")
        
        return True
        
    except Exception as e:
        logging.error(f"❌ 情感分析过程中出错: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
        return False
    finally:
        if 'db' in locals() and db.open:
            db.close()
            logging.info("🔌 数据库连接已关闭")
        
if __name__ == '__main__':
    # 需要分析的微博ID列表
    weibo_ids = [1, 2, 3, 4, 5]
    
    logging.info("\n" + "="*60)
    logging.info("微博评论情感分析启动")
    logging.info(f"当前工作目录: {os.getcwd()}")
    logging.info(f"脚本所在目录: {SCRIPT_DIR}")
    logging.info("="*60)
    
    if analyze_sentiment(weibo_ids):
        logging.info("\n🎉 所有微博情感分析完成!")
    else:
        logging.error("\n❌ 处理过程中遇到错误")