# -*- coding: utf-8 -*-
"""
点阵字库生成与注入框架。

生成：用系统字体渲染汉字为 NxN 点阵（1bpp 位图），支持 12x12 / 16x16，
覆盖 GB2312 一级字（3755 常用字）或全部 6763 字 + ASCII + 日文假名。

注入：PS2 游戏字库格式各异，注入逻辑由各游戏插件实现（实现字体格式解析），
本模块提供通用工具：位图数据、字形索引表、替换/扩容策略与降级方案说明。
"""
import json
import logging
import struct
from pathlib import Path

log = logging.getLogger("ps2hantool.font")

try:
    from PIL import Image, ImageDraw, ImageFont
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False
    log.warning("未安装 Pillow，点阵字库生成不可用")


class BitmapFont:
    """生成好的点阵字库。glyphs: {char: bytes}（每字 rows*((w+7)//8) 字节）。"""

    def __init__(self, size=16, chars=None, glyphs=None, width=None):
        self.size = size
        self.width = width or size
        self.chars = chars or []
        self.glyphs = glyphs or {}
        self.bytes_per_glyph = None

    # ---------- 生成 ----------
    @classmethod
    def generate(cls, size=16, charset=None, font_path=None):
        """生成点阵字库。charset: 字符列表/字符串；font_path: TTF（None=默认字体）。"""
        if not HAVE_PIL:
            raise RuntimeError("需要 Pillow 才能生成字库")
        import os

        chars = charset or cls.default_charset()
        # 渲染到放大画布再缩小到目标尺寸，质量更好
        scale = 4
        canvas = Image.new("L", (size * scale, size * scale), 0)
        draw = ImageDraw.Draw(canvas)
        try:
            if font_path and os.path.exists(font_path):
                font = ImageFont.truetype(font_path, size * scale)
            else:
                # 尝试常见中文字体，兜底默认
                for cand in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
                             r"C:\Windows\Fonts\simsun.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                             "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
                    if os.path.exists(cand):
                        font = ImageFont.truetype(cand, size * scale)
                        break
                else:
                    font = ImageFont.load_default()
        except Exception as e:
            log.warning("字体加载失败，使用默认: %s", e)
            font = ImageFont.load_default()

        glyphs = {}
        for ch in chars:
            canvas.paste(0, (0, 0, canvas.width, canvas.height))
            bbox = draw.textbbox((0, 0), ch, font=font)
            draw.text((0, 0), ch, font=font, fill=255)
            # 裁剪到字形
            img = canvas.crop(bbox).resize((size, size), Image.LANCZOS)
            img = img.point(lambda p: 255 if p >= 128 else 0)
            glyphs[ch] = _to_1bpp(img)
        return cls(size=size, chars=list(chars), glyphs=glyphs)

    @staticmethod
    def default_charset():
        """常用汉字（GB2312 一级 3755 + 常用标点 + ASCII + 日文假名）。"""
        base = list("，。、！？：；（）「」『』【】《》…—～·％＊　0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                    "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをんぁぃぅぇぉっゃゅょ"
                    "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンァィゥェォッャュョ")
        try:
            # GB2312 一级汉字
            from ..text.gb2312 import GB2312_L1
            base.extend(GB2312_L1)
        except Exception:
            pass
        # 去重保序
        seen = set()
        out = []
        for c in base:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return "".join(out)

    # ---------- 持久化 ----------
    def save(self, base_path, fmt="bin"):
        """保存字库数据 + 索引 json。base_path 不带扩展名。"""
        base_path = Path(base_path)
        if fmt == "bin":
            with open(str(base_path) + ".bin", "wb") as f:
                for ch in self.chars:
                    f.write(self.glyphs[ch])
            meta = {
                "size": self.size, "width": self.width,
                "bytes_per_glyph": len(self.glyphs[self.chars[0]]) if self.chars else 0,
                "chars": self.chars,
                "order": "chars order matches file order",
            }
            Path(str(base_path) + ".json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
        elif fmt == "png":
            self.save_png(str(base_path) + ".png")
        return base_path

    def save_png(self, path, cols=64):
        """把字形排布成图集 PNG（便于人工查看/替换游戏贴图字库）。"""
        if not HAVE_PIL:
            return
        n = len(self.chars)
        rows = (n + cols - 1) // cols
        img = Image.new("L", (cols * self.width, rows * self.size), 0)
        for i, ch in enumerate(self.chars):
            data = self.glyphs[ch]
            glyph = _from_1bpp(data, self.size, self.width)
            x = (i % cols) * self.width
            y = (i // cols) * self.size
            img.paste(glyph, (x, y))
        img.save(path)


def _to_1bpp(img):
    """PIL L 图像（size*size）-> 1bpp 行字节流（每行 (w+7)//8 字节，高位在前）。"""
    w, h = img.size
    bw = (w + 7) // 8
    out = bytearray()
    px = img.load()
    for y in range(h):
        for xb in range(bw):
            byte = 0
            for bit in range(8):
                x = xb * 8 + bit
                if x < w and px[x, y] > 0:
                    byte |= (0x80 >> bit)
            out.append(byte)
    return bytes(out)


def _from_1bpp(data, size, width=None):
    width = width or size
    bw = (width + 7) // 8
    img = Image.new("L", (width, size), 0)
    px = img.load()
    for y in range(size):
        for xb in range(bw):
            byte = data[y * bw + xb]
            for bit in range(8):
                x = xb * 8 + bit
                if x < width and (byte & (0x80 >> bit)):
                    px[x, y] = 255
    return img


# ---------------- 注入框架 ----------------

class FontInjector:
    """
    字库注入器框架。子类/插件实现：
      - analyze(): 解析游戏字库格式，返回 {offset, glyph_size, mapping, palette...}
      - inject(bitmap_font): 将生成的字库写入游戏文件并修正映射。
    降级方案由调用方根据 result 的 status 决定。
    """

    def analyze(self, ctx):
        raise NotImplementedError

    def inject(self, ctx, bitmap_font, progress_cb=None):
        raise NotImplementedError

    @staticmethod
    def degrade_plan(reason):
        return {
            "status": "degraded",
            "reason": reason,
            "plans": [
                "1. 字模替换：在游戏原字库内做码点重映射（不扩容）",
                "2. 同音字/拆分显示：无法编码的汉字用同音字代替（在报告中列出）",
                "3. 文本预翻译替换：用术语表将生僻字替换为常用字",
            ],
        }
