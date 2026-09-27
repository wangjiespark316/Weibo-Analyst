#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI行业情报自动化流水线（生产化版本）
每天自动完成：微博采集 → 事件分析 → 产品分析 → 趋势分析 → 日报生成
特性：任务运行锁、失败重试、详细日志、健康检查
"""
import os
import sys
import json
import time
import traceback
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import pymysql

sys.path.insert(0, "/opt/Weibo-Analyst")

# 流水线步骤定义（含重试次数）
PIPELINE_STEPS = [
    {"key": "collect", "name": "微博数据采集", "description": "采集微博AI相关数据", "max_retries": 3, "retry_interval": 300},
    {"key": "events", "name": "AI事件分析", "description": "分析当日AI热点事件", "max_retries": 2, "retry_interval": 60},
    {"key": "products", "name": "AI产品分析", "description": "分析AI产品声量变化", "max_retries": 2, "retry_interval": 60},
    {"key": "trends", "name": "AI技术趋势分析", "description": "分析AI技术发展趋势", "max_retries": 2, "retry_interval": 60},
    {"key": "report", "name": "AI日报生成", "description": "生成AI行业日报", "max_retries": 2, "retry_interval": 60},
    {"key": "sales_opp", "name": "AI销售机会分析", "description": "基于事件与趋势生成销售机会", "max_retries": 2, "retry_interval": 60},
]

TASK_NAME = "ai_intelligence_pipeline"

# 北京时区（微博发布时间与日报口径均按北京时间）
BJ_TZ = timezone(timedelta(hours=8))


def beijing_now():
    """当前北京时间"""
    return datetime.now(BJ_TZ)


def default_analysis_date():
    """
    默认分析目标日期 = 北京时间前一天。
    在次日凌晨分析"前一天全天"的完整数据，
    避免当天清晨因样本不足导致事件/产品0产出。
    """
    return (beijing_now() - timedelta(days=1)).strftime("%Y-%m-%d")


def get_db_connection():
    """获取数据库连接"""
    from dotenv import load_dotenv
    load_dotenv("/opt/Weibo-Analyst/.env")
    import pymysql
    
    def to_str(v):
        return v.decode() if isinstance(v, bytes) else v
    
    db_url = os.getenv("DATABASE_URL")
    p = urlparse(db_url)
    return pymysql.connect(
        host=to_str(p.hostname), port=p.port or 4000,
        user=to_str(p.username), password=to_str(p.password),
        database=to_str(p.path).lstrip("/"),
        charset="utf8mb4", ssl={"ssl_disabled": False}
    )


# ==================== 任务运行锁 ====================

def acquire_lock(date_str):
    """获取任务运行锁。
    - 同日期存在 running 锁：死锁(>2h)则接管，否则返回False拦截并发；
    - 同日期锁已结束(success/failed)：复用该行重置为 running，允许手动重跑/补跑；
    - 无锁：新建。
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 查该日期最新一条锁（不限状态）
        cursor.execute("""
            SELECT id, status, started_time, pid
            FROM pipeline_lock
            WHERE task_name = %s AND lock_date = %s
            ORDER BY started_time DESC LIMIT 1
        """, (TASK_NAME, date_str))
        existing = cursor.fetchone()

        if existing:
            lock_id, status, started_time, pid = existing
            if status == "running" and started_time:
                elapsed = (datetime.now() - started_time).total_seconds()
                if elapsed <= 7200:
                    print(f"⏳ 任务正在运行中（PID: {pid}, 已运行{elapsed/60:.1f}分钟），跳过本次执行")
                    conn.close()
                    return False
                print(f"⚠️  发现超时锁（已运行{elapsed/3600:.1f}小时），强制接管")

            # 已结束锁 或 超时running锁：复用该行重置为running（避免唯一键冲突，支持重跑）
            cursor.execute("""
                UPDATE pipeline_lock
                SET status = 'running', started_time = NOW(), finished_time = NULL, pid = %s
                WHERE id = %s
            """, (os.getpid(), lock_id))
            conn.commit()
            print(f"🔒 获取任务锁成功（复用重跑 {date_str}, PID: {os.getpid()}）")
            conn.close()
            return True

        # 无历史锁：创建新锁
        cursor.execute("""
            INSERT INTO pipeline_lock (task_name, lock_date, status, started_time, pid)
            VALUES (%s, %s, 'running', NOW(), %s)
        """, (TASK_NAME, date_str, os.getpid()))
        conn.commit()
        print(f"🔒 获取任务锁成功 (PID: {os.getpid()})")
        conn.close()
        return True

    except Exception as e:
        print(f"❌ 获取任务锁失败: {e}")
        return False


