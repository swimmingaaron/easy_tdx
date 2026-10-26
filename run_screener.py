#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_screener.py (兼容入口)

现已重命名升级为 run_scanner.py。
执行本脚本将自动透明重定向至 run_scanner.py 并传入全部参数。
"""
import sys

if __name__ == "__main__":
    import run_scanner
    run_scanner.main()
