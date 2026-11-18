# -*- coding: utf-8 -*-
"""本机 Python 未装 tcl/tk 时，给 venv 放一个 tkinter 桩模块（PEP 562）。

部分依赖（如 wxauto 系）在顶层 import tkinter；wechatauto 通常用不到，
但缺桩会直接 ImportError。正式安装 tcl/tk 后可删除本桩（Lib 目录优先于 site-packages）。
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

STUB = '''# -*- coding: utf-8 -*-
"""tkinter stub：本机 Python 未安装 tcl/tk 时满足顶层 import（PEP 562）。"""


class _Dummy:
    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return _Dummy()

    def __getattr__(self, name):
        return _Dummy()


def __getattr__(name):
    return _Dummy()
'''

target = Path(sys.prefix) / "Lib" / "site-packages" / "tkinter.py"
target.write_text(STUB, "utf-8")
print(f"[stub] 已写入 {target}")
