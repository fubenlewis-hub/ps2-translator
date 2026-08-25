# -*- coding: utf-8 -*-
"""第六阶段：TM2 剩余 TOC + 场景文件文本探测；TM3 文本解码采样。"""
import io, struct, pycdlib

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

e = toc(TM2)
print("TM2 DATA.DAT entries:", len(e))
# 保存完整清单
with open(r"E:\桌面\心跳回忆\ps2-translator\research\tm2_datatoc.txt", "w", encoding="utf-8") as f:
    for off, sz, name in e:
        f.write("%08x %10d %s\n" % (off, sz, name))
# 输出 110 之后的部分(简)
for off, sz, name in e[108:]:
    pass
print("=== entries 110+ (非 VOICE) ===")
n = 0
for off, sz, name in e:
    if not name.startswith("VOICE") and name.find("BGM") < 0 and name.find("CISE") < 0:
        print("  %08x %10d %s" % (off, sz, name))
        n += 1
    if n > 60:
        break

print()
print("=== TM2 场景文件文本探测 ===")
for name in ("0\\TITLE00.BIN", "MAINMENU.BIN", "1\\100.BIN", "2\\2000.BIN"):
    ent = [x for x in e if x[2] == name]
    if not ent:
        print("  (not found)", name); continue
    off, sz, _ = ent[0]
    d = read_iso(TM2, "/DATA.DAT;1", size=min(sz, 8192), offset=off)
    print("--- %s  off=%08x sz=%d ---" % (name, off, sz))
    print("head:", d[:32].hex(" "))
    # 统计可打印 sjis 比例
    print("head ascii:", "".join(chr(b) if 32 <= b < 127 else "." for b in d[:96]))

print()
print("=" * 80)
print("TM3 DATA2.BIN 密集区解码采样")
d2 = read_iso(TM3, "/DATA2.BIN;1")
for off in (0x07a48000, 0x0860b000, 0x08e0c000, 0x07a32000):
    chunk = d2[off:off+768]
    try:
        s = chunk.decode("cp932", "replace")
    except Exception:
        s = ""
    vis = "".join(ch if (0x20 <= ord(ch) < 0x7f or 0x3040 <= ord(ch) <= 0x9fff or ch in "\n\r\t") else "." for ch in s)
    print("--- @%08x ---" % off)
    print(vis[:240])
