# -*- coding: utf-8 -*-
"""第七阶段：Shift-JIS 文本定位（以假名/可读字符运行为信号）。
扫描 TM3 ELF、DATA*.BIN、TM2 场景文件，寻找真实日语文本。"""
import io, struct, pycdlib, re

TM2 = r"E:\桌面\心跳回忆\Tokimeki Memorial 2 - Music Video Clips - Circus de Ai Imashou [Japan][SLPM-65118]心跳回忆2\Tokimeki Memorial 2 - Music Video Clips - Circus de Ai Imashou [NTSC-J] [SLPM-65118].iso"
TM3 = r"E:\桌面\心跳回忆\Tokimeki Memorial 3 [Japan][SLPM-65080]心跳回忆3\Tokimeki Memorial 3 [NTSC-J] [SLPM-65080].iso"

def read_iso(path, iso_path, size=0, offset=0):
    iso = pycdlib.PyCdlib(); iso.open(path)
    buf = io.BytesIO()
    iso.get_file_from_iso_fp(buf, iso_path=iso_path)
    iso.close()
    d = buf.getvalue()
    return d[offset:offset+size] if size else d

def toc(path):
    d = read_iso(path, "/DATA.DAT;1", size=0x3000)
    entries = []
    for i in range(384):
        p = i * 32
        off, sz = struct.unpack_from("<II", d, p)
        name = d[p+8:p+32].split(b"\x00")[0]
        if not name:
            break
        entries.append((off, sz, name.decode("ascii", "replace")))
    return entries

KANA = set("ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわゐゑをんゔゕゖ"
           "ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲンヴヵヶ")

def text_runs(data, min_run=4, max_print=6):
    """用 cp932 解码数据，提取'可读文本运行'，返回 [(offset, text)] 按假名数排序。"""
    out = []
    i = 0
    n = len(data)
    while i < n:
        b0 = data[i]
        ch = None
        l = 1
        if 0x81 <= b0 <= 0x9f or 0xe0 <= b0 <= 0xef:
            if i + 1 < n and (0x40 <= data[i+1] <= 0xfc and data[i+1] != 0x7f):
                ch = bytes(data[i:i+2]).decode("cp932", "replace")
                l = 2
        elif 0x20 <= b0 < 0x7f:
            ch = chr(b0)
        elif b0 in (0x0a, 0x0d, 0x09):
            ch = "\n"
        if ch is None or ch == "\ufffd":
            if out and (i - out[-1][0] - len(out[-1][1]) >= 1):
                pass
            i += 1
            continue
        # 开始/延伸运行
        start = i
        run = [ch]
        i += l
        while i < n:
            b0 = data[i]
            c2 = None
            l2 = 1
            if 0x81 <= b0 <= 0x9f or 0xe0 <= b0 <= 0xef:
                if i + 1 < n and (0x40 <= data[i+1] <= 0xfc and data[i+1] != 0x7f):
                    c2 = bytes(data[i:i+2]).decode("cp932", "replace")
                    l2 = 2
            elif 0x20 <= b0 < 0x7f:
                c2 = chr(b0)
            elif b0 in (0x0a, 0x0d, 0x09):
                c2 = "\n"
            if c2 is None or c2 == "\ufffd":
                break
            run.append(c2)
            i += l2
        text = "".join(run)
        # 过滤：至少 min_run 个字符，且包含假名或日文汉字较多的才算候选
        kana_n = sum(1 for c in text if c in KANA)
        if len(text) >= min_run and (kana_n >= 1 or len(text) >= 8):
            out.append((start, text, kana_n))
    out.sort(key=lambda x: -x[2])
    return out

def scan(name, data, top=8):
    runs = text_runs(data)
    print("  [%s] size=%d runs>=min: %d" % (name, len(data), len(runs)))
    shown = 0
    for off, text, kana in runs[:top]:
        t = text.replace("\n", "\\n")
        print("    @%08x kana=%d: %s" % (off, kana, t[:80]))
        shown += 1

print("=" * 80)
print("[1] TM3 ELF SLPM_650.80 文本扫描")
elf = read_iso(TM3, "/SLPM_650.80;1")
scan("SLPM_650.80", elf)

print("=" * 80)
print("[2] TM3 DATA2.BIN 全文扫描（152MB）")
d2 = read_iso(TM3, "/DATA2.BIN;1")
scan("DATA2.BIN", d2)

print("=" * 80)
print("[3] TM3 DATA4.BIN 扫描（33MB）")
d4 = read_iso(TM3, "/DATA4.BIN;1")
scan("DATA4.BIN", d4)

print("=" * 80)
print("[4] TM3 DATA3.BIN 扫描（27MB, ATP）")
d3 = read_iso(TM3, "/DATA3.BIN;1")
scan("DATA3.BIN", d3)

print("=" * 80)
print("[5] TM3 DATA1.BIN 首尾各 16MB 扫描")
d1 = read_iso(TM3, "/DATA1.BIN;1", size=16*1048576)
scan("DATA1.BIN head16M", d1)
d1t = read_iso(TM3, "/DATA1.BIN;1", size=16*1048576, offset=614307840-16*1048576)
scan("DATA1.BIN tail16M", d1t)

print("=" * 80)
print("[6] TM3 DATA5.BIN 扫描（10MB MIPS）")
d5 = read_iso(TM3, "/DATA5.BIN;1")
scan("DATA5.BIN", d5)

print("=" * 80)
print("[7] TM2 场景文件文本扫描")
e = toc(TM2)
for nm in ("0\\TITLE00.BIN", "MAINMENU.BIN", "1\\100.BIN", "1\\101.BIN", "2\\2000.BIN", "2\\2001.BIN", "3\\300.BIN", "4\\400.BIN"):
    ent = [x for x in e if x[2] == nm]
    if not ent:
        print("  (missing) " + nm); continue
    off, sz, _ = ent[0]
    d = read_iso(TM2, "/DATA.DAT;1", size=sz, offset=off)
    scan(nm, d, top=4)
