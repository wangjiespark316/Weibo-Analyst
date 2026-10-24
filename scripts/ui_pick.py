#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博扫一扫相册选图助手（服务器端，经 frp adb 控制小米12）。
作用：在已打开微博扫一扫(TakePhotoActivityV3)的前提下，
     确保"最近项目"相册网格展开，并点击第一张图片（最新推送的登录二维码）。
通过 uiautomator dump 动态解析控件坐标，避免硬编码坐标在不同抽屉状态下失效。
退出码：0=已点击第一张图；1=未能找到/点击。
"""
import re
import subprocess
import sys
import time

DEV = "127.0.0.1:15555"


def adb(*args, timeout=20):
    try:
        r = subprocess.run(["adb", "-s", DEV, *args],
                           capture_output=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:  # noqa
        return 1, b"", str(e).encode()


def dump_ui():
    adb("shell", "uiautomator", "dump", "/sdcard/u.xml")
    time.sleep(0.8)
    rc, out, _ = adb("shell", "cat", "/sdcard/u.xml")
    return out.decode("utf-8", "ignore")


def bounds_center(node):
    b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
    if not b:
        return None
    x1, y1, x2, y2 = map(int, b.groups())
    return (x1 + x2) // 2, (y1 + y2) // 2


def find_node(xml, rid_substr):
    for m in re.finditer(r"<node[^>]*>", xml):
        n = m.group(0)
        if rid_substr in n:
            return n
    return None


def first_media_center(xml):
    """在 mediaGrid 之后找第一个 ImageView（图片格）的中心坐标。"""
    i = xml.find("id/mediaGrid")
    if i < 0:
        return None
    seg = xml[i:i + 8000]
    m = re.search(r"ImageView[^>]*?bounds=\"\[(\d+),(\d+)\]\[(\d+),(\d+)\]\"", seg)
    if not m:
        m = re.search(r"bounds=\"\[(\d+),(\d+)\]\[(\d+),(\d+)\]\"", seg)
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return (x1 + x2) // 2, (y1 + y2) // 2


def tap(x, y):
    adb("shell", "input", "tap", str(x), str(y))


def main():
    xml = dump_ui()
    # 1) 网格未展开 -> 先点展开按钮
    if "id/mediaGrid" not in xml:
        exp = find_node(xml, "id/expandCollapseBtn")
        if exp is None:
            print("NO_EXPAND_BTN")
            return 1
        c = bounds_center(exp)
        if not c:
            print("NO_EXPAND_CENTER")
            return 1
        print("tap expand", c)
        tap(*c)
        time.sleep(2.2)
        xml = dump_ui()
    # 2) 点第一张图
    first = first_media_center(xml)
    if not first:
        print("NO_FIRST_MEDIA")
        return 1
    print("tap first media", first)
    tap(*first)
    time.sleep(1.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
