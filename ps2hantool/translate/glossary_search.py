# -*- coding: utf-8 -*-
"""
术语网络搜索与 AI 抽取。

网络搜索（多源、可降级）：
- 维基百科(zh)：直接搜日文名，命中率高（已实测返回《心跳回忆3 ～在约会的地方～》官方译名）
- 维基百科(ja)→跨语言链接：查日文条目再取其 zh 语言链接标题（官方中文名）
- 萌娘百科：二次元专有名词常用（ACG 术语）
- Bing：兜底
联网失败静默返回空，由用户手动补充。

AI 抽取（借鉴开源项目 KeywordGacha 的思路：把游戏文本交给 LLM 抽取专有名词）：
- ai_extract(engine, texts)：批量发送文本，要求 LLM 返回 JSON 术语列表（含中文译名建议），
  结果进入“术语候选采纳”弹窗由用户确认后写入术语表。
"""
import html
import json
import logging
import re
import urllib.parse
import urllib.request

log = logging.getLogger("ps2hantool.glossary_search")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PS2-Hanhua-Tool/0.2"}
TIMEOUT = 6

# 常用日文名->中文名启发（可人工维护扩充；也可由预设术语表覆盖）
HINTS = {
    "ときめきメモリアル": "心跳回忆",
    "ときめきメモリアル3": "心跳回忆3",
    "牧原優紀子": "牧原优纪子",
    "白鷺ゆめの": "白鹭梦野",
    "針縫由布": "针缝由布",
    "河合理佳": "河合理佳",
    "御田万里": "御田万里",
    "和泉穂多琉": "和泉穗多琉",
    "相川ちひろ": "相川千寻",
    "橘恵美": "橘惠美",
    "神条芹華": "神条芹华",
    "飯田美穂": "饭田美穗",
    "野咲すみれ": "野咲堇",
    "もえぎの高校": "萌木高校",
    "二宮": "二宫",
}


def _fetch(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _wiki_api(base, params):
    qs = urllib.parse.urlencode(params)
    return json.loads(_fetch("%s/w/api.php?%s" % (base, qs)))


def search_wikipedia_zh(term):
    """zh 维基搜索日文名。返回 [(标题, 摘要)]。"""
    try:
        data = _wiki_api("https://zh.wikipedia.org", {
            "action": "query", "list": "search", "format": "json",
            "srlimit": 3, "srsearch": term})
        return [(it.get("title", ""), it.get("snippet", ""))
                for it in data.get("query", {}).get("search", [])]
    except Exception as e:
        log.debug("维基百科(zh)搜索失败: %s", e)
        return []


def wikipedia_ja_langlink(term):
    """查 ja 维基条目，取其语言链接中的中文标题（官方中文名）。
    返回 [(zh标题, '跨语言链接')]。"""
    try:
        data = _wiki_api("https://ja.wikipedia.org", {
            "action": "query", "titles": term, "prop": "langlinks",
            "lllang": "zh", "format": "json"})
        pages = data.get("query", {}).get("pages", {})
        out = []
        for pid, page in pages.items():
            for ll in page.get("langlinks", []) or []:
                out.append((ll.get("*", ""), "维基(ja→zh)"))
        return out
    except Exception as e:
        log.debug("维基百科(ja)跨语言链接失败: %s", e)
        return []


def search_moegirl(term):
    """萌娘百科搜索，返回 [(标题, 摘要)]。"""
    try:
        data = _wiki_api("https://zh.moegirl.org.cn", {
            "action": "query", "list": "search", "format": "json",
            "srlimit": 3, "srsearch": term})
        out = []
        for it in data.get("query", {}).get("search", []):
            snip = re.sub(r"<[^>]+>", "", it.get("snippet", ""))
            out.append((it.get("title", ""), snip))
        return out
    except Exception as e:
        log.debug("萌娘百科搜索失败: %s", e)
        return []


def search_bing(term):
    """Bing 兜底，返回 [(标题, "")]。"""
    try:
        page = _fetch("https://www.bing.com/search?q=%s" % urllib.parse.quote(term))
        titles = re.findall(r"<h2><a[^>]*>(.*?)</a></h2>", page, re.S)[:5]
        titles = [html.unescape(re.sub(r"<[^>]+>", "", t)).strip() for t in titles]
        return [(t, "") for t in titles if t]
    except Exception as e:
        log.debug("Bing 搜索失败: %s", e)
        return []


def lookup(term):
    """综合检索一个术语，返回候选 [(候选名, 来源, 佐证)]。"""
    results = []
    # 顺序：官方跨语言名 > zh 维基 > 萌娘百科 > Bing
    for fn, src in ((wikipedia_ja_langlink, "维基(ja→zh)"),
                    (search_wikipedia_zh, "维基百科"),
                    (search_moegirl, "萌娘百科"),
                    (search_bing, "Bing")):
        try:
            for title, snippet in fn(term):
                results.append((title, src, snippet))
        except Exception as e:
            log.debug("%s 检索异常: %s", src, e)
    # 去重（保留首个）
    seen, uniq = set(), []
    for item in results:
        if item[0] and item[0] not in seen:
            seen.add(item[0])
            uniq.append(item)
    return uniq


def auto_glossary_from_seed(glossary, detected_game=None):
    """用内置 HINTS 预填术语表（仅当条目不存在时）。"""
    n = 0
    for jp, zh in HINTS.items():
        if glossary.add(jp, zh, source="内置预设"):
            n += 1
    return n


def suggest_terms(glossary, unknown_terms, concurrency=4):
    """批量检索未知术语并给出建议（并发执行，大幅缩短等待）。
    返回 {term: [(candidate, source, snippet)]}；未检索到的 term 也保留（空列表），
    便于 UI 提示用户手动补充。"""
    from concurrent.futures import ThreadPoolExecutor
    out = {}
    if not unknown_terms:
        return out

    def work(t):
        try:
            return t, lookup(t)[:3]
        except Exception:
            return t, []

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(work, t) for t in unknown_terms]
        for fut in futures:
            t, hits = fut.result()
            out[t] = hits
    return out


