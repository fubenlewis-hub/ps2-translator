# -*- coding: utf-8 -*-
"""第四阶段：精细十六进制探测。
1) TM2 DATA.DAT 前 224 字节带偏移量输出，人工分析 TOC
2) TM3 DATA4.BIN 字形区结构
3) TM3 DATA2.BIN 全盘扫描 Shift-JIS 可打印字符串密度（定位文本所在）
"""
import io, struct, pycdlib

TM2 = r"E:\桌面\心跳回忆\Tokimeki Memorial 2 - Music Video Clips - Circus de Ai Imashou [Japan][SLPM-65118]心跳回忆2\Tokimeki Memorial 2 - Music Video Clips - Circus de Ai Imashou [NTSC-J] [SLPM-65118].iso"
TM3 = r"E:\桌面\心跳回忆\Tokimeki Memorial 3 [Japan][SLPM-65080]心跳回忆3\Tokimeki Memorial 3 [NTSC-J] [SLPM-65080].iso"

def read_file(path, iso_path, size=0):
    iso = pycdlib.PyCdlib(); iso.open(path)
    buf = io.BytesIO()
    iso.get_file_from_iso_fp(buf, iso_path=iso_path)
    iso.close()
    return buf.getvalue()[:size] if size else buf.getvalue()

def hexdump(data, base=0, n=32, width=16):
    for i in range(0, min(len(data), n * width), width):
        chunk = data[i:i+width]
        hx = " ".join("%02x" % b for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print("%08x  %-48s  %s" % (base + i, hx, asc))

print("=" * 80)
print("[1] TM2 DATA.DAT 头 224 字节")
d = read_file(TM2, "/DATA.DAT;1", size=224)
hexdump(d, 0, 14)

print()
print("=" * 80)
print("[2] TM3 DATA4.BIN 头 320 字节")
d4 = read_file(TM3, "/DATA4.BIN;1", size=320)
hexdump(d4, 0, 20)
print("glyph pattern offset:", d4.find(b"\x21\x21\x21\x00"))

print()
print("=" * 80)
print("[3] TM3 大文件 Shift-JIS 字符串扫描（找文本所在文件）")
def sjis_printable_ratio(data, sample_n=2000000, stride=1024):
    # 采样若干 64KB 块，统计可打印 sjis 序列占比
    total_print = 0; total = 0
    rng = range(0, min(len(data), sample_n), 65536)
    if len(data) > sample_n:
        rng = list(rng) + list(range(len(data)-65536, len(data), 65536))[:10]
    for off in rng:
        chunk = data[off:off+65536]
        i = 0
        while i < len(chunk) - 1:
            b0 = chunk[i]
            if 0x81 <= b0 <= 0x9f or 0xe0 <= b0 <= 0xef:  # 双字节 sjis 首字节
                b1 = chunk[i+1]
                if 0x40 <= b1 <= 0xfc and b1 != 0x7f:
                    total_print += 2; total += 2; i += 2; continue
                else:
                    total += 1; i += 1; continue
            if 0x20 <= b0 < 0x7f:
                total_print += 1
            total += 1
            i += 1
    return total_print / total if total else 0

for ip in ("/DATA1.BIN;1", "/DATA2.BIN;1", "/DATA3.BIN;1", "/DATA4.BIN;1", "/DATA5.BIN;1",
           "/BSD_DATA/DATA1.BSD;1", "/BSD_DATA/DATA2.BSD;1", "/BSD_DATA/DATA9.BSD;1"):
    data = read_file(TM3, ip)
    r = sjis_printable_ratio(data)
    print("  %-28s size=%-10d sjis_printable_ratio=%.4f" % (ip, len(data), r))

print()
print("=" * 80)
print("[4] TM3 DATA2.BIN 扫描含大量 Shift-JIS 双字节文本的连续区段（候选文本块）")
d2 = read_file(TM3, "/DATA2.BIN;1")
# 按 4KB 块统计 sjis 双字节占比，找出连续高密度区
block = 4096
scores = []
for off in range(0, len(d2) - block, block):
    chunk = d2[off:off+block]
    double = 0
    i = 0
    while i < len(chunk) - 1:
        b0 = chunk[i]
        if (0x81 <= b0 <= 0x9f or 0xe0 <= b0 <= 0xef) and 0x40 <= chunk[i+1] <= 0xfc and chunk[i+1] != 0x7f:
            double += 1; i += 2
        else:
            i += 1
    scores.append((double, off))
scores.sort(reverse=True)
print("top 25 dense 4KB blocks (sjis-double count, offset):")
for sc, off in scores[:25]:
    print("   %4d  @0x%08x  (%.1f MB)" % (sc, off, off / 1048576))