def release_lock(date_str, status="success"):
    """释放任务运行锁"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE pipeline_lock 
            SET status = %s, finished_time = NOW()
            WHERE task_name = %s AND lock_date = %s AND status = 'running'
        """, (status, TASK_NAME, date_str))
        conn.commit()
        conn.close()
        print(f"🔓 释放任务锁 (状态: {status})")
    except Exception as e:
        print(f"❌ 释放任务锁失败: {e}")


# ==================== 日志记录 ====================

def log_pipeline_step(run_date, step, status, message="", duration=0, retry_count=0, error_detail="", start_time=None, end_time=None):
    """记录流水线步骤日志（增强版）"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pipeline_logs 
            (run_date, step, status, message, duration, retry_count, error_detail, start_time, end_time, created_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (run_date, step, status, message, duration, retry_count, error_detail, start_time, end_time))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"记录日志失败: {e}")


# ==================== 步骤执行函数 ====================

def step_collect_weibo(date_str):
    """步骤1：微博数据采集"""
    print(f"[{date_str}] 开始微博数据采集...")
    
    # 检查是否已有数据
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM weibo_posts 
            WHERE DATE(publish_time) = %s
        """, (date_str,))
        count = cursor.fetchone()[0]
        conn.close()
        
        if count > 0:
            print(f"  已有 {count} 条微博数据，跳过采集")
            return {"status": "success", "count": count, "skipped": True}
    except Exception as e:
        print(f"  检查数据失败: {e}")
    
    # 调用现有采集脚本
    try:
        import subprocess
        result = subprocess.run(
            ["python3", "/opt/Weibo-Analyst/step9_scheduler/run_daily.py", date_str],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            print(f"  采集完成: {result.stdout[:200]}")
            return {"status": "success", "output": result.stdout[:500]}
        else:
            print(f"  采集失败: {result.stderr[:200]}")
            return {"status": "failed", "error": result.stderr[:500]}
    except FileNotFoundError:
        print("  采集脚本不存在，跳过（使用已有数据）")
        return {"status": "success", "skipped": True, "note": "使用已有数据"}
    except Exception as e:
        print(f"  采集异常: {e}")
        return {"status": "failed", "error": str(e)}


def step_analyze_events(date_str):
    """步骤2：AI事件分析"""
    print(f"[{date_str}] 开始AI事件分析...")
    try:
        from step7_api_service.event_analyzer import analyze_and_save
        result = analyze_and_save(date_str, force=True)
        # 兼容返回列表或字典
        if isinstance(result, list):
            count = len(result)
        else:
            count = result.get("count", 0) if isinstance(result, dict) else 0
        print(f"  事件分析完成: {count} 个事件")
        return {"status": "success", "count": count}
    except Exception as e:
        print(f"  事件分析失败: {e}")
        traceback.print_exc()
        return {"status": "failed", "error": str(e), "traceback": traceback.format_exc()[:500]}


def step_analyze_products(date_str):
    """步骤3：AI产品分析"""
    print(f"[{date_str}] 开始AI产品分析...")
    try:
        from step7_api_service.product_analyzer import analyze_and_save
        result = analyze_and_save(date_str, force=True)
        count = result.get("count", 0) if isinstance(result, dict) else len(result) if isinstance(result, list) else 0
        print(f"  产品分析完成: {count} 个产品")
        return {"status": "success", "count": count}
    except Exception as e:
        print(f"  产品分析失败: {e}")
        traceback.print_exc()
        return {"status": "failed", "error": str(e), "traceback": traceback.format_exc()[:500]}


def step_analyze_trends(date_str):
    """步骤4：AI技术趋势分析"""
    print(f"[{date_str}] 开始AI技术趋势分析...")
    try:
        from step7_api_service.trend_analyzer import analyze_and_save
        result = analyze_and_save(date_str, force=True)
        count = result.get("count", 0) if isinstance(result, dict) else len(result) if isinstance(result, list) else 0
        print(f"  趋势分析完成: {count} 个技术方向")
        return {"status": "success", "count": count}
    except Exception as e:
        print(f"  趋势分析失败: {e}")
        traceback.print_exc()
        return {"status": "failed", "error": str(e), "traceback": traceback.format_exc()[:500]}


def step_generate_report(date_str):
    """步骤5：AI日报生成"""
    print(f"[{date_str}] 开始AI日报生成...")
    try:
        from step7_api_service.daily_report_generator import generate_and_save_report
        content = generate_and_save_report(date_str, force=True)
        print(f"  日报生成完成: {len(content)} 字符")
        return {"status": "success", "length": len(content)}
    except Exception as e:
        print(f"  日报生成失败: {e}")
        traceback.print_exc()
        return {"status": "failed", "error": str(e), "traceback": traceback.format_exc()[:500]}


def step_sales_opportunity(date_str):
    """步骤6：AI销售机会分析（基于事件/技术趋势，纯规则匹配，无LLM调用，幂等）"""
    print(f"[{date_str}] 开始AI销售机会分析...")
    try:
        from step7_api_service.sales_opportunity_analyzer import analyze_and_save
        result = analyze_and_save(date_str, force=True)
        n = len(result) if result is not None else 0
        print(f"  销售机会分析完成: {n} 条")
        return {"status": "success", "count": n}
    except Exception as e:
        print(f"  销售机会分析失败: {e}")
        traceback.print_exc()
        return {"status": "failed", "error": str(e), "traceback": traceback.format_exc()[:500]}


# 步骤映射
STEP_FUNCTIONS = {
    "collect": step_collect_weibo,
    "events": step_analyze_events,
    "products": step_analyze_products,
    "trends": step_analyze_trends,
    "report": step_generate_report,
    "sales_opp": step_sales_opportunity,
}


# ==================== 带重试的步骤执行 ====================

def execute_step_with_retry(step_info, date_str):
    """执行单个步骤，带失败重试"""
    step_key = step_info["key"]
    step_name = step_info["name"]
    max_retries = step_info.get("max_retries", 2)
    retry_interval = step_info.get("retry_interval", 60)
    
    step_func = STEP_FUNCTIONS[step_key]
    last_result = None
    last_error = ""
    
    for attempt in range(max_retries + 1):
        retry_count = attempt
        start_time = datetime.now()
        
        if attempt > 0:
            print(f"  🔄 第{attempt}次重试（等待{retry_interval}秒）...")
            time.sleep(retry_interval)
        
        try:
            result = step_func(date_str)
            end_time = datetime.now()
            duration = int((end_time - start_time).total_seconds())
            
            if result.get("status") == "success":
                log_pipeline_step(date_str, step_key, "success", 
                                f"{step_name}成功", duration, retry_count, "",
                                start_time, end_time)
                return result
            else:
                last_result = result
                last_error = result.get("error", "未知错误")
                log_pipeline_step(date_str, step_key, "failed",
                                f"{step_name}失败（第{attempt+1}次）: {last_error[:100]}",
                                duration, retry_count, last_error[:500],
                                start_time, end_time)
                
        except Exception as e:
            end_time = datetime.now()
            duration = int((end_time - start_time).total_seconds())
            last_error = f"{str(e)}\n{traceback.format_exc()[:300]}"
            log_pipeline_step(date_str, step_key, "failed",
                            f"{step_name}异常（第{attempt+1}次）: {str(e)[:100]}",
                            duration, retry_count, last_error[:500],
                            start_time, end_time)
            print(f"  ❌ {step_name}异常: {e}")
    
    # 所有重试都失败
    print(f"  ❌ {step_name}在{max_retries+1}次尝试后仍然失败")
    return {"status": "failed", "error": last_error, "retries": max_retries}


# ==================== 主流水线 ====================

def run_daily_pipeline(date_str=None, skip_steps=None):
    """
    运行每日AI情报流水线（生产化版本，带锁和重试）
    
    Args:
        date_str: 日期，默认今天
        skip_steps: 要跳过的步骤列表
    
    Returns:
        流水线运行结果
    """
    if not date_str:
        date_str = default_analysis_date()
    
    if skip_steps is None:
        skip_steps = []
    
    # 1. 获取任务锁
    if not acquire_lock(date_str):
        return {
            "date": date_str,
            "status": "skipped",
            "reason": "任务已在运行中",
            "total_duration": 0,
            "success_count": 0,
            "failed_count": 0,
            "results": {}
        }
    
    print("=" * 70)
    print(f"AI行业情报自动化流水线 - {date_str}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    results = {}
    total_start = time.time()
    success_count = 0
    failed_count = 0
    overall_status = "success"
    
    try:
        for step_info in PIPELINE_STEPS:
            step_key = step_info["key"]
            step_name = step_info["name"]
            
            if step_key in skip_steps:
                print(f"\n⏭️  跳过: {step_name}")
                results[step_key] = {"status": "skipped", "name": step_name}
                continue
            
            print(f"\n{'─' * 70}")
            print(f"▶️  开始: {step_name}")
            print(f"{'─' * 70}")
            
            result = execute_step_with_retry(step_info, date_str)
            results[step_key] = {**result, "name": step_name}
            
            if result.get("status") == "success":
                success_count += 1
                print(f"✅ {step_name}完成")
            else:
                failed_count += 1
                overall_status = "partial_failed" if success_count > 0 else "failed"
                print(f"❌ {step_name}失败: {result.get('error', '未知错误')[:100]}")
        
        total_duration = int(time.time() - total_start)
        
        # 释放锁
        release_lock(date_str, overall_status)
        
    except Exception as e:
        total_duration = int(time.time() - total_start)
        overall_status = "failed"
        print(f"\n❌ 流水线执行异常: {e}")
        traceback.print_exc()
        release_lock(date_str, "failed")
    
    print("\n" + "=" * 70)
    print(f"流水线执行完成 - {date_str}")
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"总耗时: {total_duration}秒")
    print(f"成功: {success_count}/{len(PIPELINE_STEPS)} | 失败: {failed_count}/{len(PIPELINE_STEPS)}")
    print(f"整体状态: {overall_status}")
    print("=" * 70)
    
    # 输出各步骤结果
    print("\n各步骤结果:")
    for step_info in PIPELINE_STEPS:
        step_key = step_info["key"]
        step_name = step_info["name"]
        result = results.get(step_key, {})
        status = result.get("status", "unknown")
        duration = result.get("duration", 0)
        
        status_icon = {"success": "✅", "failed": "❌", "skipped": "⏭️"}.get(status, "❓")
        print(f"  {status_icon} {step_name}: {status}")
    
    return {
        "date": date_str,
        "status": overall_status,
        "total_duration": total_duration,
        "success_count": success_count,
        "failed_count": failed_count,
        "results": results
    }


def get_pipeline_status(date_str=None):
    """获取指定日期的流水线运行状态；默认北京前一天（最新一份日报）"""
    if not date_str:
        date_str = default_analysis_date()
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 获取锁状态
        cursor.execute("""
            SELECT task_name, lock_date, status, started_time, finished_time, pid
            FROM pipeline_lock 
            WHERE task_name = %s AND lock_date = %s
            ORDER BY started_time DESC LIMIT 1
        """, (TASK_NAME, date_str))
        lock = cursor.fetchone()
        
        # 获取日志
        cursor.execute("""
            SELECT step, status, message, duration, retry_count, start_time, end_time, created_time
            FROM pipeline_logs 
            WHERE run_date = %s
            ORDER BY created_time DESC
            LIMIT 20
        """, (date_str,))
        logs = cursor.fetchall()
        conn.close()
        
        # 转换时间格式
        for log in logs:
            for key in ["start_time", "end_time", "created_time"]:
                if log.get(key) and hasattr(log[key], "isoformat"):
                    log[key] = log[key].isoformat()
        
        if lock:
            for key in ["started_time", "finished_time", "lock_date"]:
                if lock.get(key) and hasattr(lock[key], "isoformat"):
                    lock[key] = lock[key].isoformat()
        
        return {
            "date": date_str,
            "lock": lock,
            "logs": logs,
            "latest_status": lock["status"] if lock else "not_run"
        }
    except Exception as e:
        print(f"获取流水线状态失败: {e}")
        return {"date": date_str, "latest_status": "error", "lock": None, "logs": [], "error": str(e)}


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="AI行业情报自动化流水线")
    parser.add_argument("--date", help="运行日期 (YYYY-MM-DD)，默认今天")
    parser.add_argument("--skip", nargs="*", help="跳过的步骤 (collect/events/products/trends/report)")
    parser.add_argument("--status", action="store_true", help="只查看状态，不运行")
    parser.add_argument("--force", action="store_true", help="强制运行（忽略锁）")
    
    args = parser.parse_args()
    
    if args.status:
        status = get_pipeline_status(args.date)
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        if args.force:
            print("⚠️  强制运行模式，忽略任务锁")
            # 强制释放现有锁
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE pipeline_lock SET status = 'failed', finished_time = NOW()
                    WHERE task_name = %s AND lock_date = %s AND status = 'running'
                """, (TASK_NAME, args.date or default_analysis_date()))
                conn.commit()
                conn.close()
            except:
                pass
        
        result = run_daily_pipeline(args.date, args.skip)
        print("\n最终结果:")
        print(json.dumps({
            "date": result["date"],
            "status": result["status"],
            "total_duration": result["total_duration"],
            "success_count": result["success_count"],
            "failed_count": result["failed_count"]
        }, ensure_ascii=False, indent=2))
