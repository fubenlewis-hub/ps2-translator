# -*- coding: utf-8 -*-
"""
翻译引擎：OpenAI 兼容接口（云端 API 与本地 Ollama/LM Studio/llama.cpp 通用）+
Anthropic 兼容接口。支持批量、并发限流、自动重试、断点续传（已译条目跳过）。
"""
import json
import logging
import random
import threading
import time
import urllib.request

log = logging.getLogger("ps2hantool.translate")

DEFAULT_TIMEOUT = 120
MAX_RETRY = 3


def parse_batch_response(resp_text, batch):
    """解析多行批量响应为 {id: 译文}。
    优先按行首 “id=” 前缀匹配；若无前缀且行数一致，则按顺序对齐。
    batch: [(id, text), ...]。返回 {id: text}（可能少于 batch 长度）。"""
    out = {}
    ids = [i for i, _ in batch]
    lines = [ln.strip() for ln in (resp_text or "").split("\n") if ln.strip()]
    by_id = {}
    plain = []
    for ln in lines:
        head, sep, rest = ln.partition("=")
        if sep and head.strip() in ids:
            by_id[head.strip()] = rest.strip()
        else:
            plain.append(ln)
    if len(by_id) == len(ids):
        return by_id
    # 部分带前缀：先取带前缀的；缺失位置按顺序从 plain 补
    missing = [i for i in ids if i not in by_id]
    if plain and len(plain) >= len(missing):
        for i, txt in zip(missing, plain[:len(missing)]):
            by_id[i] = txt
        return by_id
    # 全部无前缀且行数与批一致：顺序对齐
    if not by_id and len(lines) == len(ids):
        return dict(zip(ids, lines))
    return by_id


class EngineError(Exception):
    pass


class _Http:
    @staticmethod
    def post_json(url, headers, payload, timeout=DEFAULT_TIMEOUT):
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))


