# -*- coding: utf-8 -*-
"""GB2312 一级汉字（3755 常用字），按区位码生成。"""


def _build():
    out = []
    for qu in range(16, 56):      # 0x10..0x37 -> 0xB0..0xD7
        for wei in range(1, 95):  # 0x01..0x5E -> 0xA1..0xFE
            if qu == 55 and wei > 89:   # 末区只有 89 字
                break
            try:
                ch = bytes([qu + 0xA0, wei + 0xA0]).decode("gb2312")
                out.append(ch)
            except UnicodeDecodeError:
                continue
    return out


GB2312_L1 = _build()
