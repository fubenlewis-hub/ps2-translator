# -*- coding: utf-8 -*-
"""第二阶段调研：读取 SYSTEM.CNF、完整文件列表、容器头部分析。全部只读。"""
import os, struct, pycdlib

TM2 = r"E:\桌面\心跳回忆\Tokimeki Memorial 2 - Music Video Clips - Circus de Ai Imashou [Japan][SLPM-65118]心跳回忆2\Tokimeki Memorial 2 - Music Video Clips - Circus de Ai Imashou [NTSC-J] [SLPM-65118].iso"
TM3 = r"E:\桌面\心跳回忆\Tokimeki Memorial 3 [Japan][SLPM-65080]心跳回忆3\Tokimeki Memorial 3 [NTSC-J] [SLPM-65080].iso"

def full_list(path):
    iso = pycdlib.PyCdlib(); iso.open(path)
    out = []
    def walk(dp):
        for c in iso.list_children(iso_path=dp):
            n = c.file_identifier().decode("utf-8","replace")
            if n in (".",".."): continue
            full = (dp + "/" + n) if dp != "/" else "/" + n
            out.append((full, c.is_dir(), c.data_length))
            if c.is_dir(): walk(full)
    walk("/")
    iso.close()
    return out

def read_small(iso, path):
    out = b""
    iso.get_file_from_iso_fp(open("NUL","wb"), iso_path=path)
    return None

def extract_to_memory(iso, path, limit=8192):
    import io
    buf = io.BytesIO()
    iso.get_file_from_iso_fp(buf, iso_path=path)
    data = buf.getvalue()
    return data[:limit]

for tag, p in (("TM2", TM2), ("TM3", TM3)):
    iso = pycdlib.PyCdlib(); iso.open(p)
    print("="*90); print(tag, os.path.basename(p))
    # SYSTEM.CNF
    try:
        cnf = extract_to_memory(iso, "/SYSTEM.CNF;1")
        print("--- SYSTEM.CNF ---"); print(cnf.decode("ascii","replace"))
    except Exception as e:
        print("cnf err", e)
    # 完整列表（含子目录文件）
    entries = full_list(p)
    print("--- FULL LIST (%d) ---" % len(entries))
    for full, isdir, size in entries:
        print("%s %12d %s" % ("[D]" if isdir else "   ", size, full))
    iso.close()

# 容器头部 64KB 分析
def head(path, iso_path):
    iso = pycdlib.PyCdlib(); iso.open(path)
    import io
    buf = io.BytesIO()
    iso.get_file_from_iso_fp(buf, iso_path=iso_path)
    d = buf.getvalue()
    iso.close()
    return d

print("="*90); print("CONTAINER HEADERS (first 64 bytes hex + 256 bytes ascii)")
targets = [
    (TM2, "/DATA.DAT;1"),
    (TM3, "/DATA1.BIN;1"), (TM3, "/DATA2.BIN;1"), (TM3, "/DATA3.BIN;1"),
    (TM3, "/DATA4.BIN;1"), (TM3, "/DATA5.BIN;1"), (TM3, "/EVSDATA.BIN;1"),
]
for p, ip in targets:
    d = head(p, ip)
    print("-"*60)
    print(ip, "len(read)=%d" % len(d))
    print(d[:64].hex(" "))
    # 显示可打印 ascii 片段
    s = "".join(chr(b) if 32 <= b < 127 else "." for b in d[:256])
    print(s)
