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
import json
from datetime import datetime, timedelta, timezone

# 北京时区（采集/日报时刻均按北京时间调度）
BJ_TZ = timezone(timedelta(hours=8))


def bj_now():
    return datetime.now(BJ_TZ)


# 确保项目根目录在 path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from step9_scheduler.config import SCHEDULE_HOUR, SCHEDULE_MINUTE, FEISHU_ENABLED, ENABLE_CRAWL
from step9_scheduler.tenant_runner import run_tenant, load_tenants
from step9_scheduler.report_sender import list_reports


def run_data_crawl(target: str = 'today'):
    """
    执行微博数据采集（可选，由 ENABLE_CRAWL 控制）。

    实时流自然日增量模式：调用 weibo_post_collector.py --mode realtime --target <target>，
    帖子与「窗口内帖子的评论」在一次运行内完成，不再单独跑 comment_batch
    （旧批量评论器会扫全库历史积压，不适合每日增量）。

    target: today=当天0点至今（高频增量）/ yesterday=昨天全天（日报前最后补采）/ YYYY-MM-DD

    失败自动重试：当采集进程返回非零，或所有关键词均 API 失败（ok!=1）、
    一页数据都没取到时，判定为「链路级失败」，按 CRAWL_RETRY_MAX / CRAWL_RETRY_WAIT
    自动等待并重试（采集器按帖子去重，重复运行安全）。部分关键词失败但已取到数据时
    判成功、不重试，避免重复写入。
    """
    if not ENABLE_CRAWL:
        print('[Scheduler] 数据采集未启用（ENABLE_CRAWL=false），跳过')
        return True

    import subprocess
    import re

    retry_max = int(os.getenv('CRAWL_RETRY_MAX', '2'))
    retry_wait = int(os.getenv('CRAWL_RETRY_WAIT', '90'))

    post_script = os.path.join(PROJECT_ROOT, 'step1_comments_spider', 'weibo_post_collector.py')
    if not os.path.exists(post_script):
        print(f'  ⚠️  帖子采集脚本不存在: {post_script}')
        return False

    def _run_once(attempt: int):
        print(f'  → [尝试 {attempt}] 实时流采集: {post_script} --mode realtime --target {target}')
        try:
            result = subprocess.run(
                [sys.executable, post_script, '--mode', 'realtime', '--target', target],
                capture_output=True, text=True, timeout=1800,
                cwd=PROJECT_ROOT,
            )
        except Exception as e:
            print(f'  ⚠️  采集异常: {type(e).__name__}: {e}')
            return {'healthy': False, 'reason': f'exception:{type(e).__name__}'}
        # 实时采集器的进度都在 stdout，打印尾部便于排查
        out = result.stdout or ''
        if out:
            tail = '\n'.join(out.strip().split('\n')[-25:])
            print(tail)
        if result.returncode != 0:
            print(f'  ⚠️  采集返回非零: {result.returncode}')
            if result.stderr:
                print(f'     stderr: {result.stderr[-500:]}')
            return {'healthy': False, 'reason': f'returncode:{result.returncode}'}
        # 判定「假成功」：所有关键词 ok!=1、未取到任何一页数据 = 链路整体故障
        api_fails = out.count('ok!=1')
        parsed_ok = len([m for m in re.finditer(r'解析到\s*([0-9]+)\s*条\s*mblog', out)
                         if int(m.group(1)) > 0])
        if api_fails > 0 and parsed_ok == 0:
            return {'healthy': False,
                    'reason': f'全部关键词API失败(ok!=1 x{api_fails})、0数据'}
        if api_fails > 0:
            print(f'  ⚠️  部分关键词失败(ok!=1 x{api_fails})，但已取到 {parsed_ok} 页数据，视为成功')
        print('  ✅ 实时流采集完成（帖子 + 窗口内评论）')
        return {'healthy': True, 'reason': 'ok'}

    print(f'[Scheduler] 开始数据采集（实时流增量，目标日={target}，'
          f'失败自动重试最多{retry_max}次/间隔{retry_wait}s）...')
    last = {'healthy': False, 'reason': 'unknown'}
    for attempt in range(1, retry_max + 2):
        last = _run_once(attempt)
        if last.get('healthy'):
            return True
        if attempt <= retry_max:
            print(f'  ⏳ 采集未成功（{last.get("reason")}），{retry_wait}s 后自动重试'
                  f'（剩余{retry_max - attempt + 1}次）...')
            time.sleep(retry_wait)
    print(f'  ❌ 采集经 {retry_max + 1} 次尝试仍失败：{last.get("reason")}')
    return False


