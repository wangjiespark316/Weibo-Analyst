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

from step9_scheduler.config import SCHEDULE_HOUR, SCHEDULE_MINUTE
from step9_scheduler.tenant_runner import run_tenant, load_tenants
from step9_scheduler.report_sender import list_reports


def generate_all_reports(tenant_filter: str = None) -> list:
    """
    批量生成所有租户日报。

    一个租户失败不影响其他租户（异常隔离在 run_tenant 内部）。

    Args:
        tenant_filter: 仅运行指定租户（None = 全部）

    Returns:
        结果列表 [{'tenant_key', 'tenant_name', 'success', 'report_path', 'duration', 'error'}, ...]
    """
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
        else:
            print(f"  ❌ {result['tenant_name']} — 失败（不影响其他租户）")
            print(f"     错误：{result['error']}")

    # 汇总
    print("\n" + "=" * 60)
    success_count = sum(1 for r in results if r['success'])
    fail_count = len(results) - success_count
    total_duration = sum(r['duration'] for r in results)
    print(f"[Scheduler] 完成：{success_count} 成功 / {fail_count} 失败 / 共 {len(results)}")
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
        description='微博舆情日报定时调度器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scheduler.py --now              # 立即执行全部租户
  python scheduler.py --now --tenant ai_test  # 仅执行指定租户
  python scheduler.py --daemon           # 启动每日定时任务
  python scheduler.py --daemon --hour 9 --minute 30  # 自定义时间
  python scheduler.py --list             # 列出已生成的日报
        """
    )
    parser.add_argument('--now', action='store_true', help='立即执行一次')
    parser.add_argument('--daemon', action='store_true', help='启动每日定时任务')
    parser.add_argument('--list', action='store_true', help='列出已生成的日报')
    parser.add_argument('--tenant', type=str, default=None, help='仅运行指定租户')
    parser.add_argument('--hour', type=int, default=SCHEDULE_HOUR, help=f'定时小时（默认{SCHEDULE_HOUR}）')
    parser.add_argument('--minute', type=int, default=SCHEDULE_MINUTE, help=f'定时分钟（默认{SCHEDULE_MINUTE}）')
    args = parser.parse_args()

    if args.list:
        show_reports()
    elif args.now:
        generate_all_reports(tenant_filter=args.tenant)
    elif args.daemon:
        start_daily_scheduler(hour=args.hour, minute=args.minute)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
