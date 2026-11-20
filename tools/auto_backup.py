#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AMMDS 备份包模板仓库 —— 自动化驱动脚本（Python 3.8+，无第三方依赖）

它把「用户填好的 TODO.md」翻译成「一个校验通过的备份包」，中间不让用户碰任何格式细节。

子命令
    init     初始化 work/ 工作区与模板文件（幂等，不覆盖已有文件）
    todo     预检 TODO.md 是否填完整，并校验 work/_meta.json 的合法性
    build    由 work/records/<type>.json [+ work/images/] 产出 output/*.zip 并自检
    verify   对一个已有 zip 跑《AI备份包生成规范》第 9 节自检
    report   重新生成 output/deliver.md 交付说明

典型用法
    python tools/auto_backup.py init
    python tools/auto_backup.py todo
    python tools/auto_backup.py build
    python tools/auto_backup.py verify output/ammds-backup-movie-20260101120000.zip

约束（与 Rule/AI备份包生成规范.md 一致）
    * 只支持 movie / actor / comic / novel 四类
    * records 必须是数组，条目字段名必须与规范第 5 节一致
    * 图片走打包策略时，字段值 / imageFiles[].ref / 包内 path 三者必须对齐（本脚本用 ref 作 key，天然对齐）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime

# --------------------------------------------------------------------------- #
# 常量与路径
# --------------------------------------------------------------------------- #

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULE_DIR = os.path.join(ROOT, "Rule")
WORK_DIR = os.path.join(ROOT, "work")
OUTPUT_DIR = os.path.join(ROOT, "output")
TODO_PATH = os.path.join(ROOT, "TODO.md")
META_PATH = os.path.join(WORK_DIR, "_meta.json")
IMAGES_DIR = os.path.join(WORK_DIR, "images")
SCRIPTS_DIR = os.path.join(WORK_DIR, "scripts")
SOURCE_DIR = os.path.join(WORK_DIR, "source")
RECORDS_DIR = os.path.join(WORK_DIR, "records")

ALLOWED_TYPES = ("movie", "actor", "comic", "novel")
ALLOWED_SOURCE_MODES = ("scrape", "existing")
ALLOWED_IMAGE_STRATEGIES = ("pack", "link", "none")
ALLOWED_CONFLICT_POLICIES = ("skip", "overwrite", "merge")
TYPE_CN = {"movie": "影视", "actor": "演员", "comic": "漫画 / 相册", "novel": "小说"}

if RULE_DIR not in sys.path:
    sys.path.insert(0, RULE_DIR)

import ammds_backup_pack as pack  # noqa: E402  (Rule/ammds_backup_pack.py)


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #

def _stdout_utf8() -> None:
    """Windows 控制台默认 GBK，中文输出会炸；尽量切成 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


def read_text(path: str) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gbk"):
        try:
            with open(path, "r", encoding=encoding) as fp:
                return fp.read()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as fp:
        return fp.read()


def read_json(path: str):
    raw = read_text(path)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("%s 不是合法 JSON：%s" % (os.path.relpath(path, ROOT), exc)) from exc


def rel(path: str) -> str:
    try:
        return os.path.relpath(path, ROOT).replace("\\", "/")
    except ValueError:
        return path


def write_text(path: str, content: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(content)


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return "%.1f %s" % (value, unit) if unit != "B" else "%d B" % num_bytes
        value /= 1024
    return "%.1f GB" % value


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# todo：解析并校验用户填写的 TODO.md
# --------------------------------------------------------------------------- #

QUESTION_SPECS = (
    ("source_site", "Q1 站点名称或域名"),
    ("source_urls", "Q1 入口链接"),
    ("scope", "Q1 抓取范围"),
    ("target_list", "Q1 指定清单"),
    ("package_type", "Q2 备份包类型"),
    ("image_strategy", "Q3 图片处理方式"),
    ("data_ready", "Q4 已备好数据"),
    ("existing_paths", "Q4 数据路径"),
)

# 模板里的 <...> 占位符（判定「未填写」）
PLACEHOLDER_RE = re.compile(r"<[^<>\n]{0,200}>")
# 取反引号包裹的首个 token
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
URL_RE = re.compile(r"https?://[^\s`\"'<>\)\]]+")


def _question_blocks(text: str):
    """把 TODO.md 按 `## Qn ...` 切成块，返回 [(标题, 正文)]。"""
    blocks = []
    current_title, buffer = None, []
    for line in text.splitlines():
        if re.match(r"^\s*##\s*Q\d", line):
            if current_title is not None:
                blocks.append((current_title, "\n".join(buffer)))
            current_title, buffer = line.strip("# ").strip(), []
        elif current_title is not None:
            buffer.append(line)
    if current_title is not None:
        blocks.append((current_title, "\n".join(buffer)))
    return blocks


def _strip_placeholders(chunk: str) -> str:
    return PLACEHOLDER_RE.sub("", chunk)


# 模板里「说明文字：`示例值`」形式的首个示例值（用于识别用户是否替换了模板）
INLINE_EXAMPLE_RE = re.compile(r"[：:]\s*`([^`\n]*)`")


def _marker_value(block: str, marker: str) -> str:
    """
    取「marker：`值`」里的值。模板原文是「marker：`例：xxx`」，
    此时返回空串（= 用户没填），避免把模板示例当成用户的答案。
    """
    for line in block.splitlines():
        pos = line.find(marker)
        if pos < 0:
            continue
        match = INLINE_EXAMPLE_RE.search(line[pos:])
        if not match:
            continue
        value = match.group(1).strip()
        return "" if _looks_like_template(value) else value
    return ""


def _fence_span(text: str, start: int = 0):
    """返回 text[start:] 中第一个 ``` 围栏的内容区间 (内容起点, 内容终点)，找不到返回 None。"""
    open_match = re.compile(r"```[^\n]*\n").search(text, start)
    if not open_match:
        return None
    begin = open_match.end()
    close = text.find("```", begin)
    return (begin, close if close >= 0 else len(text))


def _body_of(block: str, start_marker: str = None) -> str:
    """
    截取块正文（模板里正文要么写在 ``` 围栏内，要么写成行内 `示例`）。三种版式都要支持：

        「xxx：`示例`」                  行内代码 -> 正文 = 该行代码内的内容
        「xxx（说明）：」+ 下一段围栏       -> 正文 = 下一个围栏内的内容
        「`<可选>` 指定清单（…）」+ 围栏    -> 同上（标题里含行内代码，不能误判成围栏）

    可选从 start_marker 之后开始；遇到 ## 标题 / --- 分隔线 / 围栏结束即停止。
    """
    if not start_marker:
        return block
    # 跳过把 marker 当说明文字引用的模板行（如「- 站点名称或域名：`例：…`」）
    idx = -1
    for match in re.finditer(re.escape(start_marker), block):
        pos = match.start()
        line_end = block.find("\n", pos)
        line_end = len(block) if line_end < 0 else line_end
        if not _looks_like_template(_strip_placeholders(block[pos:line_end])):
            idx = pos
            break
    if idx < 0:
        return ""

    line_end = block.find("\n", idx)
    line_end = len(block) if line_end < 0 else line_end
    line = block[idx:line_end]

    def _between(text: str, ch: str) -> "str|None":
        first = text.find(ch)
        if first < 0:
            return None
        second = text.find(ch, first + len(ch))
        return text[first + len(ch):second if second >= 0 else len(text)]

    fence = line.find("```")
    if fence >= 0:
        text = _between(line, "```")          # 围栏与标题同行（含同行闭合）
    else:
        inline = line.find("`")
        if inline >= 0:
            text = _between(line[inline:], "`") or ""   # 行内代码：正文就在该行里
        else:
            span = _fence_span(block, line_end)         # 正文在标题之后的下一个围栏内
            text = block[span[0]:span[1]] if span else block[line_end + 1:]
    if text is None:
        return ""
    if text.strip() == line.strip():
        return ""     # 没有找到正文，返回的是标题行本身 -> 视为未填写

    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if re.match(r"^##\s", stripped) or stripped == "---" or stripped.count("```") == 3:
            break
        lines.append(raw)
    return "\n".join(lines)


def _after_marker_lines(block: str, marker: str, allow_labels: bool = True) -> list:
    """
    marker 所在行之后第一个正文块的行。

    用于「`<可选>` / 若选 yes」这类**正文不在 marker 同行**的段落：
    优先取 ``` 围栏，其次取以 ` 开头的独立行内代码行。
    """
    idx = -1
    for match in re.finditer(re.escape(marker), block):
        pos = match.start()
        line_end = block.find("\n", pos)
        line_end = len(block) if line_end < 0 else line_end
        if not _looks_like_template(_strip_placeholders(block[pos:line_end])):
            idx = pos
            break
    if idx < 0:
        return []
    line_end = block.find("\n", idx)
    line_end = len(block) if line_end < 0 else line_end
    rest = block[line_end + 1:]
    span = _fence_span(rest, 0)
    if span:
        return _clean_lines(rest[span[0]:span[1]], allow_labels=allow_labels)
    out = []
    for line in _clean_lines(rest, allow_labels=allow_labels):
        if line.endswith("？") or line.endswith("?"):
            continue
        out.append(line)
    return out


def _fenced_block(chunk: str) -> "str|None":
    """取块内第一个 ``` 围栏代码块的内容；没有围栏则返回 None。"""
    span = _fence_span(chunk, 0)
    return chunk[span[0]:span[1]] if span else None


def _clean_lines(chunk: str, allow_labels: bool = False):
    """
    取块内的有效行：去占位符行、围栏、反引号、列表符号与模板说明行。

    :param allow_labels: True 时保留「xxx：」形式的行（列表类正文里合法），
                         字段取值场景必须为 False（否则会把说明行当成值）。
    """
    result = []
    for raw in _strip_placeholders(chunk).splitlines():
        line = raw.strip()
        if not line or line.startswith("```") or line.startswith("|"):
            continue
        if line.startswith("---") or line.startswith(">") or line.startswith("#"):
            continue
        line = BACKTICK_RE.sub(r"\1", line)                # `x` -> x
        line = re.sub(r"^[\-\*\+]\s*", "", line)           # 去列表符号
        line = line.strip().strip("`").strip()
        if not line or line in ("--", "-", "input"):
            continue
        if not allow_labels and (line.endswith("：") or line.endswith(":")):
            continue
        result.append(line)
    return result


def _fenced_lines(chunk: str) -> list:
    """取块内第一个围栏代码块的内容行；没有围栏则退化为整块的有效行。"""
    block = _fenced_block(chunk)
    return _clean_lines(block if block is not None else chunk)


def _first_value(chunk: str, keys) -> str:
    for line in _clean_lines(chunk):
        for key in keys:
            if line.startswith(key):
                value = line[len(key):].lstrip("：: =").strip()
                if value:
                    return value
    lines = _clean_lines(chunk)
    return lines[0] if lines else ""


# 模板里用作示例的行；未被替换时应视为「未填写」，不能当成用户的答案
# 模板里用作「示例答案」的行前缀；这些行未被替换时应视为未填写。
# 注意：不要收录「一行一个」「三选一」这类**指令**用词——它们出现在模板标题里，
# 是给用户看的说明，不是示例答案。
TEMPLATE_ECHO_KEYS = ("本仓库示例", "例：", "输入提示")


def _looks_like_template(line: str) -> bool:
    """
    判断一行是不是模板自带的示范文字（而不是用户填的内容）。

    只看「例：」「本仓库示例」这类前缀。**不能**因为行里含有 `<...>` 就认定为模板：
    模板的选项标题本身带 `<可选>`，用户填好后也可能保留说明性尖括号。
    """
    return any(key in line for key in TEMPLATE_ECHO_KEYS)


def _checked_codes(chunk: str, allowed) -> list:
    """解析 `- [x] code` 形式，返回被勾选的 code（按模板顺序）。"""
    hits = []
    for code in allowed:
        if re.search(r"\[[xX]\]\s*`?%s`?\b" % re.escape(code), chunk):
            hits.append(code)
    return hits


def _checked_bracket_codes(chunk: str, allowed) -> list:
    """解析 `[x] code` 形式（Q3 的选项没有反引号）。"""
    hits = []
    for code in allowed:
        if re.search(r"\[[xX]\]\s*[`\"']?%s\b" % re.escape(code), chunk):
            hits.append(code)
    return hits


def _drop_template_lines(chunk: str) -> str:
    """删掉「例：xxx」「本仓库示例：xxx」这类模板示范行，只留用户真实填写的内容。"""
    kept = [line for line in chunk.splitlines()
            if not _looks_like_template(_strip_placeholders(line))]
    return "\n".join(kept)


def parse_todo(path: str = TODO_PATH) -> dict:
    if not os.path.isfile(path):
        raise FileNotFoundError("找不到 TODO.md：%s" % path)
    text = read_text(path)

    q = {}
    for title, body in _question_blocks(text):
        num = re.match(r"^Q(\d)", title)
        if not num:
            continue
        q[int(num.group(1))] = body

    data = {key: "" for key, _ in QUESTION_SPECS}
    data["raw"] = text[:4000]

    # Q1：站点 / 入口链接（取自「入口链接」段，fence 内为主）/ 抓取范围 / 指定清单
    q1 = q.get(1, "")
    real_q1 = _drop_template_lines(q1)
    data["source_site"] = _marker_value(real_q1, "站点名称")
    urls = URL_RE.findall(_strip_placeholders(real_q1))
    data["source_urls"] = list(dict.fromkeys(urls))
    scope_lines = _clean_lines(_body_of(real_q1, "抓取范围") or "")
    data["scope"] = scope_lines[0] if scope_lines else ""
    if data["scope"] and re.search(r"N\s*=\s*$", data["scope"]):
        data["scope"] = ""   # 模板示例行「全站前 N 页 → N =」未填写
    data["target_list"] = _after_marker_lines(real_q1, "指定清单")
    if not data["scope"]:
        # 未用围栏时退化为逐行扫描（已剔除模板示范行）
        scope_candidates = [l for l in _clean_lines(real_q1)
                            if any(k in l for k in ("页", "全部", "清单", "链接"))]
        data["scope"] = scope_candidates[0] if scope_candidates else ""

    # Q2：包类型（四选一）
    q2 = q.get(2, "")
    types = _checked_codes(q2, ALLOWED_TYPES)
    data["package_type"] = types[0] if len(types) == 1 else ""
    data["package_type_hits"] = types

    # Q3：图片策略（三选一）+ 可选补充说明
    q3 = q.get(3, "")
    strategies = _checked_bracket_codes(q3, ALLOWED_IMAGE_STRATEGIES)
    data["image_strategy"] = strategies[0] if len(strategies) == 1 else ""
    data["image_strategy_hits"] = strategies
    detail_lines = _after_marker_lines(q3, "可选")
    data["image_detail"] = detail_lines[0] if detail_lines else ""

    # Q4：是否已有数据 + 数据路径
    q4 = q.get(4, "")
    ready = _checked_bracket_codes(q4, ("no", "yes"))
    ready_codes = [c for c in ("yes", "no") if c in ready]
    data["data_ready"] = ready_codes[0] if len(ready_codes) == 1 else ""
    path_lines = _after_marker_lines(q4, "若选")
    data["existing_paths"] = path_lines

    # 选填项（表格行：| 项目 | 填这里 | 默认值 |）
    extras = {}
    for match in re.finditer(r"^\|\s*(导入时冲突策略|AMMDS 版本号|额外要求)\s*\|\s*(.*?)\s*\|", text, re.M):
        value = _strip_placeholders(match.group(2)).replace("`", "").strip()
        if value:
            extras[match.group(1)] = value
    data["conflict_policy"] = extras.get("导入时冲突策略", "")
    data["app_version"] = extras.get("AMMDS 版本号", "")
    data["extra"] = extras.get("额外要求", "")

    return data


def check_todo(todo: dict) -> "tuple[list, list]":
    """返回 (errors, warnings)。errors 非空 => 用户没填完，必须停下来问用户。"""
    errors, warnings = [], []

    if not todo["source_site"] and not todo["source_urls"]:
        errors.append("Q1 未填写：请用户给出站点名称/域名 或 入口链接")
    if not todo["package_type"]:
        hits = todo.get("package_type_hits") or []
        if len(hits) > 1:
            errors.append("Q2 勾选了多项（%s）：必须四选一" % " / ".join(hits))
        else:
            errors.append("Q2 未勾选：请用户在 movie / actor / comic / novel 中选一个")
    if not todo["image_strategy"]:
        hits = todo.get("image_strategy_hits") or []
        if len(hits) > 1:
            errors.append("Q3 勾选了多项（%s）：必须三选一" % " / ".join(hits))
        else:
            errors.append("Q3 未勾选：请用户在 pack / link / none 中选一个")
    if not todo["data_ready"]:
        errors.append("Q4 未勾选：请用户确认 yes（已有数据）/ no（需要抓取）")
    if todo["data_ready"] == "yes" and not todo["existing_paths"]:
        errors.append("Q4 选了 yes，但没写数据文件/文件夹路径")
    if todo.get("conflict_policy") and todo["conflict_policy"] not in ALLOWED_CONFLICT_POLICIES:
        warnings.append("冲突策略 %r 非标准值，建议 skip / overwrite / merge；将按 skip 写入交付说明"
                        % todo["conflict_policy"])

    if todo["data_ready"] == "no" and not todo["source_urls"]:
        warnings.append("Q1 没有给出可用的 http(s) 入口链接，抓取阶段需要先向用户确认入口")
    if not todo["scope"]:
        warnings.append("Q1 未写明抓取范围，默认按「全站前 5 页」处理（需在 todo_snapshot 中记录）")
    return errors, warnings


# --------------------------------------------------------------------------- #
# _meta.json：TODO -> 机器可读配置（AI 归一化后写入，是唯一事实来源）
# --------------------------------------------------------------------------- #

META_TEMPLATE = {
    "package_type": "movie",
    "source_mode": "scrape",
    "image_strategy": "pack",
    "app_version": pack.DEFAULT_APP_VERSION,
    "conflict_policy": "skip",
    "generated_at": "",
    "todo_snapshot": {
        "site": "",
        "urls": [],
        "scope": "",
        "target_list": [],
        "image_detail": "",
        "extra": ""
    },
    "source": {
        "input_paths": [],
        "entry_url": "",
        "fetched_at": "",
        "pages": 0,
        "notes": ""
    },
    "notes": ""
}

BUILD_CONFIG_TEMPLATE = {
    "_comment": "构建开关；打包参数（type / 图片策略 / 版本号）以 work/_meta.json 为准",
    "run_verify": True,
    "fail_on_warning": False,
}


def load_meta() -> dict:
    if not os.path.isfile(META_PATH):
        raise FileNotFoundError(
            "缺少 %s。先执行 `python tools/auto_backup.py init`，"
            "再按 TODO.md 填写该文件（AI 负责归一化）。" % rel(META_PATH))
    meta = read_json(META_PATH)
    if not isinstance(meta, dict):
        raise ValueError("%s 顶层必须是对象" % rel(META_PATH))
    return meta


def check_meta(meta: dict) -> "tuple[list, list]":
    errors, warnings = [], []
    if meta.get("package_type") not in ALLOWED_TYPES:
        errors.append("_meta.package_type 非法：%r（允许 %s）"
                      % (meta.get("package_type"), " / ".join(ALLOWED_TYPES)))
    if meta.get("source_mode") not in ALLOWED_SOURCE_MODES:
        errors.append("_meta.source_mode 非法：%r（允许 %s）"
                      % (meta.get("source_mode"), " / ".join(ALLOWED_SOURCE_MODES)))
    if meta.get("image_strategy") not in ALLOWED_IMAGE_STRATEGIES:
        errors.append("_meta.image_strategy 非法：%r（允许 %s）"
                      % (meta.get("image_strategy"), " / ".join(ALLOWED_IMAGE_STRATEGIES)))
    if meta.get("conflict_policy") not in ALLOWED_CONFLICT_POLICIES:
        warnings.append("_meta.conflict_policy 非标准值 %r，建议 skip / overwrite / merge"
                        % meta.get("conflict_policy"))
    if not isinstance(meta.get("app_version"), str) or not meta.get("app_version"):
        warnings.append("_meta.app_version 为空，回退 %s" % pack.DEFAULT_APP_VERSION)
    return errors, warnings


def ensure_year_field(records: list) -> None:
    """规范第 5.4 节：novel 的 publishYear 是字符串，写成整数会被忽略。"""
    for record in records:
        if isinstance(record, dict) and isinstance(record.get("publishYear"), int):
            record["publishYear"] = str(record["publishYear"])


# --------------------------------------------------------------------------- #
# init：铺开工作区
# --------------------------------------------------------------------------- #

RECORD_TEMPLATE_HINT = {
    "movie": [
        {"uniqueid": ["AI-001"], "originalTitle": "AI-001 Sample Movie",
         "poster": ["data/images/media/2026/09/ai-001-poster.jpg"], "dataSource": "user"}
    ],
    "actor": [
        {"name": "示例演员", "poster": "data/images/actor/2026/09/ai-actor.jpg", "dataSource": "user"}
    ],
    "comic": [
        {"title": "示例漫画", "isbn": "9780000000001", "cover": "data/images/gallery/comic/cover/x.jpg",
         "chapters": [{"title": "第 1 话", "episode": 1,
                       "pages": [{"imagePath": "data/images/gallery/comic/story/x-001.jpg",
                                  "sequence": 1}]}]}
    ],
    "novel": [
        {"title": "示例小说", "author": "示例作者", "cover": "data/images/novel/cover/x.jpg",
         "chapters": [{"title": "第一章", "content": "正文", "sort": 1}]}
    ],
}


def cmd_init(args) -> int:
    created, skipped = [], []

    def emit(path: str, content: str, force: bool = False) -> None:
        if os.path.exists(path) and not force:
            skipped.append(rel(path))
            return
        write_text(path, content)
        created.append(rel(path))

    for directory in (WORK_DIR, IMAGES_DIR, SCRIPTS_DIR, SOURCE_DIR, RECORDS_DIR, OUTPUT_DIR):
        os.makedirs(directory, exist_ok=True)

    emit(os.path.join(SCRIPTS_DIR, ".gitkeep"), "")
    emit(os.path.join(SOURCE_DIR, "README.md"),
         "# source/：抓取或用户提供的原始数据\n\n"
         "约定：一个来源一个文件，文件名带日期，保留原始结构不改写。\n\n"
         "- `scrape` 模式：`<site>-<type>-<yyyyMMdd>.raw.json`（+ `*.html` / `*.csv` 均可）\n"
         "- `existing` 模式：用户给的原始导出文件也先复制到这里，**不要直接改用户文件**\n\n"
         "> 本目录只作留痕与复现用，不参与打包。真正参与打包的是 `work/records/`。\n")
    emit(os.path.join(RECORDS_DIR, "README.md"),
         "# records/：参与打包的归一化记录\n\n"
         "每个类型一个文件，文件名固定：`movie.json` / `actor.json` / `comic.json` / `novel.json`。\n"
         "（`_examples/` 下是四种类型的骨架样例，仅供参考，不会被 build 读取。）\n\n"
         "- 顶层必须是 **JSON 数组**，元素字段名严格遵守《AI备份包生成规范》第 5 节。\n"
         "- 整数字段写整数（`120`，不是 `120.0`）；日期写 `yyyy-MM-dd`；枚举只写 code。\n"
         "- 取不到的字段**直接省略**，不要写 `\"未知\"` / `\"-\"` / `\"N/A\"`。\n"
         "- 图片字段见《生成记录规范》第 4 节（movie.poster 是数组，actor.poster 是单值……）。\n")
    for btype, example in RECORD_TEMPLATE_HINT.items():
        emit(os.path.join(RECORDS_DIR, "_examples", "%s.json" % btype),
             json.dumps(example, ensure_ascii=False, indent=2) + "\n")
    emit(os.path.join(WORK_DIR, "build_config.json"),
         json.dumps(BUILD_CONFIG_TEMPLATE, ensure_ascii=False, indent=2) + "\n")
    emit(META_PATH, json.dumps(META_TEMPLATE, ensure_ascii=False, indent=2) + "\n")

    print("=== init 完成 ===")
    if created:
        print("已创建/更新：")
        for path in created:
            print("  + %s" % path)
    if skipped:
        print("已存在，未改动：")
        for path in skipped:
            print("  = %s" % path)
    print("\n下一步：填写 TODO.md，然后把 TODO 的答案归一化进 %s（见 AI.md 第 2 步）。" % rel(META_PATH))
    return 0


# --------------------------------------------------------------------------- #
# build：records + images -> zip + 自检 + 交付说明
# --------------------------------------------------------------------------- #

PLACEHOLDER_VALUES = {"未知", "-", "n/a", "N/A", "na", "null", "无", "暂无", "unknown"}


def quality_checks(btype: str, records: list, refs_in_data: set,
                   strategy: str = "pack") -> "tuple[list, list]":
    """规范第 11 节的条目级 / 静默失败自查，返回 (errors, warnings)。"""
    errors, warnings = [], []
    int_fields = {"runtime", "pageCount", "resolutionWidth", "resolutionHeight", "season",
                  "episode", "sequence", "sort", "fileSizeByte", "duration"}
    match_key = {"movie": "uniqueid", "actor": "name", "comic": "title", "novel": "title"}[btype]

    for index, record in enumerate(records):
        where = "%s[%d]" % (rel(os.path.join(RECORDS_DIR, "%s.json" % btype)), index)
        if not isinstance(record, dict):
            errors.append("%s 不是对象" % where)
            continue

        key = record.get(match_key)
        if key in (None, "", [], {}):
            errors.append("%s 缺少导入匹配键 `%s`（该条目导入必失败）" % (where, match_key))

        def walk(node, path):
            if isinstance(node, dict):
                for field, value in node.items():
                    walk(value, "%s.%s" % (path, field))
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    walk(value, "%s[%d]" % (path, i))
            else:
                if isinstance(node, str) and node.strip() in PLACEHOLDER_VALUES:
                    warnings.append("%s = %r 是占位符，应删除该字段" % (path, node))
                field = path.rsplit(".", 1)[-1].split("[")[0]
                if field in int_fields and isinstance(node, float) and node.is_integer() is False:
                    errors.append("%s 是整数型字段却写了小数 %r（会导致该条目导入失败）" % (path, node))
                if field in int_fields and isinstance(node, float) and node.is_integer():
                    warnings.append("%s 写成了 %r，请改成整数 %d" % (path, node, int(node)))

        walk(record, where)

        for bad_field in ("id", "createdTime", "updatedTime", "version"):
            if bad_field in record:
                warnings.append("%s 含被忽略字段 `%s`，建议删除" % (where, bad_field))

        if btype == "comic" and not record.get("chapters"):
            errors.append("%s 是 comic 但没有 chapters" % where)
        if btype == "novel" and not record.get("chapters"):
            errors.append("%s 是 novel 但没有 chapters" % where)

    local_refs = {r for r in refs_in_data if isinstance(r, str) and not r.startswith(("http://", "https://"))}
    if local_refs and strategy == "link":
        warnings.append("策略为 link，但 data.json 里仍有 %d 个本地打包引用（`data/...`）；"
                        "若不想打包图片，应把这些字段改成完整 http(s) URL" % len(local_refs))
    return errors, warnings


def load_records(btype: str) -> list:
    path = os.path.join(RECORDS_DIR, "%s.json" % btype)
    if not os.path.isfile(path):
        raise FileNotFoundError(
            "缺少 %s。AI 需要先把抓取/用户数据归一化成该文件（见《生成记录规范》）。" % rel(path))
    records = read_json(path)
    if not isinstance(records, list):
        raise ValueError("%s 顶层必须是 JSON 数组（规范第 4.1 节）" % rel(path))
    if not records:
        raise ValueError("%s 是空数组，没有可导入的条目" % rel(path))
    ensure_year_field(records)
    return records


def load_images() -> dict:
    """work/images/<ref> 的目录结构就是 ref 本身，天然与 data.json 对齐。"""
    mapping = {}
    if not os.path.isdir(IMAGES_DIR):
        return mapping
    for dirpath, _dirnames, filenames in os.walk(IMAGES_DIR):
        for name in filenames:
            local = os.path.join(dirpath, name)
            ref = rel(os.path.relpath(local, IMAGES_DIR))
            mapping[ref] = local
    return mapping


def load_build_config() -> dict:
    """
    work/build_config.json：可选的构建开关（打包参数仍以 work/_meta.json 为准）。

        run_verify       是否在打包后跑结构自检，默认 True
        fail_on_warning  存在 WARN 即视为失败（等价命令行 --strict），默认 False
    """
    path = os.path.join(WORK_DIR, "build_config.json")
    defaults = {"run_verify": True, "fail_on_warning": False}
    if not os.path.isfile(path):
        return defaults
    try:
        cfg = read_json(path)
    except ValueError as exc:
        print("WARN  %s 解析失败，忽略：%s" % (rel(path), exc))
        return defaults
    if not isinstance(cfg, dict):
        print("WARN  %s 顶层不是对象，忽略" % rel(path))
        return defaults
    for key, value in defaults.items():
        if not isinstance(cfg.get(key), bool):
            cfg[key] = value
    return cfg


def cmd_build(args) -> int:
    meta = load_meta()
    config = load_build_config()
    meta_errors, meta_warnings = check_meta(meta)
    for warn in meta_warnings:
        print("WARN  %s" % warn)
    if meta_errors:
        print("=== build 中止：_meta.json 不合法 ===")
        for err in meta_errors:
            print("ERROR %s" % err)
        return 2

    btype = meta["package_type"]
    strategy = meta["image_strategy"]
    app_version = meta.get("app_version") or pack.DEFAULT_APP_VERSION

    if args.output:
        out_zip = args.output
    else:
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        out_zip = os.path.join(OUTPUT_DIR, "ammds-backup-%s-%s.zip" % (btype, stamp))

    records = load_records(btype)
    images = load_images()

    refs_in_data = pack._data_image_refs(btype, records)
    packed_refs = {r for r in refs_in_data
                   if isinstance(r, str) and not r.startswith(("http://", "https://"))}
    missing = sorted(r for r in packed_refs if strategy == "pack" and r not in images)

    print("=== build 参数 ===")
    print("  包类型 type        : %s (%s)" % (btype, TYPE_CN.get(btype, "?")))
    print("  数据来源 source_mode: %s" % meta["source_mode"])
    print("  图片策略           : %s" % strategy)
    print("  条目数             : %d" % len(records))
    print("  引用图片           : 本地 %d / 外链 %d"
          % (len(packed_refs), len(refs_in_data) - len(packed_refs)))
    print("  本地图片池         : %d 个文件（%s）" % (len(images), rel(IMAGES_DIR)))
    if btype == "comic":
        page_total = sum(len((ch or {}).get("pages") or [])
                         for r in records if isinstance(r, dict)
                         for ch in (r.get("chapters") or []))
        print("  漫画章节页总数     : %d 页" % page_total)
    print("  产物               : %s" % rel(out_zip))

    if missing:
        print("\n=== build 中止：以下本地引用在 work/images/ 下找不到对应文件 ===")
        for ref in missing[:50]:
            print("  MISSING %s" % ref)
        if len(missing) > 50:
            print("  ...（共 %d 个）" % len(missing))
        print("提示：pack 策略要求每个非 http(s) 的图片字段值都能在 work/images/<ref> 找到文件；"
              "若某些图确实抓不到，请改走外链（http(s) URL）或从字段中移除。")
        return 2

    # pack：把 work/images 当成本地图片池；link/none：不打包任何图片
    images_arg = images if strategy == "pack" else {}
    include_images = strategy == "pack" and bool(images_arg)

    manifest = pack.build_backup(out_zip, btype, records, images_arg,
                                 include_images=include_images, app_version=app_version)

    if config["run_verify"]:
        problems, warnings = pack.verify_backup(out_zip)
    else:
        problems, warnings = [], ["build_config.run_verify=false，已跳过结构自检（不推荐）"]
    q_errors, q_warnings = quality_checks(btype, records, refs_in_data, strategy)
    warnings = list(warnings) + list(q_warnings)

    if strategy == "none":
        empty_refs = [r for r in refs_in_data if isinstance(r, str) and not r.startswith("http")]
        if empty_refs:
            warnings.append("图片策略=none，但 data.json 里仍有 %d 个图片引用；建议清空这些字段"
                            % len(empty_refs))

    print("\n=== 自检（%s）===" % rel(os.path.join(RULE_DIR, "ammds_backup_pack.py")))
    for warn in warnings:
        print("WARN  %s" % warn)
    for err in list(problems) + list(q_errors):
        print("ERROR %s" % err)
    ok = not problems and not q_errors
    print("校验%s（ERROR=%d，WARN=%d）" % ("通过" if ok else "未通过",
                                       len(problems) + len(q_errors), len(warnings)))

    zip_size = os.path.getsize(out_zip) if os.path.isfile(out_zip) else 0
    report_path = os.path.join(OUTPUT_DIR, "deliver.md")
    write_report(report_path, meta, manifest, out_zip, zip_size, problems, q_errors,
                 warnings, records, images)
    print("\n交付说明已写入：%s" % rel(report_path))

    if not ok and not args.force:
        return 1
    if warnings and (args.strict or config["fail_on_warning"]):
        print("--strict / fail_on_warning：存在 WARN，按失败处理")
        return 1
    return 0


# --------------------------------------------------------------------------- #
# report：交付说明
# --------------------------------------------------------------------------- #

IMPORT_STEPS = """1. 打开 AMMDS → **系统 → 备份恢复 → 数据导入**
2. 选择本包 zip → 点击「**解析预览**」，应显示 **校验通过**
3. 选择冲突策略：`skip`（跳过已存在）/ `overwrite`（覆盖重建）/ `merge`（字段级合并）
4. 点击「开始导入」，确认结果为 **failed=0**"""

CONFLICT_HINT = {
    "skip": "跳过已存在（首次导入最安全，不会动到库里已有数据）",
    "overwrite": "覆盖更新（同键记录会被本包内容覆盖；漫画会删除重建章节与页）",
    "merge": "字段级合并（影视/演员合并字段、漫画补章节、小说整本重建）",
}


def write_report(path, meta, manifest, out_zip, zip_size, problems, q_errors,
                 warnings, records, images) -> None:
    btype = manifest.get("type")
    image_files = manifest.get("imageFiles") or []
    lines = []
    lines.append("# 备份包交付说明")
    lines.append("")
    lines.append("> 本文件由 `tools/auto_backup.py build` 自动生成，随包一起交付给用户。")
    lines.append("")
    lines.append("## 1. 产物")
    lines.append("")
    lines.append("| 项目 | 值 |")
    lines.append("| --- | --- |")
    lines.append("| 包路径 | `%s` |" % rel(out_zip))
    lines.append("| 类型 `manifest.type` | `%s`（%s） |" % (btype, TYPE_CN.get(btype, "?")))
    lines.append("| 条目数 `count` | %d |" % manifest.get("count", 0))
    lines.append("| 含图片 `includeImages` | %s |" % str(manifest.get("includeImages")).lower())
    lines.append("| 图片数量 `imageFiles` | %d |" % len(image_files))
    lines.append("| 包体积 | %s（%d 字节） |" % (human_size(zip_size), zip_size))
    lines.append("| 生成时间 `generatedAt` | %s |" % manifest.get("generatedAt", ""))
    lines.append("| 目标版本 `appVersion` | %s |" % manifest.get("appVersion", ""))
    lines.append("| 图片策略 | `%s` |" % meta.get("image_strategy", ""))
    lines.append("| 数据来源模式 | `%s` |" % meta.get("source_mode", ""))
    lines.append("| zip SHA-256 | `%s` |" % (sha256_file(out_zip) if os.path.isfile(out_zip) else "-"))
    lines.append("")

    lines.append("## 2. 自检结果")
    lines.append("")
    lines.append("- ERROR：**%d**（必须为 0）" % (len(problems) + len(q_errors)))
    lines.append("- WARN：%d" % len(warnings))
    lines.append("")
    if problems or q_errors:
        lines.append("### ERROR 明细")
        lines.append("")
        for err in list(problems) + list(q_errors):
            lines.append("- ❌ %s" % err)
        lines.append("")
    if warnings:
        lines.append("### WARN 明细")
        lines.append("")
        for warn in warnings:
            lines.append("- ⚠️ %s" % warn)
        lines.append("")
    if not problems and not q_errors:
        lines.append("自检通过：结构 / 清单 / 字段类型 / 图片对齐均满足《AI备份包生成规范》。")
        lines.append("")

    lines.append("## 3. 内容概览")
    lines.append("")
    lines.append("| # | 匹配键 | 标题 / 名称 | 图片字段 | 章节 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for index, record in enumerate(records[:30]):
        if not isinstance(record, dict):
            continue
        match = record.get("uniqueid") or record.get("name") or record.get("isbn") or record.get("title") or "-"
        if isinstance(match, list):
            match = ", ".join(str(m) for m in match)
        title = record.get("titleCn") or record.get("originalTitle") or record.get("name") \
            or record.get("title") or "-"
        used = sorted({f for f in ("poster", "fanart", "thumb", "extrafanart", "cover",
                                   "backCover", "posterHd", "fanartHd", "thumbHd")
                       if record.get(f)})
        chapters = len(record.get("chapters") or [])
        lines.append("| %d | %s | %s | %s | %s |"
                     % (index + 1, str(match)[:40], str(title)[:40],
                        ", ".join(used) or "-", chapters or "-"))
    if len(records) > 30:
        lines.append("| ... | | 其余 %d 条见 `records/%s.json` | | |" % (len(records) - 30, btype))
    lines.append("")

    if image_files:
        lines.append("## 4. 图片清单（前 20 条）")
        lines.append("")
        lines.append("| ref | path | sha256（前 12 位） |")
        lines.append("| --- | --- | --- |")
        for item in image_files[:20]:
            lines.append("| `%s` | `%s` | `%s...` |"
                         % (item.get("ref", ""), item.get("path", ""),
                            str(item.get("sha256", ""))[:12]))
        if len(image_files) > 20:
            lines.append("| ... | 其余 %d 条见 manifest.json | |" % (len(image_files) - 20))
        lines.append("")
        local_missing = [r for r in pack._data_image_refs(btype, records)
                         if isinstance(r, str) and not r.startswith("http")
                         and r not in images]
        if local_missing:
            lines.append("> ⚠️ 有 %d 个本地引用未打包（`data.json` 里保留原值，导入后为坏路径）。" % len(local_missing))
            lines.append("")

    lines.append("## 5. 导入步骤")
    lines.append("")
    lines.append(IMPORT_STEPS)
    lines.append("")
    policy = meta.get("conflict_policy") or "skip"
    hint = CONFLICT_HINT.get(policy, "非标准策略，请自行确认影响")
    lines.append("> **建议冲突策略：`%s`** —— %s" % (policy, hint))
    lines.append("")

    lines.append("## 6. 已知风险 / 备注")
    lines.append("")
    notes = []
    if meta.get("notes"):
        notes.append(meta["notes"])
    snapshot = meta.get("todo_snapshot") or {}
    if snapshot.get("site"):
        notes.append("抓取来源：%s" % snapshot["site"])
    if snapshot.get("scope"):
        notes.append("抓取范围：%s" % snapshot["scope"])
    if snapshot.get("image_detail"):
        notes.append("图片特别要求：%s" % snapshot["image_detail"])
    if snapshot.get("extra"):
        notes.append("用户额外要求：%s" % snapshot["extra"])
    source = meta.get("source") or {}
    if source.get("fetched_at"):
        notes.append("抓取时间：%s" % source["fetched_at"])
    if not notes:
        notes.append("无")
    for note in notes:
        lines.append("- %s" % note)
    lines.append("")

    write_text(path, "\n".join(lines) + "\n")


def cmd_report(args) -> int:
    zips = sorted((os.path.join(OUTPUT_DIR, n) for n in os.listdir(OUTPUT_DIR)
                   if n.lower().endswith(".zip")), key=os.path.getmtime) if os.path.isdir(OUTPUT_DIR) else []
    if not zips:
        print("output/ 下没有 zip，先执行 build")
        return 2
    target = args.zip_path or zips[-1]
    meta = load_meta()
    with zipfile.ZipFile(target) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        records = json.loads(zf.read("data.json").decode("utf-8"))
    problems, warnings = pack.verify_backup(target)
    q_errors, q_warnings = quality_checks(manifest.get("type", ""), records,
                                          pack._data_image_refs(manifest.get("type", ""), records),
                                          meta.get("image_strategy", "pack"))
    report_path = os.path.join(OUTPUT_DIR, "deliver.md")
    write_report(report_path, meta, manifest, target, os.path.getsize(target),
                 problems, q_errors, list(warnings) + list(q_warnings), records, load_images())
    print("已重新生成 %s（基于 %s）" % (rel(report_path), rel(target)))
    return 0 if not problems and not q_errors else 1


# --------------------------------------------------------------------------- #
# todo / verify
# --------------------------------------------------------------------------- #

def cmd_todo(args) -> int:
    todo = parse_todo()
    errors, warnings = check_todo(todo)

    print("=== TODO.md 预检 ===")
    print("  Q1 站点      : %s" % (todo["source_site"] or "(未填)"))
    print("  Q1 入口链接  : %s" % ("; ".join(todo["source_urls"]) or "(未填)"))
    print("  Q1 抓取范围  : %s" % (todo["scope"] or "(未填，默认前 5 页)"))
    print("  Q1 指定清单  : %s" % ("; ".join(todo["target_list"]) or "(无)"))
    print("  Q2 包类型    : %s" % (todo["package_type"] or "(未勾选)"))
    print("  Q3 图片策略  : %s" % (todo["image_strategy"] or "(未勾选)"))
    print("  Q4 已有数据  : %s" % (todo["data_ready"] or "(未勾选)"))
    if todo["existing_paths"]:
        print("  Q4 数据路径  : %s" % "; ".join(todo["existing_paths"]))
    if todo["image_detail"]:
        print("  Q3 图片补充  : %s" % todo["image_detail"])
    if todo["conflict_policy"] or todo["app_version"] or todo["extra"]:
        print("  选填         : 冲突策略=%s 版本=%s 额外=%s"
              % (todo["conflict_policy"] or "skip", todo["app_version"] or pack.DEFAULT_APP_VERSION,
                 todo["extra"] or "无"))

    for warn in warnings:
        print("WARN  %s" % warn)
    for err in errors:
        print("ERROR %s" % err)

    ok = not errors
    if ok:
        print("TODO 已填完整 ✅")
        if os.path.isfile(META_PATH):
            meta_errors, meta_warnings = check_meta(load_meta())
            for warn in meta_warnings:
                print("WARN  %s" % warn)
            for err in meta_errors:
                print("ERROR %s" % err)
            if meta_errors:
                ok = False
        else:
            print("WARN  尚未生成 %s，build 前需先按 TODO 归一化该文件" % rel(META_PATH))
    else:
        print("TODO 未填完整 ❌ —— 请 AI 停下来向用户提问，不要自行编造答案（见 AI.md 第 2 步）")
    return 0 if ok else 1


def cmd_verify(args) -> int:
    problems, warnings = pack.verify_backup(args.zip_path)
    for warn in warnings:
        print("WARN  %s" % warn)
    for err in problems:
        print("ERROR %s" % err)
    print("校验%s：%s" % ("通过" if not problems else "未通过", args.zip_path))
    return 0 if not problems else 1


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #

def cmd_selftest(args) -> int:
    """转发到 tools/selftest.py，方便只记一个入口。"""
    import runpy
    target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "selftest.py")
    sys.argv = [target]
    try:
        runpy.run_path(target, run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auto_backup.py",
        description="AMMDS 备份包模板仓库：由 TODO.md 驱动产出并自检备份包")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="初始化 work/ 工作区与模板文件（幂等）")

    sub.add_parser("todo", help="预检 TODO.md / work/_meta.json 是否填完整")

    sub.add_parser("selftest", help="跑内置自检（生成 mock 数据，会覆盖 work/ 与 output/）")

    p_build = sub.add_parser("build", help="由 records + images 产出 zip、自检并写交付说明")
    p_build.add_argument("--output", help="指定输出 zip 路径（默认 output/ammds-backup-<type>-<时间戳>.zip）")
    p_build.add_argument("--force", action="store_true", help="即使自检失败也返回 0（仅用于排查）")
    p_build.add_argument("--strict", action="store_true", help="存在 WARN 也视为失败")

    p_verify = sub.add_parser("verify", help="自检一个已有 zip")
    p_verify.add_argument("zip_path")

    p_report = sub.add_parser("report", help="按 output/ 中最新（或指定）的 zip 重新生成 deliver.md")
    p_report.add_argument("zip_path", nargs="?")

    return parser


def main(argv=None) -> int:
    _stdout_utf8()
    args = build_parser().parse_args(argv)
    handlers = {"init": cmd_init, "todo": cmd_todo, "build": cmd_build,
                "verify": cmd_verify, "report": cmd_report, "selftest": cmd_selftest}
    try:
        return handlers[args.cmd](args)
    except (FileNotFoundError, ValueError) as exc:
        print("ERROR %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