def high_freq_terms(texts, existing=None, top=30, min_count=4):
    """从文本中统计高频专有名词候选（借鉴 KeywordGacha 的“出现次数阈值”思路）。
    返回 [(词, 出现次数)]，按频次降序。
    过滤规则（专有名词特征）：
    - 必须含汉字、以汉字结尾（地名/人名/校名等几乎都以汉字收尾，可排除动词短语/助词碎片）
    - 排除纯假名片段、已收录术语、低频项
    """
    import collections
    counter = collections.Counter()
    for t in texts:
        if not t:
            continue
        for n in (4, 3, 2):
            for i in range(len(t) - n + 1):
                seg = t[i:i + n]
                if not re.search(r"[一-龥]", seg):          # 必须含汉字
                    continue
                if not re.fullmatch(r"[一-龥ぁ-んァ-ヶー]{2,5}", seg):
                    continue
                counter[seg] += 1
    existing = set(existing or [])
    out = []
    for seg, c in counter.most_common():
        if seg in existing:
            continue
        if c < min_count:
            continue
        # 专有名词几乎都以汉字结尾；假名结尾多为动词/助词短语（“行った”“思っ”）
        if not re.search(r"[一-龥]$", seg):
            continue
        # 排除明显的常用虚词组合
        if seg in ("から", "ため", "よう", "ところ", "みたい", "こん", "あっ", "きれい"):
            continue
        out.append((seg, c))
        if len(out) >= top:
            break
    return out


# ---------------- AI 术语抽取（借鉴 KeywordGacha） ----------------

EXTRACT_PROMPT = (
    "你是资深游戏本地化术语专家。请从下面的日文游戏文本中抽取【专有名词】"
    "（角色人名、昵称、地名、学校名、组织名、物品名、技能名、专有缩写等），"
    "并为每个词给出中文译名建议（约定俗成优先，其次意译）。\n"
    "要求：\n"
    "1. 只输出 JSON 数组，不要任何其他文字，格式：\n"
    '[{"src": "日文原名", "dst": "中文译名", "type": "人名/地名/组织/物品/其他", "note": "说明"}] \n'
    "2. 只收录真正的专有名词，不要收录普通动词/形容词；\n"
    "3. 每个词尽量完整（如“もえぎの高校”整体收录，不要拆成“もえぎ”）；\n"
    "4. 已经给出中文的译文片段不算专有名词。\n\n"
    "游戏文本（每行一条，可能不完整）：\n{texts}"
)


def ai_extract(engine, texts, batch=40, max_batches=4, progress_cb=None, cancel_event=None):
    """
    用已配置的翻译引擎抽取专有名词并给出中文建议（借鉴 KeywordGacha 思路）。
    engine: TranslateEngine 实例（已配置）。
    texts: list[str] 游戏文本（抽样即可）。
    返回 {term: (zh, type, note)}；失败/未配置返回空 dict。
    """
    if engine is None or not getattr(engine, "base_url", ""):
        return {}
    results = {}
    used = 0
    for start in range(0, min(len(texts), batch * max_batches), batch):
        if cancel_event and cancel_event.is_set():
            break
        chunk = texts[start:start + batch]
        joined = "\n".join(t.replace("\n", " ") for t in chunk)
        try:
            resp = engine._post(EXTRACT_PROMPT, joined)
        except Exception as e:
            log.warning("AI 术语抽取批次失败: %s", e)
            continue
        terms = _parse_ai_response(resp)
        for t in terms:
            src = (t.get("src") or "").strip()
            dst = (t.get("dst") or "").strip()
            if src and dst:
                results[src] = (dst, t.get("type", "其他"), t.get("note", ""))
        used += 1
        if progress_cb:
            progress_cb(used, max_batches)
    return results


def _parse_ai_response(text):
    """从 LLM 输出中解析 JSON 数组（容忍 markdown 代码块/前后缀）。"""
    if not text:
        return []
    text = text.strip()
    # 去掉 ```json ... ``` 包裹
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if m:
        text = m.group(1)
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    except Exception:
        pass
    return []
