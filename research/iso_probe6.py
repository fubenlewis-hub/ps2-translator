# -*- coding: utf-8 -*-
"""第八阶段：DATA5.BIN 文本区结构确认 + 全文总量统计。"""
import io, struct, pycdlib

TM3 = r"E:\桌面\心跳回忆\Tokimeki Memorial 3 [Japan][SLPM-65080]心跳回忆3\Tokimeki Memorial 3 [NTSC-J] [SLPM-65080].iso"

def read_iso(path, iso_path, size=0, offset=0):
    iso = pycdlib.PyCdlib(); iso.open(path)
    buf = io.BytesIO()
    iso.get_file_from_iso_fp(buf, iso_path=iso_path)
    iso.close()
    d = buf.getvalue()
    return d[offset:offset+size] if size else d

KANA = set("ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわゐゑをんゔゕゖ"
           "ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲンヴヵヶ")

print("[1] DATA5.BIN 文本区上下文（@0x19BB40 起 512 字节 hex+ascii）")
d5 = read_iso(TM3, "/DATA5.BIN;1")
reg = d5[0x19BB40:0x19BB40+512]
for i in range(0, 512, 16):
    chunk = reg[i:i+16]
    hx = " ".join("%02x" % b for b in chunk)
    asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    print("%08x  %-48s  %s" % (0x19BB40+i, hx, asc))

print()
print("[2] 文本前 16 字节（判断长度前缀/指针）")
print(d5[0x19BBAD-16:0x19BBAD].hex(" "))

print()
print("[3] DATA5.BIN 文本总量统计（kana>=8 的 run）")
def stats(data):
    runs = []
    i = 0; n = len(data)
    while i < n:
        b0 = data[i]
        ch = None; l = 1
        if 0x81 <= b0 <= 0x9f or 0xe0 <= b0 <= 0xef:
            if i+1 < n and 0x40 <= data[i+1] <= 0xfc and data[i+1] != 0x7f:
                ch = bytes(data[i:i+2]).decode("cp932","replace"); l = 2
        elif 0x20 <= b0 < 0x7f:
            ch = chr(b0)
        elif b0 in (0x0a, 0x0d): ch = "\n"
        if ch is None or ch == "\ufffd":
            i += 1; continue
        start = i; run = [ch]; i += l
        while i < n:
            b0 = data[i]; c2=None; l2=1
            if 0x81 <= b0 <= 0x9f or 0xe0 <= b0 <= 0xef:
                if i+1 < n and 0x40 <= data[i+1] <= 0xfc and data[i+1] != 0x7f:
                    c2 = bytes(data[i:i+2]).decode("cp932","replace"); l2=2
            elif 0x20 <= b0 < 0x7f: c2 = chr(b0)
            elif b0 in (0x0a, 0x0d): c2 = "\n"
            if c2 is None or c2 == "\ufffd": break
            run.append(c2); i += l2
        text = "".join(run)
        kana = sum(1 for c in text if c in KANA)
        if kana >= 8:
            runs.append((start, text, kana))
    return runs

r5 = stats(d5)
print("DATA5.BIN kana>=8 runs:", len(r5))
total_chars = sum(len(t) for _, t, _ in r5)
print("total chars:", total_chars)
# 分布
import collections
lens = [len(t) for _, t, _ in r5]
print("len dist: <20:%d 20-60:%d 60-120:%d >120:%d" % (
    sum(1 for x in lens if x<20), sum(1 for x in lens if 20<=x<60),
    sum(1 for x in lens if 60<=x<120), sum(1 for x in lens if x>=120)))

print()
print("[4] DATA3.BIN 同类统计")
d3 = read_iso(TM3, "/DATA3.BIN;1")
r3 = stats(d3)
print("DATA3.BIN kana>=8 runs:", len(r3), "total chars:", sum(len(t) for _, t, _ in r3))

print()
print("[5] ELF 同类统计")
elf = read_iso(TM3, "/SLPM_650.80;1")
re_ = stats(elf)
print("ELF kana>=8 runs:", len(re_), "total chars:", sum(len(t) for _, t, _ in re_))

print()
print("[6] 示例：DATA5.BIN 前 20 条文本")
for off, t, k in r5[:20]:
    print("  @%08x: %s" % (off, t[:60].replace("\n", "\\n")))
