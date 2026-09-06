#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

# 获取当前文件所在目录
current_dir = os.path.dirname(os.path.abspath(__file__))


# 配置结果文件路径（在本目录）
result_path = os.path.join(current_dir, "eva_result.dat")
print(f"结果文件将保存至: {result_path}")

# 配置数据文件路径（使用相对路径）
eva_data_path = os.path.join(current_dir, "eva_data.dat")
eva_label_path = os.path.join(current_dir, "eva_label.dat")

# 获取父目录路径（step4_sentiments）
parent_dir = os.path.dirname(current_dir)

# 初始化情感分析模型# 加载位于train_model文件夹中的模型
from snownlp import sentiment
sentiment.load(os.path.join(parent_dir, "train_model", "my_sentiment.marshal"))
from snownlp import SnowNLP

# 处理数据并写入结果
results = []
with open(eva_data_path, "r", encoding="utf-8") as f_data:
    for line in f_data:
        s = SnowNLP(line.strip())
        eva_label = 1 if s.sentiments >= 0.5 else -1
        results.append(str(eva_label))

# 一次性写入结果文件
with open(result_path, "w", encoding="utf-8") as f_result:
    f_result.write("\n".join(results))

# 计算准确率
true_labels = []
with open(eva_label_path, "r", encoding="utf-8") as f_label:
    true_labels = [line.strip() for line in f_label]

correct_count = 0
total_count = min(len(results), len(true_labels))

for i in range(total_count):
    if results[i] == true_labels[i]:
        correct_count += 1

accuracy = correct_count / total_count
print(f"分析完成! 准确率: {accuracy:.2%} ({correct_count}/{total_count})")