def load_schedule_config():
    """
    从 config/crawl_config.json 读取调度时刻：
      collect_times: 每日多次增量采集（只采集不推送），如 ['09:00','13:00','18:00','22:00']
      report_time:   每日生成 T-1 自然日日报并推送的时刻，如 '08:30'
    读取失败回退默认值。
    """
    default = {'collect_times': ['09:00', '13:00', '18:00', '22:00'],
               'report_time': '08:30'}
    try:
        import json
        cfg_path = os.path.join(PROJECT_ROOT, 'config', 'crawl_config.json')
        with open(cfg_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        ct = data.get('collect_times', default['collect_times'])
        rt = data.get('report_time', default['report_time'])
        ct = [str(x) for x in ct if isinstance(x, str) and ':' in x]
        return {'collect_times': ct or default['collect_times'],
                'report_time': rt if ':' in str(rt) else default['report_time']}
    except Exception as e:
        print(f'[Scheduler] 读取调度时刻配置失败，用默认值: {e}')
        return default


def generate_all_reports(tenant_filter: str = None, skip_crawl: bool = False,
                         report_date: str = None) -> list:
    """
    批量生成所有租户的「T-1 自然日」日报。

    流程:
      1. 补采目标自然日（默认昨天）全天数据（可选，ENABLE_CRAWL 控制）
      2. 按目标自然日取数，批量生成日报（一个租户失败不影响其他）
      3. 飞书推送（FEISHU_ENABLED 控制，每天每租户仅 1 条）
      4. AI 情报流水线（事件/产品/趋势/网站日报），同样按目标自然日

    Args:
        tenant_filter: 仅运行指定租户（None = 全部）
        skip_crawl: 跳过数据采集步骤
        report_date: 目标自然日 'YYYY-MM-DD'，默认北京昨天（T-1）

    Returns:
        结果列表 [{'tenant_key', 'tenant_name', 'success', 'report_path', 'duration', 'error', 'feishu_pushed'}, ...]
    """
    # 目标自然日：默认北京昨天（T-1）
    if not report_date:
        report_date = (bj_now() - timedelta(days=1)).strftime('%Y-%m-%d')

    # 第一步: 补采目标自然日全天数据（把当天晚些时候发酵的评论补齐）
    if not skip_crawl:
        if not ENABLE_CRAWL:
            print('[Scheduler] 采集已禁用，停止正式日报和飞书写入')
            return []
        if not run_data_crawl(target=report_date):
            print(f'[Scheduler] 补采 {report_date} 失败，停止日报生成和飞书推送，避免发布不完整数据')
            return []
        # 飞书工作流晚于本次补采运行；仅在成功后开放同日取数。
        ready_dir = os.path.join(PROJECT_ROOT, 'logs', 'crawl_ready')
        os.makedirs(ready_dir, exist_ok=True)
        marker = os.path.join(ready_dir, f'{report_date}.json')
        tmp_marker = marker + '.tmp'
        with open(tmp_marker, 'w', encoding='utf-8') as ready_file:
            json.dump({'date': report_date, 'completed_at': bj_now().isoformat()}, ready_file)
        os.replace(tmp_marker, marker)
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
    print(f"[Scheduler] 批量生成日报（目标自然日 T-1：{report_date}）")
    print(f"[Scheduler] 执行时间：{now_str}")
    print(f"[Scheduler] 租户数量：{len(tenant_keys)}")
    print(f"[Scheduler] 飞书推送：{'启用' if FEISHU_ENABLED else '未启用'}（每租户仅 1 条）")
    print("=" * 60)

    results = []
    for i, tenant_key in enumerate(tenant_keys, 1):
        print(f"\n[{i}/{len(tenant_keys)}] 处理租户：{tenant_key}（数据日期 {report_date}）")
        result = run_tenant(tenant_key, report_date=report_date)
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

    # 执行AI情报流水线（事件分析→产品分析→趋势分析→日报生成）
    print("\n" + "=" * 60)
    print("[Scheduler] 开始执行AI行业情报流水线...")
    print("=" * 60)
    try:
        from step7_api_service.daily_ai_pipeline import run_daily_pipeline
        # AI情报分析目标自然日全天完整数据（与租户日报同一天，默认 T-1）
        analysis_date = report_date
        # 跳过采集步骤（前面已经补采过目标日）
        pipeline_result = run_daily_pipeline(analysis_date, skip_steps=["collect"])
        print(f"[Scheduler] AI情报流水线完成（分析日期 {analysis_date}）: {pipeline_result['success_count']}成功 / {pipeline_result['failed_count']}失败")

        # 日报质量检查
        try:
            from step7_api_service.report_quality_checker import check_report_quality
            quality = check_report_quality(analysis_date)
            print(f"[Scheduler] 日报质量评分: {quality['score']}/100 ({quality['status']})")
        except Exception as e:
            print(f"[Scheduler] 日报质量检查异常: {e}")
            
    except Exception as e:
        print(f"[Scheduler] AI情报流水线执行异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    return results


def start_daily_scheduler(hour: int = None, minute: int = None):
    """
    启动每日调度守护（多事件表，简单 sleep 循环，不依赖外部 cron）。

    - collect_times（默认 09/13/18/22 点）：只做当天实时流增量采集，不生成日报、不推送；
    - report_time（默认 08:30，可用 --hour/--minute 覆盖）：补采昨天全天，
      生成 T-1 自然日日报并推送，飞书群每天每租户只收 1 条。

    进程内用「日期|事件|时刻」去重，同一分钟只执行一次；跨天清空标记。
    """
    sched = load_schedule_config()
    collect_times = sched['collect_times']
    if hour is not None and minute is not None:
        report_time = f"{hour:02d}:{minute:02d}"  # CLI 显式覆盖
    else:
        report_time = sched['report_time']        # 默认读 crawl_config.json

    print("[Scheduler] 每日调度守护已启动")
    print(f"[Scheduler] 增量采集时刻（只采集不推送）：{', '.join(collect_times)}")
    print(f"[Scheduler] T-1 日报时刻（补采昨天 + 日报 + 飞书 1 条）：每天 {report_time}")
    print("[Scheduler] 按 Ctrl+C 停止")
    print()

    done = set()
    last_day = None
    while True:
        now = bj_now()
        today = now.strftime('%Y-%m-%d')
        hm = now.strftime('%H:%M')
        if today != last_day:
            done.clear()
            last_day = today

        # 1) 增量采集事件（目标=今天，只采集不推送）
        for ct in collect_times:
            key = f"{today}|collect|{ct}"
            if hm == ct and key not in done:
                done.add(key)
                print(f"\n[Scheduler] {hm} 触发当天增量采集（不推送）...")
                try:
                    run_data_crawl('today')
                except Exception as e:
                    print(f"[Scheduler] 增量采集出错：{type(e).__name__}: {e}")

        # 2) T-1 日报事件（补采昨天 + 日报 + 推送 1 条）
        rkey = f"{today}|report|{report_time}"
        if hm == report_time and rkey not in done:
            done.add(rkey)
            yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
            print(f"\n[Scheduler] {hm} 触发 T-1 日报（数据日期 {yesterday}）...")
            try:
                generate_all_reports(report_date=yesterday)
            except Exception as e:
                print(f"[Scheduler] 日报批量执行出错：{type(e).__name__}: {e}")

        try:
            time.sleep(30)  # 每 30 秒检查一次，任意整分钟至少命中一次
        except KeyboardInterrupt:
            print("\n[Scheduler] 收到停止信号，退出")
            break


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
  python scheduler.py --now                    # 立即生成 T-1（昨天）自然日日报（含补采昨天+推送1条）
  python scheduler.py --now --date 2026-09-18  # 立即生成指定自然日的日报
  python scheduler.py --now --skip-crawl       # 立即生成日报，跳过采集
  python scheduler.py --now --tenant ai_industry  # 仅执行指定租户
  python scheduler.py --crawl-now              # 只跑一次当天实时流增量采集（不生成日报、不推送）
  python scheduler.py --crawl-now --target yesterday  # 只补采昨天
  python scheduler.py --daemon                 # 启动每日调度（多次增量采集 + 08:30 T-1日报）
  python scheduler.py --daemon --hour 9 --minute 30  # 覆盖日报时刻
  python scheduler.py --list                   # 列出已生成的日报

调度时刻在 config/crawl_config.json 配置：
  collect_times  每日增量采集时刻（只采集不推送），默认 09/13/18/22 点
  report_time    T-1 日报时刻，默认 08:30

环境变量:
  ENABLE_CRAWL=true   启用采集（默认关闭）
  FEISHU_*            飞书自建应用推送配置
        """
    )
    parser.add_argument('--now', action='store_true', help='立即生成一次 T-1 自然日日报（含补采+推送）')
    parser.add_argument('--crawl-now', action='store_true', help='只跑一次实时流增量采集，不生成日报/不推送')
    parser.add_argument('--daemon', action='store_true', help='启动每日调度守护')
    parser.add_argument('--list', action='store_true', help='列出已生成的日报')
    parser.add_argument('--tenant', type=str, default=None, help='仅运行指定租户')
    parser.add_argument('--skip-crawl', action='store_true', help='跳过数据采集步骤')
    parser.add_argument('--date', type=str, default=None,
                        help="日报目标自然日 YYYY-MM-DD（配合 --now，默认昨天 T-1）")
    parser.add_argument('--target', type=str, default='today',
                        help="采集目标日 today/yesterday/YYYY-MM-DD（配合 --crawl-now，默认 today）")
    parser.add_argument('--hour', type=int, default=None, help='覆盖日报时刻-小时（默认读配置 08）')
    parser.add_argument('--minute', type=int, default=None, help='覆盖日报时刻-分钟（默认读配置 30）')
    args = parser.parse_args()

    if args.list:
        show_reports()
    elif args.crawl_now:
        ok = run_data_crawl(target=args.target)
        sys.exit(0 if ok else 1)
    elif args.now:
        generate_all_reports(tenant_filter=args.tenant, skip_crawl=args.skip_crawl,
                             report_date=args.date)
    elif args.daemon:
        start_daily_scheduler(hour=args.hour, minute=args.minute)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
