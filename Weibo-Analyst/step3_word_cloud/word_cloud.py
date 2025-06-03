#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Dec 21 15:06:18 2017
@author: Ming JIN
"""
import jieba.analyse
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties  
from wordcloud import WordCloud, ImageColorGenerator
from PIL import Image
import glob
import os
import argparse

# ===== 获取脚本所在目录 =====
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ===== 创建输出目录 =====
OUTPUT_DIR = os.path.join(SCRIPT_DIR, 'output')  # 在脚本目录下创建output文件夹
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 设置中文字体 - 使用绝对路径
font_path = os.path.join(SCRIPT_DIR, 'Songti.ttc')
if not os.path.exists(font_path):
    print(f"警告：字体文件未找到: {font_path}")
    print("请确保Songti.ttc字体文件存在于脚本目录")
font = FontProperties(fname=font_path) if os.path.exists(font_path) else None
bar_width = 0.5

# ===== 添加命令行参数解析 =====
parser = argparse.ArgumentParser(description='微博评论词云生成工具')
parser.add_argument('--input_dir', type=str, default='/workspace/step2_comment_segmentation/weibo_comments',
                    help='预处理输出目录，包含评论文件')
args = parser.parse_args()

DATA_DIR = args.input_dir

# 如果找不到文件，显示错误信息
if not os.path.exists(DATA_DIR):
    print(f"错误：输入目录不存在: {DATA_DIR}")
    print("请检查以下情况:")
    print("1. 确保已运行预处理脚本")
    print("2. 检查 --input_dir 参数是否正确")
    exit(1)

# 定义要处理的文件列表
file_list = []
# 匹配预处理脚本生成的所有评论文件
patterns = ['comments_*.txt', 'all_comments.txt']
for pattern in patterns:
    file_list.extend(glob.glob(os.path.join(DATA_DIR, pattern)))

# 如果找不到文件，显示错误信息
if not file_list:
    print(f"错误：在 {DATA_DIR} 找不到任何数据文件！")
    print("请检查以下情况:")
    print("1. 确保已运行预处理脚本")
    print("2. 检查 --input_dir 参数是否正确")
    print("3. 预处理输出目录应包含 comments_*.txt 或 all_comments.txt 文件")
    print(f"目录内容: {os.listdir(DATA_DIR)}")
    exit(1)

print(f"找到 {len(file_list)} 个数据文件:")
for i, path in enumerate(file_list, 1):
    print(f"{i}. {os.path.abspath(path)}")

# 背景图片路径 - 使用绝对路径
background_img = os.path.join(SCRIPT_DIR, 'background.png')
print(f"背景图片路径: {background_img}")

# 处理每个文件
for file_path in file_list:
    # 读取文件内容
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lyric = f.read()
    except UnicodeDecodeError:
        try:
            with open(file_path, 'r', encoding='gbk') as f:
                lyric = f.read()
        except Exception as e:
            print(f"无法读取文件 {file_path}: {str(e)}")
            continue
    except Exception as e:
        print(f"读取文件 {file_path} 出错: {str(e)}")
        continue
    
    # 提取关键词
    try:
        result = jieba.analyse.textrank(lyric, topK=50, withWeight=True)
        keywords = dict()
        for i in result:
            keywords[i[0]] = i[1]
    except Exception as e:
        print(f"处理文件 {file_path} 时出错: {str(e)}")
        continue
    
    print(f"\n处理文件: {os.path.basename(file_path)} - 找到 {len(keywords)} 个关键词")
    
    # 生成文件名前缀
    file_id = os.path.basename(file_path).split('.')[0]
    
    # ========== 生成词云 ==========
    graph = None
    try:
        if os.path.exists(background_img):
            image = Image.open(background_img)
            graph = np.array(image)
            print(f"使用背景图片: {background_img}")
        else:
            print(f"警告：背景图片 {background_img} 未找到，使用纯色背景")
    except Exception as e:
        print(f"加载背景图片出错: {str(e)}，使用纯色背景")
    
    try:
        wc = WordCloud(
            font_path=font_path if os.path.exists(font_path) else None,
            background_color='White',
            max_words=50,
            mask=graph,
            width=1600,
            height=900
        )
        wc.generate_from_frequencies(keywords)
        
        if graph is not None:
            try:
                image_color = ImageColorGenerator(graph)
                wc_image = wc.recolor(color_func=image_color)
            except Exception as e:
                print(f"重新着色出错: {str(e)}，使用默认颜色")
                wc_image = wc
        else:
            wc_image = wc
        
        plt.figure(figsize=(16, 9))
        plt.imshow(wc_image)
        plt.axis("off")
        title = f"关键词词云 - {file_id}"
        if font:
            plt.title(title, fontproperties=font, fontsize=16)
        else:
            plt.title(title, fontsize=16)
        
        # 保存词云图到输出目录
        cloud_output = os.path.join(OUTPUT_DIR, f'output_cloud_{file_id}.png')
        plt.savefig(cloud_output, bbox_inches='tight', dpi=300)
        print(f"词云图已保存至: {cloud_output}")
        plt.close()
    except Exception as e:
        print(f"生成词云时出错: {str(e)}")
        plt.close()
    
    # ========== 生成条形图 ==========
    if not keywords:
        print("没有关键词数据，跳过条形图生成")
        continue
        
    try:
        X = list(keywords.keys())
        Y = list(keywords.values())
        num = len(X)
        
        plt.figure(figsize=(28, 10))
        plt.bar(range(num), Y, tick_label=X, width=bar_width)
        plt.xticks(rotation=50, fontsize=20)
        # 设置条形图的刻度字体
        if font:
            for label in plt.gca().get_xticklabels():
                label.set_fontproperties(font)
        plt.yticks(fontsize=20)
        title = f"关键词频率分布 - {file_id}"
        if font:
            plt.title(title, fontproperties=font, fontsize=30)
        else:
            plt.title(title, fontsize=30)
        
        # 保存条形图到输出目录
        bar_output = os.path.join(OUTPUT_DIR, f'output_barchart_{file_id}.jpg')
        plt.savefig(bar_output, bbox_inches='tight', dpi=360)
        print(f"条形图已保存至: {bar_output}")
        plt.close()
    except Exception as e:
        print(f"生成条形图时出错: {str(e)}")
        plt.close()

print("\n所有文件处理完成!")
print(f"输出文件保存在: {os.path.abspath(OUTPUT_DIR)}")
