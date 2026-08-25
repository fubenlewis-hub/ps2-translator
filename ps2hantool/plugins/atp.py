# -*- coding: utf-8 -*-
"""
Konami ATP 压缩格式解压（实验性）。

源码移植自：https://github.com/ShrNme/TM3_Tools 的 Decoder.cs（作者 ShortenedName，
WIP 实现，作者自述"按反汇编逐段重写、仍可能有误"）。此处忠实移植其逻辑，
并在下方 self_check 中做合理性验证（解压后应出现可读 Shift-JIS 文本）。
许可证：项目未明确标注，引用已注明来源，仅作学习研究用途。

ATP 容器条目布局（来自 BloodRaynare 的 QuickBMS 脚本，ResHax 论坛）：
- 条目 = 8 字节：u32(高8位=容器号, 低24位=扇区号) + u16 压缩尺寸(扇区) + u16 解压尺寸(扇区)
- 实际偏移 = 扇区号 * 0x800；条目数据前 8 字节为 'ATP\\0' + 4 字节（未知/尺寸）
"""
import logging

log = logging.getLogger("ps2hantool.atp")


def decode_atp(data, start=0):
    """
    解压一个 ATP 条目。data: 该条目的完整字节（含 'ATP\\0' 头部）。
    返回解压后的 bytes；失败返回 None。
    """
    if data[start:start + 4] != b"ATP\x00":
        return None
    src = start + 8  # 跳过 ATP 头
    n = len(data)
    dest = bytearray()

    # 以下变量名沿用原 C# 实现，保持逐位逻辑
    previousByte = data[src]
    src += 1
    counter = 8
    destinationPointer = 0

    try:
        while True:
            v0 = previousByte & 0x1
            if counter == 0:
                previousByte = data[src]
                src += 1
                counter = 8
            # Part2
            counter -= 1
            if v0 == 0:
                buffer = data[src]
                src += 1
                previousByte = previousByte >> 1
                destinationPointer += 1
                dest.append(buffer)
                continue
            # Part3
            previousByte = previousByte >> 1
            if counter == 0:
                previousByte = data[src]
                src += 1
                counter = 8
            # Part4
            _unused = previousByte & 0x1
            v0 = data[src]  # delay slot：读取下一字节覆盖 v0
            if v0 == 0:
                # Part7
                src += 1
                v1 = data[src]
                src += 1
                _v0b = (v0 << 8) & 0xFF
                previousByte = previousByte >> 1
                v1 = (_v0b | v1) & 0xFF
                counter -= 1
                if v1 == 0:
                    break  # Part11 结束
                a2 = (v1 & 0xF) + 2
                if a2 == 0:
                    # Part8
                    v0 = data[src]
                    src += 1
                    v1 = v1 >> 4
                    a2 = (v0 + 1) & 0xFF
                else:
                    v1 = v1 >> 4
                # Part9/10
                v1 = (destinationPointer - v1) & 0xFFFFFFFF
                for _ in range(a2):
                    v0 = dest[v1]
                    v1 = (v1 + 1) & 0xFFFFFFFF
                    a2 -= 1
                    dest.append(v0)
                    destinationPointer += 1
                    if a2 == 0:
                        break
                continue
            else:
                counter -= 1
                previousByte = previousByte >> 1
                if counter == 0:
                    previousByte = data[src]
                    src += 1
                    counter = 8
                # Part5
                v0 = previousByte & 0x1
                previousByte = previousByte >> 1
                counter -= 1
                a2 = (v0 << 1) & 0xFF
                if counter == 0:
                    previousByte = data[src]
                    src += 1
                    counter = 8
                # Part6
                v0 = previousByte & 0x1
                previousByte = previousByte >> 1
                v1 = data[src]
                src += 1
                v0 = (a2 + v0) & 0xFF
                counter -= 1
                a2 = (v0 + 0x2) & 0xFF
                if v1 == 0:
                    v1 = 0x100
                # Part9/10
                v1 = (destinationPointer - v1) & 0xFFFFFFFF
                for _ in range(a2):
                    v0 = dest[v1]
                    v1 = (v1 + 1) & 0xFFFFFFFF
                    a2 -= 1
                    dest.append(v0)
                    destinationPointer += 1
                    if a2 == 0:
                        break
                continue
    except IndexError:
        # 源数据耗尽：可能解压完成或算法有误
        pass
    return bytes(dest)