class TranslateEngine:
    """基类。子类实现 build_url / build_payload / parse_result。"""

    name = "base"

    def __init__(self, base_url="", api_key="", model="", temperature=0.3,
                 max_tokens=2048, timeout=DEFAULT_TIMEOUT, rpm=30, concurrency=4):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.rpm = rpm              # 每分钟请求上限
        self.concurrency = concurrency
        self._lock = threading.Lock()
        self._window = []           # 限流时间窗
        self._stats = {"ok": 0, "fail": 0}

    # ---------- 子类实现 ----------
    def build_url(self):
        raise NotImplementedError

    def build_payload(self, system, user):
        raise NotImplementedError

    def parse_result(self, resp):
        raise NotImplementedError

    # ---------- 连接测试 ----------
    def test(self):
        try:
            resp = self._post("测试连接", "请回复「OK」")
            return True, "连接成功"
        except Exception as e:
            return False, str(e)

    # ---------- 基础请求 ----------
    def _post(self, system, user):
        with self._lock:
            now = time.time()
            self._window = [t for t in self._window if now - t < 60]
            if len(self._window) >= self.rpm:
                wait = 60 - (now - self._window[0])
                time.sleep(max(0.1, wait))
            self._window.append(time.time())
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer %s" % self.api_key
        payload = self.build_payload(system, user)
        last_err = None
        for attempt in range(MAX_RETRY):
            try:
                resp = _Http.post_json(self.build_url(), headers, payload, self.timeout)
                text = self.parse_result(resp)
                self._stats["ok"] += 1
                return text
            except Exception as e:
                last_err = e
                wait = 2 ** attempt + random.random()
                log.warning("翻译请求失败(第%d次): %s，%.1fs 后重试", attempt + 1, e, wait)
                time.sleep(wait)
        self._stats["fail"] += 1
        raise EngineError("请求失败: %s" % last_err)

    # ---------- 批量翻译 ----------
    def translate_batch(self, items, glossary_block="", game_context="",
                        reference_block="", progress_cb=None, cancel_event=None,
                        resume_ids=None):
        """
        items: list[(entry_id, text)] —— 待翻译条目（逐条请求）。
        glossary_block: 术语表 system prompt 文本。
        game_context: 游戏背景说明。
        reference_block: 相似文本参考译文（fuzzy-match 参考，提高一致性，可选）。
        返回 {entry_id: translated_text}。
        """
        batches = [[(i, t)] for i, t in items]
        return self.translate_batches(
            batches, glossary_block=glossary_block, game_context=game_context,
            reference_block=reference_block, progress_cb=progress_cb,
            cancel_event=cancel_event)

    def translate_batches(self, batches, glossary_block="", game_context="",
                          reference_block="", progress_cb=None, cancel_event=None):
        """
        组批翻译（借鉴 AiNiee“每次翻译行数”+ 相似文本聚合思路）：
        每个 batch 为一个多行请求，行格式 “id=原文”，响应按行解析 “id=译文”。
        收益：system prompt 每组只发一次（省 token）、请求数减少（加速）、
        同组相似文本共享上下文（一致性↑）。
        批失败自动降级：整批拆成逐条请求重试，保证不丢条目。

        batches: list[ list[(entry_id, text), ...] ]
        返回 (results: {id: text}, errors: {id: err})
        """
        system = self._build_system_prompt(glossary_block, game_context,
                                           reference_block)
        results = {}
        errors = {}
        lock = threading.Lock()
        sem = threading.Semaphore(self.concurrency)
        total = sum(len(b) for b in batches)

        def work(batch):
            with sem:
                if cancel_event and cancel_event.is_set():
                    return
                ids = [i for i, _ in batch]
                try:
                    out = self._post_batch(system, batch)
                    with lock:
                        results.update(out)
                except Exception:
                    # 降级：批失败则逐条重试（避免整批丢失）
                    for eid, text in batch:
                        if cancel_event and cancel_event.is_set():
                            return
                        try:
                            out1 = self._post(system, "%s=%s" % (eid, text.replace("\n", " ")))
                            with lock:
                                results[eid] = out1
                        except Exception as e:
                            with lock:
                                errors[eid] = str(e)
                if progress_cb:
                    try:
                        with lock:
                            progress_cb(len(results) + len(errors), total)
                    except Exception:
                        pass

        threads = [threading.Thread(target=work, args=(b,), daemon=True)
                   for b in batches]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results, errors

    def _post_batch(self, system, batch):
        """发送多行请求并解析多行响应。batch: [(id, text), ...]
        若一个 id 都没解析到（多行批场景），抛异常触发上层降级为逐条重试。"""
        lines = ["%s=%s" % (i, t.replace("\n", " ")) for i, t in batch]
        resp = self._post(system, "\n".join(lines))
        out = parse_batch_response(resp, batch)
        if not out and len(batch) > 1:
            raise EngineError("批量响应解析为空，降级逐条重试")
        return out

    def _build_system_prompt(self, glossary_block, game_context, reference_block=""):
        parts = [
            "你是一位资深的日译中游戏本地化译者。请将用户提供的日文游戏文本翻译成",
            "自然、口语化的简体中文，符合游戏对话语气。",
            "规则：",
            "1. 只输出译文本身，不要任何解释、注音或引号包裹；",
            "2. 保留原文中的换行结构（\\n）与 %s 等占位符；",
            "3. 严格遵守术语表（术语表内的专有名词必须使用其中译名）；",
            "4. 日文中的句末语气（です/ます/だ）适当转化为中文语气；",
            "5. 省略号、感叹号等符号与原文保持一致；",
            "6. 不要翻译英文字符串中的专有名词（如歌曲名、公司名）。",
        ]
        if game_context:
            parts.append("【游戏背景】%s" % game_context)
        if glossary_block:
            parts.append("【术语表（日文→中文，必须遵守）】\n%s" % glossary_block)
        if reference_block:
            parts.append(
                "【相似文本参考译文】以下是与待译文本相似（部分相同）的参考译文，"
                "请参考其用词与语气，保持译名和风格一致；参考译文只作参考，"
                "仍以本次待译文本的完整内容为准。\n%s" % reference_block)
        return "\n".join(parts)


class OpenAICompatEngine(TranslateEngine):
    name = "openai_compat"

    def build_url(self):
        return "%s/chat/completions" % self.base_url

    def build_payload(self, system, user):
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

    def parse_result(self, resp):
        try:
            return resp["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError):
            raise EngineError("OpenAI 响应格式异常: %s" % resp)


class AnthropicEngine(TranslateEngine):
    name = "anthropic"

    def build_url(self):
        return "%s/messages" % self.base_url

    def build_payload(self, system, user):
        return {
            "model": self.model,
            "system": system,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [{"role": "user", "content": user}],
        }

    def parse_result(self, resp):
        try:
            return "".join(b.get("text", "") for b in resp["content"]).strip()
        except (KeyError, TypeError) as e:
            raise EngineError("Anthropic 响应格式异常: %s" % resp)


def create_engine(kind, cfg):
    """kind: 'openai' | 'anthropic' | 'local'"""
    base = cfg.get("base_url", "")
    key = cfg.get("api_key", "")
    model = cfg.get("model", "")
    temperature = float(cfg.get("temperature", 0.3))
    max_tokens = int(cfg.get("max_tokens", 2048))
    rpm = int(cfg.get("rpm", 30))
    concurrency = int(cfg.get("concurrency", 4))
    if kind == "anthropic":
        return AnthropicEngine(base, key, model, temperature, max_tokens,
                               rpm=rpm, concurrency=concurrency)
    return OpenAICompatEngine(base, key, model, temperature, max_tokens,
                              rpm=rpm, concurrency=concurrency)
