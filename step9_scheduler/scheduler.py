#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博舆情日报定时调度器
======================
功能:
  1. 批量生成所有租户日报（一个租户失败不影响其他）
  2. 每日定时执行（默认 08:00）
  3. 日报存储: reports/{tenant_key}/{YYYY-MM-DD}.md

用法:
  # 立即执行一次（测试用）
  .venv/bin/python step9_scheduler/scheduler.py --now

  # 启动每日定时任务（后台运行）
  .venv/bin/python step9_scheduler/scheduler.py --daemon

  # 自定义定时时间
  .venv/bin/python step9_scheduler/scheduler.py --daemon --hour 9 --minute 30

  # 仅运行指定租户
  .venv/bin/python step9_scheduler/scheduler.py --now --tenant ai_test
"""
import os
import sys
import time
import argparse
from datetime import datetime, timedelta

# 确保项目根目录在 path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from step9_scheduler.config import SCHEDULE_HOUR, SCHEDULE_MINUTE, FEISHU_ENABLED, ENABLE_CRAWL
from step9_scheduler.tenant_runner import run_tenant, load_tenants
from step9_scheduler.report_sender import list_reports


def run_data_crawl():
    """
    执行微博数据采集（可选，由 ENABLE_CRAWL 控制）
    采集帖子和评论数据，更新本地 MySQL
    """
    if not ENABLE_CRAWL:
        print('[Scheduler] 数据采集未启用（ENABLE_CRAWL=false），跳过')
        return True

    print('[Scheduler] 开始数据采集...')
    import subprocess

    # 帖子采集
    post_script = os.path.join(PROJECT_ROOT, 'step1_comments_spider', 'weibo_post_collector.py')
    if os.path.exists(post_script):
        print(f'  → 执行帖子采集: {post_script}')
        try:
            result = subprocess.run(
                [sys.executable, post_script],
                capture_output=True, text=True, timeout=300,
                cwd=PROJECT_ROOT,
            )
            if result.returncode == 0:
                print('  ✅ 帖子采集完成')
            else:
                print(f'  ⚠️  帖子采集返回非零: {result.returncode}')
                print(f'     stderr: {result.stderr[-200:]}')
        except Exception as e:
            print(f'  ⚠️  帖子采集异常: {e}')
    else:
        print(f'  ⚠️  帖子采集脚本不存在: {post_script}')

    # 评论采集
    comment_script = os.path.join(PROJECT_ROOT, 'step1_comments_spider', 'weibo_comment_batch_collector.py')
    if os.path.exists(comment_script):
        print(f'  → 执行评论采集: {comment_script}')
        try:
            result = subprocess.run(
                [sys.executable, comment_script],
                capture_output=True, text=True, timeout=600,
                cwd=PROJECT_ROOT,
            )
            if result.returncode == 0:
                print('  ✅ 评论采集完成')
            else:
                print(f'  ⚠️  评论采集返回非零: {result.returncode}')
        except Exception as e:
            print(f'  ⚠️  评论采集异常: {e}')
    else:
        print(f'  ⚠️  评论采集脚本不存在: {comment_script}')

    print('[Scheduler] 数据采集阶段完成')
    return True


def generate_all_reports(tenant_filter: str = None, skip_crawl: bool = False) -> list:
    """
    批量生成所有租户日报。

    流程:
      1. 数据采集（可选，ENABLE_CRAWL 控制）
      2. 批量生成日报（一个租户失败不影响其他）
      3. 飞书推送（FEISHU_ENABLED 控制）

    Args:
        tenant_filter: 仅运行指定租户（None = 全部）
        skip_crawl: 跳过数据采集步骤

    Returns:
        结果列表 [{'tenant_key', 'tenant_name', 'success', 'report_path', 'duration', 'error', 'feishu_pushed'}, ...]
    """
    # 第一步: 数据采集
    if not skip_crawl:
        run_data_crawl()
    else:
        print('[Scheduler] 跳过数据采集（--skip-crawl）')

    tenants = load_tenants()

    if tenant_filter:
        if tenant_filter not in tenants:
            print(f"[Scheduler] 错误：租户 '{tenant_filter}' 不存在")
            print(f"[Scheduler] 可用租户：{', '.join(tenants.keys())}")
            return []
        tenant_keys = [tenant_filter]
    else:
        tenant_keys = list(tenants.keys())

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print("=" * 60)
    print(f"[Scheduler] 批量生成日报")
    print(f"[Scheduler] 时间：{now_str}")
    print(f"[Scheduler] 租户数量：{len(tenant_keys)}")
    print(f"[Scheduler] 飞书推送：{'启用' if FEISHU_ENABLED else '未启用'}")
    print("=" * 60)

    results = []
    for i, tenant_key in enumerate(tenant_keys, 1):
        print(f"\n[{i}/{len(tenant_keys)}] 处理租户：{tenant_key}")
        result = run_tenant(tenant_key)
        results.append(result)

        if result['success']:
            print(f"  ✅ {result['tenant_name']}")
            print(f"     耗时：{result['duration']}s")
            print(f"     文件：{result['report_path']}")
            if result.get('feishu_pushed') is True:
                print(f"     📨 飞书推送：成功")
            elif result.get('feishu_pushed') is False:
                print(f"     ⚠️  飞书推送：失败")
        else:
            print(f"  ❌ {result['tenant_name']} — 失败（不影响其他租户）")
            print(f"     错误：{result['error']}")

    # 汇总
    print("\n" + "=" * 60)
    success_count = sum(1 for r in results if r['success'])
    fail_count = len(results) - success_count
    feishu_success = sum(1 for r in results if r.get('feishu_pushed') is True)
    feishu_fail = sum(1 for r in results if r.get('feishu_pushed') is False)
    total_duration = sum(r['duration'] for r in results)
    print(f"[Scheduler] 完成：{success_count} 成功 / {fail_count} 失败 / 共 {len(results)}")
    if FEISHU_ENABLED:
        print(f"[Scheduler] 飞书推送：{feishu_success} 成功 / {feishu_fail} 失败")
    print(f"[Scheduler] 总耗时：{total_duration:.1f}s")
    print("=" * 60)

    return results


def start_daily_scheduler(hour: int = SCHEDULE_HOUR, minute: int = SCHEDULE_MINUTE):
    """
    启动每日定时任务。

    每天在指定时间执行 generate_all_reports()。
    使用简单的 sleep 循环，不依赖外部 cron。
    """
    print(f"[Scheduler] 每日定时任务已启动")
    print(f"[Scheduler] 执行时间：每天 {hour:02d}:{minute:02d}")
    print(f"[Scheduler] 按 Ctrl+C 停止")
    print()

    while True:
        now = datetime.now()
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)

        wait_seconds = (next_run - now).total_seconds()
        wait_hours = wait_seconds / 3600
        print(f"[Scheduler] 下次执行：{next_run.strftime('%Y-%m-%d %H:%M:%S')}"
              f"（等待 {wait_hours:.1f} 小时）")

        try:
            time.sleep(wait_seconds)
        except KeyboardInterrupt:
            print("\n[Scheduler] 收到停止信号，退出")
            break

        # 执行批量生成
        print(f"\n[Scheduler] 定时触发，开始执行...")
        try:
            generate_all_reports()
        except Exception as e:
            print(f"[Scheduler] 批量执行出错：{type(e).__name__}: {e}")
        print()


def show_reports():
    """显示已生成的日报列表"""
    reports = list_reports()
    if not reports:
        print("[Scheduler] 暂无已生成的日报")
        return

    print(f"[Scheduler] 已生成日报（共 {len(reports)} 份）：")
    print("-" * 60)
    for r in reports:
        print(f"  {r['tenant']:20s} | {r['date']} | {r['size']:>6d} bytes | {r['path']}")


def main():
    parser = argparse.ArgumentParser(
        description='微博舆情日报定时调度器（含飞书推送）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scheduler.py --now                    # 立即执行全部租户（含数据采集）
  python scheduler.py --now --skip-crawl      # 立即执行，跳过数据采集
  python scheduler.py --now --tenant ai_test  # 仅执行指定租户
  python scheduler.py --daemon                 # 启动每日定时任务
  python scheduler.py --daemon --hour 9 --minute 30  # 自定义时间
  python scheduler.py --list                   # 列出已生成的日报

环境变量:
  FEISHU_WEBHOOK_URL  飞书群机器人 Webhook（配置后自动推送）
  ENABLE_CRAWL=true    启用日报前的数据采集（默认关闭）
  SCHEDULE_HOUR        定时小时（默认8）
  SCHEDULE_MINUTE      定时分钟（默认0）
        """
    )
    parser.add_argument('--now', action='store_true', help='立即执行一次')
    parser.add_argument('--daemon', action='store_true', help='启动每日定时任务')
    parser.add_argument('--list', action='store_true', help='列出已生成的日报')
    parser.add_argument('--tenant', type=str, default=None, help='仅运行指定租户')
    parser.add_argument('--skip-crawl', action='store_true', help='跳过数据采集步骤')
    parser.add_argument('--hour', type=int, default=SCHEDULE_HOUR, help=f'定时小时（默认{SCHEDULE_HOUR}）')
    parser.add_argument('--minute', type=int, default=SCHEDULE_MINUTE, help=f'定时分钟（默认{SCHEDULE_MINUTE}）')
    args = parser.parse_args()

    if args.list:
        show_reports()
    elif args.now:
        generate_all_reports(tenant_filter=args.tenant, skip_crawl=args.skip_crawl)
    elif args.daemon:
        start_daily_scheduler(hour=args.hour, minute=args.minute)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
