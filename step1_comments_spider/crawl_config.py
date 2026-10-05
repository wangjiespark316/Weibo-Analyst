#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博爬虫采集配置模块（配置驱动）
=================================
从 config/crawl_config.json 读取关键词与采集参数，替代代码内硬编码。

配置文件结构（顶层为默认配置，tenants 为多客户预留）：

    {
      "keywords": ["飞书", "豆包"],        # 关键词采集列表（每个词一条通道）
      "users": ["1669879400"],             # 用户时间线采集列表（可空）
      "max_posts": 5,                      # 每通道最多帖子数
      "max_comments": 50,                  # 每帖最多评论数
      "tenants": [                         # 未来多客户配置（预留，暂不参与采集）
        {"name": "客户A", "keywords": [...], "users": [], "max_posts": 3, "max_comments": 30}
      ]
    }

配置文件路径优先级（高 → 低）：
  1. 命令行 --config 参数（由调用方传入）
  2. 环境变量 CRAWL_CONFIG（多客户/多环境切换）
  3. 项目默认 config/crawl_config.json

用法：
    from crawl_config import load_crawl_config
    cfg = load_crawl_config('/path/to/config.json')   # 或 load_crawl_config() 走优先级
"""
import json
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CONFIG_PATH = os.path.join(_PROJECT_ROOT, 'config', 'crawl_config.json')

# 配置缺省值（配置文件未填写时兜底）
_DEFAULTS = {
    'keywords': [],
    'users': [],
    'max_posts': 10,
    'max_comments': 50,
    # —— 实时流增量采集 / 自然日窗口（每日无人值守）——
    # search_mode: realtime=微博实时流(type=61,按时间倒序,只取目标自然日)；mixed=旧综合排序(type=1)
    'search_mode': 'realtime',
    # collect_target: 采集目标自然日 today=当天0点至今(高频增量) / yesterday=昨天全天(日报前补采)
    'collect_target': 'today',
    'per_keyword': 15,        # 每个关键词在目标自然日内最多入库的帖子数
    'max_pages': 6,           # 实时流每个关键词最多翻页数（翻到目标日之前即停）
    'comment_post_limit': 30, # 每次仅给目标日内评论数最高的 N 条帖子补评论
    'collect_times': ['09:00', '11:30', '14:00', '16:30', '19:00', '22:00'],  # daemon 每日增量采集时刻
    'report_time': '08:30',   # daemon 每日生成 T-1 自然日日报并推送的时刻
}


def _as_int(data, key, default):
    """安全读取整数配置（空值/非法值回退默认）"""
    try:
        v = data.get(key, default)
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def resolve_config_path(explicit_path=None):
    """按优先级解析配置文件路径：--config > CRAWL_CONFIG > 默认路径"""
    if explicit_path:
        return explicit_path
    env_path = os.getenv('CRAWL_CONFIG')
    if env_path:
        return env_path
    return _DEFAULT_CONFIG_PATH


def load_crawl_config(explicit_path=None):
    """
    读取采集配置，返回 dict：
        {'keywords': [...], 'users': [...], 'max_posts': int, 'max_comments': int, 'source': path}

    配置文件不存在时：使用缺省值并给出提示（不抛异常，保证命令行直接运行可用）。
    """
    path = resolve_config_path(explicit_path)
    cfg = dict(_DEFAULTS)

    if not os.path.exists(path):
        print(f'[crawl_config] ⚠️ 配置文件不存在: {path}，使用缺省值（keywords=[] max_posts={cfg["max_posts"]}）')
        cfg['source'] = path
        return cfg

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f'[crawl_config] ⚠️ 配置文件解析失败: {path} ({e})，使用缺省值')
        cfg['source'] = path
        return cfg

    # 顶层默认配置（同时兼容用户给定的扁平结构与带默认节的嵌套结构）
    if 'default' in data and isinstance(data['default'], dict):
        data = data['default']

    cfg['keywords'] = [str(k).strip() for k in data.get('keywords', []) if str(k).strip()]
    cfg['users'] = [str(u).strip() for u in data.get('users', []) if str(u).strip()]
    cfg['max_posts'] = _as_int(data, 'max_posts', cfg['max_posts'])
    cfg['max_comments'] = _as_int(data, 'max_comments', cfg['max_comments'])
    cfg['tenants'] = data.get('tenants', [])

    # 实时流 / 自然日窗口相关配置（缺省走 _DEFAULTS）
    cfg['search_mode'] = str(data.get('search_mode', cfg['search_mode']) or cfg['search_mode']).strip()
    cfg['collect_target'] = str(data.get('collect_target', cfg['collect_target']) or cfg['collect_target']).strip()
    cfg['per_keyword'] = _as_int(data, 'per_keyword', cfg['per_keyword'])
    cfg['max_pages'] = _as_int(data, 'max_pages', cfg['max_pages'])
    cfg['comment_post_limit'] = _as_int(data, 'comment_post_limit', cfg['comment_post_limit'])
    ct = data.get('collect_times', cfg['collect_times'])
    cfg['collect_times'] = [str(x).strip() for x in ct if str(x).strip()] if isinstance(ct, list) else cfg['collect_times']
    cfg['report_time'] = str(data.get('report_time', cfg['report_time']) or cfg['report_time']).strip()

    cfg['source'] = path
    return cfg


if __name__ == '__main__':
    import json as _json
    cfg = load_crawl_config()
    print('=== 采集配置 ===')
    print(f'配置文件: {cfg["source"]}')
    print(f'关键词 ({len(cfg["keywords"])}): {cfg["keywords"]}')
    print(f'用户 ({len(cfg["users"])}): {cfg["users"]}')
    print(f'max_posts: {cfg["max_posts"]} | max_comments: {cfg["max_comments"]}')
    print(f'search_mode: {cfg["search_mode"]} | collect_target: {cfg["collect_target"]} '
          f'| per_keyword: {cfg["per_keyword"]} | max_pages: {cfg["max_pages"]} '
          f'| comment_post_limit: {cfg["comment_post_limit"]}')
    print(f'collect_times: {cfg["collect_times"]} | report_time: {cfg["report_time"]}')
    print(f'多客户配置数: {len(cfg.get("tenants", []))}（预留）')
