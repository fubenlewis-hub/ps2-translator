# -*- coding: utf-8 -*-
"""第五阶段：验证 TM2 CISE 内容 + TM3 文本区解码。只读。"""
import io, struct, pycdlib

TM2 = r"E:\桌面\心跳回忆\Tokimeki Memorial 2 - Music Video Clips - Circus de Ai Imashou [Japan][SLPM-65118]心跳回忆2\Tokimeki Memorial 2 - Music Video Clips - Circus de Ai Imashou [NTSC-J] [SLPM-65118].iso"
TM3 = r"E:\桌面\心跳回忆\Tokimeki Memorial 3 [Japan][SLPM-65080]心跳回忆3\Tokimeki Memorial 3 [NTSC-J] [SLPM-65080].iso"

def read_file(path, iso_path, size=0, offset=0):
    iso = pycdlib.PyCdlib(); iso.open(path)
    buf = io.BytesIO()
    iso.get_file_from_iso_fp(buf, iso_path=iso_path)
    iso.close()
    d = buf.getvalue()
    return d[offset:offset+size] if size else d

def hx(data, n=8):
    return " ".join("%02x" % b for b in data[:n])

print("=" * 80)
print("[1] TM2 DATA.DAT TOC 全解析 + CISE00 内容验证")
d = read_file(TM2, "/DATA.DAT;1", size=0x3000)
entries = []
for i in range(384):
    p = i * 32
    off, sz = struct.unpack_from("<II", d, p)
    name = d[p+8:p+32].split(b"\x00")[0]
    if not name:
        break
    entries.append((off, sz, name.decode("ascii", "replace")))
print("TOC entries:", len(entries))
# 打印所有条目的 (字段1, 字段2, name)
for e in entries:
    print("  %08x %08x %s" % (e[0], e[1], e[2]))
# 验证: 在 0x3000 与 0x6000 读取 CISE00 头
for abs_off in (0x3000, 0x6000):
    d0 = read_file(TM2, "/DATA.DAT;1", size=64, offset=abs_off)
    print("  CISE00 @%08x head:" % abs_off, hx(d0, 16))
for abs_off in (0x328, 0x3328):
    d0 = read_file(TM2, "/DATA.DAT;1", size=64, offset=abs_off)
    print("  CISE01 @%08x head:" % abs_off, hx(d0, 16))

print()
print("=" * 80)
print("[2] TM3 DATA2.BIN 密集区 Shift-JIS 解码采样")
d2 = read_file(TM3, "/DATA2.BIN;1")
for off in (0x07a48000, 0x0860b000, 0x08e0c000, 0x07a32000):
    chunk = d2[off:off+512]
    try:
        s = chunk.decode("cp932", "replace")
    except Exception:
        s = "<decode err>"
    vis = "".join(ch if (0x20 <= ord(ch) < 0x7f or 0x3000 <= ord(ch) <= 0x9fff) else "." for ch in s)
    print("--- @%08x ---" % off)
    print(vis[:200])

print()
print("=" * 80)
print("[3] TM3 DATA2.BIN 头部 u32 解读（候选 TOC）")
u32s = struct.unpack_from("<16I", d2, 0)
print([hex(x) for x in u32s])
# 0x68 处是什么? 打印 0x68-0x100
print("at 0x68:", d2[0x68:0x100].hex(" "))
# 0x490 处?
print("at 0x490:", d2[0x490:0x4C0].hex(" "))
