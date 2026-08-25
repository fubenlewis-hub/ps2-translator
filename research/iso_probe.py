# -*- coding: utf-8 -*-
"""第三阶段：容器内部格式探测。只读。
1) TM2 DATA.DAT 的 TOC 结构解析（尝试多种解释并校验）
2) TM3 BSD_DATA/DATA1.BSD 头部
3) TM3 DATA2.BIN 字形区域分析
"""
import io, struct, pycdlib

TM2 = r"E:\桌面\心跳回忆\Tokimeki Memorial 2 - Music Video Clips - Circus de Ai Imashou [Japan][SLPM-65118]心跳回忆2\Tokimeki Memorial 2 - Music Video Clips - Circus de Ai Imashou [NTSC-J] [SLPM-65118].iso"
TM3 = r"E:\桌面\心跳回忆\Tokimeki Memorial 3 [Japan][SLPM-65080]心跳回忆3\Tokimeki Memorial 3 [NTSC-J] [SLPM-65080].iso"

def read_file(path, iso_path, size=0):
    iso = pycdlib.PyCdlib(); iso.open(path)
    buf = io.BytesIO()
    iso.get_file_from_iso_fp(buf, iso_path=iso_path)
    iso.close()
    d = buf.getvalue()
    return d[:size] if size else d

print("=" * 80)
print("[1] TM2 DATA.DAT TOC 探测")
d = read_file(TM2, "/DATA.DAT;1", size=0x4000)
print("file head len:", len(d))
# 尝试: (u32 off, u32 size, name[32])，起始于 0，条目40字节
def try_parse(data, off_field, size_field, name_len, entry_size, count):
    entries = []
    base = 0
    for i in range(count):
        p = i * entry_size
        off = struct.unpack_from("<I", data, p + off_field)[0]
        sz = struct.unpack_from("<I", data, p + size_field)[0]
        name = data[p:p+entry_size][:name_len].split(b"\x00")[0]
        if not name:
            break
        entries.append((off, sz, name))
    return entries

# 解释1: 第一字段offset 第二字段size，name[32]
for e in try_parse(d, 0, 4, 32, 40, 8):
    print("  off,size,name:", e)
print("  --- 若第一字段是size,第二字段是offset ---")
for e in try_parse(d, 4, 0, 32, 40, 8):
    print("  size,off,name:", e)
# 条目可能为 0x30 字节(48): off,size,name[40]
print("  --- entry=48, name[40] ---")
for e in try_parse(d, 0, 4, 40, 48, 8):
    print("  off,size,name:", e)

print()
print("=" * 80)
print("[2] TM3 BSD_DATA/DATA1.BSD 头部")
b = read_file(TM3, "/BSD_DATA/DATA1.BSD;1", size=0x800)
print(b[:64].hex(" "))
print("".join(chr(x) if 32 <= x < 127 else "." for x in b[:256]))
print("first 4 bytes as u32 LE:", struct.unpack_from("<I", b, 0)[0])
print("possible counts at 0x04/0x08:", struct.unpack_from("<I", b, 4)[0], struct.unpack_from("<I", b, 8)[0])
# 检查是否类似 TOC: (off,size,name)
for e in try_parse(b, 0, 4, 32, 40, 12):
    print("  off,size,name:", e)

print()
print("=" * 80)
print("[3] TM3 DATA2.BIN 结构分析（疑似字库/纹理容器）")
d2 = read_file(TM3, "/DATA2.BIN;1", size=0x20000)
print("head64:", d2[:64].hex(" "))
u32s = struct.unpack_from("<8I", d2, 0)
print("first 8 u32:", [hex(x) for x in u32s])
# 找字形图案区: 搜索 "!!!.))).111" 的重复模式
idx = d2.find(b"!!!.)))")
print("glyph pattern '!!!.)))' at offset:", hex(idx) if idx >= 0 else "not found in first 128KB")
if idx >= 0:
    # 打印该区域前后 hex
    print("around glyph region:")
    print(d2[idx-64:idx+128].hex(" "))
    print("".join(chr(x) if 32 <= x < 127 else "." for x in d2[idx-64:idx+128]))
    # 检查是否每字形固定大小: 尝试找间隔规律
    import re
    pat = re.compile(rb"[\x21\x29\x31\x39\x42\x4a\x52\x5a\x63\x6b\x73\x7b]{3}[\x00]")
    m = list(pat.finditer(d2))
    print("regex glyph hits:", len(m))
    if m:
        gaps = [m[i+1].start() - m[i].start() for i in range(min(10, len(m)-1))]
        print("gaps:", gaps)

print()
print("=" * 80)
print("[4] TM3 DATA3.BIN 头部(ATP) 与 DATA5.BIN (MIPS)")
d3 = read_file(TM3, "/DATA3.BIN;1", size=0x100)
print("ATP head:", d3[:16].hex(" "))
d5 = read_file(TM3, "/DATA5.BIN;1", size=0x100)
print("DATA5 head:", d5[:16].hex(" "))
