# -*- coding: utf-8 -*-
"""通用 Shift-JIS 文本提取器。

核心思路：以“可读文本运行”为单位扫描二进制（假名/汉字/ASCII 连续区段），
任何非文本字节都会终止当前运行，因此天然按二进制缝隙切分文本块。
所有游戏插件可复用本模块。
"""
import re

from .model import TextEntry, TextFile, CAT_DIALOG, CAT_OTHER
from .gb2312 import GB2312_L1


def _jis_level1_kanji():
    """JIS X0208 第一水準汉字（2965 字），按区号 16-47 生成。"""
    out = []
    for qu in range(16, 48):
        for wei in range(1, 95):
            try:
                ch = bytes([qu + 0xA0, wei + 0xA0]).decode("cp932")
                if len(ch) == 1:
                    out.append(ch)
            except UnicodeDecodeError:
                continue
    return set(out)


# 常用汉字白名单（JIS 一级 + GB2312 一级）——用于过滤压缩流噪声
COMMON_KANJI = set(GB2312_L1) | _jis_level1_kanji()

# 日文假名集合（用于给文本运行“打分”）
KANA = set(
    "ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとど"
    "なにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわゐゑをん"
    "ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトド"
    "ナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲン"
    "ヴヵヶヶー"
)
# 允许出现在文本运行内的 ASCII 可读字符
ASCII_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
               " 　,.。、!?！？:：;；()（）[]「」『』【】<>《》-–—/\\|~～+＊*%％#&@'\"=＿_"
               "♡♥★☆♪※→←↑↓①②③④⑤⑥⑦⑧⑨⑩・…△▲▽▼○●◎◇□■℃")
# 全角/半角标点与符号（不提升“有效字符”计数，但允许出现在运行内部）
PUNCT = set(" 　,.。、!?！？:：;；()（）[]「」『』【】<>《》-–—/\\|~～+＊*%％#&@'\"=＿_"
            "♡♥★☆♪※→←↑↓①②③④⑤⑥⑦⑧⑨⑩・…△▲▽▼○●◎◇□■℃々ー")
# 换行字节（保留在运行内部，回写时还原为游戏换行）
NEWLINE_BYTES = (0x0A, 0x0D, 0x09)


class SjisRunExtractor:
    """Shift-JIS 可读文本运行提取器。

    min_run: 最少有效字符数（假名/汉字/字母数字）
    min_kana: 最少假名数（提升精确度）
    min_semantic: 最少“语义字符”（假名+汉字）数，过滤二进制噪声
    drop_dups: 去重（游戏常存多份相同文本）
    """

    def __init__(self, min_run=4, min_kana=1, min_semantic=2, drop_dups=True,
                 rare_filter=True):
        self.min_run = min_run
        self.min_kana = min_kana
        self.min_semantic = min_semantic
        self.drop_dups = drop_dups
        self.rare_filter = rare_filter   # 生僻字过滤（压缩流扫描建议开启）
        self._seen = set()

    def _iter_chars(self, data):
        """
        逐字符解码 cp932。
        yield (ch, byte_len, offset)：ch=None 表示非文本字节（应终止运行）；
        文本字符为 str；换行(0x0A/0x0D/0x09) yield "\n"。
        """
        i, n = 0, len(data)
        while i < n:
            b0 = data[i]
            # 换行/制表
            if b0 in NEWLINE_BYTES:
                yield "\n", 1, i
                i += 1
                continue
            # Shift-JIS 双字节
            if 0x81 <= b0 <= 0x9F or 0xE0 <= b0 <= 0xEF:
                if i + 1 < n and 0x40 <= data[i + 1] <= 0xFC and data[i + 1] != 0x7F:
                    try:
                        ch = bytes(data[i:i + 2]).decode("cp932")
                        yield ch, 2, i
                        i += 2
                        continue
                    except UnicodeDecodeError:
                        pass
                yield None, 0, i
                i += 1
                continue
            # ASCII 可打印
            if 0x20 <= b0 < 0x7F:
                yield chr(b0), 1, i
                i += 1
                continue
            # 其他控制/二进制字节
            yield None, 0, i
            i += 1

    def extract(self, data, file_path, category=CAT_DIALOG):
        """扫描 data，返回 TextFile。"""
        tf = TextFile(path=file_path)
        run = []          # 字符
        run_off = None
        run_len = 0
        valid = 0
        kana = 0
        semantic = 0      # 假名+汉字数（语义字符）
        rare = 0          # 非常用汉字数（压缩流噪声特征）
        ascii_alpha = 0   # 半角英文字母数（二进制噪声特征）

        def flush():
            nonlocal run, run_off, run_len, valid, kana, semantic, rare, ascii_alpha
            if run_off is None:
                return
            text = "".join(run).strip()
            n = len(text)
            # 噪声过滤：非常用汉字（JIS一级/GB2312一级之外）占比须极低；
            # 短文本不允许生僻字，长文本最多容忍 1 个（人名等）。
            # 注意：真实日文文本也可能含 JIS 二级汉字，故仅压缩流扫描开启。
            rare_ok = (not self.rare_filter) or rare == 0 or (n >= 20 and rare <= 1)
            # 半角英文字母占比过高说明是二进制数据
            ascii_ok = ascii_alpha <= max(1, n * 0.25)
            if (n >= self.min_run and kana >= self.min_kana
                    and semantic >= self.min_semantic and rare_ok and ascii_ok):
                text = re.sub(r"\n{2,}", "\n", text).strip()
                if len(text) >= self.min_run:
                    key = text if self.drop_dups else None
                    if key is None or key not in self._seen:
                        self._seen.add(key)
                        tf.add(TextEntry(offset=run_off, length=run_len,
                                         category=category, original=text))
            run, run_off, run_len, valid, kana, semantic, rare, ascii_alpha = (
                [], None, 0, 0, 0, 0, 0, 0)

        for ch, blen, off in self._iter_chars(data):
            if ch is None:
                flush()
                continue
            if ch == "\n":
                if run_off is not None:
                    run.append(ch)
                    run_len += blen
                continue
            is_valid = (ch in ASCII_OK or ch not in PUNCT)
            if run_off is None:
                run_off = off
            run.append(ch)
            run_len += blen
            if is_valid:
                valid += 1
            if ch in KANA:
                kana += 1
                semantic += 1
            elif ord(ch) >= 0x4E00 and ord(ch) <= 0x9FFF:
                semantic += 1
                if ch not in COMMON_KANJI:
                    rare += 1
            elif "a" <= ch <= "z" or "A" <= ch <= "Z":
                ascii_alpha += 1
        flush()
        return tf
