# PS2 游戏一键汉化工具

> ⚠️ **仅供个人学习研究使用**。请确保您拥有正版游戏光盘/镜像，本项目不内置任何受版权保护的资源。

一个通用型 PS2 游戏汉化桌面工具：载入正版 ISO → 自动分析并提取游戏文本 → 生成/编辑术语表 →
配置翻译引擎（云端 API 或本地 AI）→ 一键翻译、术语统一、回写打包 → 输出汉化 ISO（不覆盖原盘）。

## 功能一览

| 模块 | 说明 |
|---|---|
| ISO 处理 | ISO9660 提取与重打包（保序策略），原始 ISO 只读，输出新文件 |
| 文本提取 | 插件化架构：内置专用游戏插件 + 通用 Shift-JIS 扫描，新游戏可编写插件扩展（接口见 `docs/插件开发.md`） |
| **状态机** | 全程实时状态显示：首页状态横幅 + 进度条 + 底部状态栏，随时了解当前工作阶段 |
| 信息展示 | 提取后展示文本总条数/字符数/分类统计、游戏识别、术语表预览 |
| 术语表 | 查看/搜索/增删改、CSV/JSON 导入导出、内置预设、**联网搜索（并发检索+勾选采纳+无结果可直接填写）**、**AI 抽取术语**（借鉴 KeywordGacha，MIT） |
| 翻译引擎 | OpenAI 兼容（云端/本地 Ollama、LM Studio、llama.cpp）+ Anthropic 格式；批量并发、限流重试、断点续传；**独立「开始翻译」按钮**；**实时进度条："已翻译 X/Y 条 (Z%)"**；**成本优化三层：精确去重复用 → 相似组批翻译（省 token/加速/一致性）→ 相似参考注入** |
| 术语统一 | 翻译后自动替换术语、二次一致性检查报告 |
| 中文字库 | 生成 12/16px 点阵字库（GB2312 常用字），注入框架 + 降级方案说明 |
| GUI | PySide6 六页面流程：首页/提取结果/术语管理/翻译设置/文本校对/日志报告，后台线程可取消 |
| 容错 | 回写前自动备份、一键恢复、超长文本记录、崩溃日志（crash.log） |

## 快速开始

### 方式一：使用打包好的 exe（推荐给普通用户）
- **GitHub Releases 下载**：https://github.com/fubenlewis-hub/ps2-translator/releases
  （`PS2HanhuaTool-v1.0.0.exe`，单文件，无需安装 Python 与依赖）
- 工程数据默认保存在 exe 同目录下的 `projects/` 文件夹；
- 重新打包方法见下文「打包为 exe」。

### 方式二：源码运行

```bash
# 1. 安装依赖（建议使用虚拟环境）
pip install -r requirements.txt

# 2. 启动图形界面
python main.py
python main.py --selftest   # 无头自检，结果写入 selftest.txt

# 或使用命令行（无 GUI）
python cli.py load <游戏.iso> <工程目录>
python cli.py extract <工程目录>
python cli.py stats <工程目录>
python cli.py translate <工程目录> --cfg 翻译配置.json --limit 50
python cli.py writeback <工程目录>
python cli.py rebuild <工程目录>
```

## 打包为单个 exe

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean "PS2汉化工具.spec"
# 产物：dist/PS2汉化工具.exe（单文件，含 Qt 运行库，约 100~200MB）
```

- 打包已内置 opencc（简繁转换字典）、pycdlib、Pillow、翻译引擎与全部游戏插件；
- 用 `PS2汉化工具.exe --selftest` 可做无头自检（通过/失败写入 exe 同目录 `selftest.txt`）；
- 若杀软误报，请在设置中添加信任（PyInstaller 单文件为常见误报场景）。

翻译配置示例 `cfg.json`：

```json
{
  "kind": "openai",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-xxx",
  "model": "gpt-4o-mini",
  "temperature": 0.3,
  "max_tokens": 2048,
  "rpm": 30,
  "concurrency": 4
}
```

本地引擎把 `kind` 设为 `local`，`base_url` 指向本地服务（Ollama：`http://localhost:11434/v1`，LM Studio：`http://localhost:1234/v1`），`api_key` 留空。

## 使用流程（GUI）

1. **首页/流程**：选择 ISO → 「载入并检测游戏」→ 自动整盘提取并识别游戏（自动命中匹配的专用插件）。
2. **提取结果**：查看文本量统计与术语表预览 → 「编辑术语表」。
3. **术语管理**：核对/添加/删除术语（内置了常用游戏预设）；可「联网搜索更新」获取候选；「导入/导出」便于多人协作。
4. **翻译设置**：选择引擎类型、填 Base URL / Key / 模型 → 「测试连接」→ 「保存设置」。
5. **文本校对（可选）**：查看原文/译文对照，可直接改译文，支持导出/导入。
6. **日志/报告**：实时日志、「生成术语一致性报告」。
7. 首页点击「一键全流程」或分步执行「汉化与打包」，完成后在 `工程目录/output/` 拿到汉化 ISO，用 PCSX2 加载测试。

## 工程目录结构

```
工程目录/
├── iso/        原始 ISO 引用
├── work/       提取出的文件树（汉化修改发生在这一层）
├── backup/     回写前的自动备份（可恢复）
├── output/     汉化 ISO 输出
├── data/       工程状态：settings.json / glossary.json / extracted.json / translated.json / font_*px.bin
└── logs/       运行日志
```

## 已实测支持的 PS2 游戏

- **《心跳回忆3》（SLPM-65080）**：完整支持文本提取——DATA5.BIN（未压缩对话，约 4 万+ 条）、
  ELF 系统文本、DATA3.BIN 内 ATP 条目（含剧情对话；ATP 压缩解压为实验功能，引用 TM3_Tools 实现）。
  字库位于 DATA2/DATA4.BIN（PS2 GS 纹理容器），注入需进一步逆向，当前提供点阵字库生成与降级方案。
- **《心跳回忆2》音乐视频剪辑版（SLPM-65118）**：支持 DATA.DAT 容器解包与通用文本扫描；
  本盘为视频盘，可译文本极少（字幕烧录在视频流中）。若放入《心跳回忆2》游戏本体 ISO，
  可复用通用插件或按新格式编写插件（接口见 `docs/插件开发.md`）。

上述为已实测验证的游戏；其他 PS2 游戏可通过通用 Shift-JIS 扫描或编写新插件支持。
详细逆向结论见 `docs/调研报告.md`。

## 开源许可与致谢

- 参考了 [ResonanceTranslation](https://github.com/AGTTeam/ResonanceTranslation)（MIT）、
  [Chobits-Translation-Project](https://github.com/sam8457/Chobits-Translation-Project)（MIT）等项目的工作流；
- ATP 解压移植自 [ShrNme/TM3_Tools](https://github.com/ShrNme/TM3_Tools)（WIP，已注明来源）；
- TM3 目录表解析依据 BloodRaynare 发布的 QuickBMS 脚本（ResHax 论坛）。
- 本项目代码仅作学习研究；请勿将汉化结果用于商业用途。
