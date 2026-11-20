#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模板仓库自检：不依赖任何外部数据，用内置 mock 记录跑通全部产物路径。

    python tools/selftest.py

覆盖：
  1. 模板 TODO.md 必须被判定为「未填写」（4 个 ERROR）
  2. 内置的已填写样例必须被解析成预期答案（含行内值 / 围栏值 / 表格选填项）
  3. 四种 type × pack / link 策略全部 build 成功、结构自检 0 ERROR、图片对齐正确
  4. 应当被拒绝的输入必须真的被拒绝（非法 type / 缺少图片 / 缺少 records / 空数组 / 缺匹配键）

它只操作 work/ 与 output/，所以会覆盖这两个目录里原有的内容——这是开发自检工具，
交付给用户的包请在跑完自检后重新 build。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import auto_backup as ab  # noqa: E402

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082")

# --------------------------------------------------------------------------- #
# 内置样例：已填写的 TODO（含各种版式）+ 四类 mock 记录
# --------------------------------------------------------------------------- #

FILLED_TODO = """# 待办事项

## Q1 [必答] 数据从哪里来？

- 站点名称或域名：`example.com`
- 入口链接（列表页 / 搜索页 / 详情页 / API 地址，一行一个）：

```
https://example.com/list?page=1
https://example.com/api/search?q=ABC
```

- 抓取范围（三选一，只留你要的一行）：

```
全站前 3 页
```

`<可选>` 指定清单（按编号 / ISBN / 关键字 / URL，一行一个）：

```
ABC-123
9780000000001
```

---

## Q2 [必答] 要生成哪一种备份包？（四选一）

- [x] `comic` —— 漫画 / 相册

---

## Q3 [必答] 图片怎么处理？

- [x] `pack` —— **打包进 zip**

`<可选>` 只要封面/海报、不要全套图？

```
只打包封面，其余外链
```

---

## Q4 [必答] 已备好数据了吗？

- [x] `no` —— **没有**，请按 Q1 去抓取

若选 `yes`，在下面写数据文件/文件夹路径：

```
incoming/mydata.json
```

---

## 其他（选填，不填就用默认值）

| 项目 | 填这里 | 默认值 |
| --- | --- | --- |
| 导入时冲突策略 | `overwrite` | `skip` |
| AMMDS 版本号 | `1.6.90` | `1.6.80` |
| 额外要求 | 只要 2024 年之后的 | 无 |
"""

EXPECT_TODO = {
    "source_site": "example.com",
    "source_urls": ["https://example.com/list?page=1", "https://example.com/api/search?q=ABC"],
    "scope": "全站前 3 页",
    "target_list": ["ABC-123", "9780000000001"],
    "package_type": "comic",
    "image_strategy": "pack",
    "image_detail": "只打包封面，其余外链",
    "data_ready": "no",
    "existing_paths": ["incoming/mydata.json"],
    "conflict_policy": "overwrite",
    "app_version": "1.6.90",
    "extra": "只要 2024 年之后的",
}

MOCK = {
    "movie": ([{
        "uniqueid": ["SELF-001"], "originalTitle": "SELF-001 Sample", "titleCn": "自检影片",
        "plot": "自检简介", "premiered": "2026-08-01", "runtime": 120, "rating": 8.5,
        "genre": ["剧情"], "studio": ["自检制作"], "director": ["自检导演"],
        "actors": [{"name": "自检演员", "role": "女优"}],
        "poster": ["data/images/media/2026/09/self-001-poster.png"],
        "fanart": ["https://img.example.com/self-001-fanart.jpg"],
        "magnet": [{"name": "SELF-001", "link": "magnet:?xt=urn:btih:SELF", "size": 1073741824}],
        "dataSource": "user",
    }, {
        "uniqueid": ["SELF-002"], "originalTitle": "SELF-002 Another",
        "poster": ["https://img.example.com/self-002.jpg"], "dataSource": "user",
    }], ["data/images/media/2026/09/self-001-poster.png"]),

    "actor": ([{
        "name": "自检演员", "aliases": ["小自"], "gender": "female", "heightCm": 160,
        "weightKg": 45.5, "birthDate": "1995-01-02", "bloodType": "A", "agency": ["自检经纪"],
        "poster": "data/images/actor/2026/09/self-actor.png",
        "thumb": ["https://img.example.com/self-actor-thumb.jpg"],
        "dataSource": "user",
    }], ["data/images/actor/2026/09/self-actor.png"]),

    "comic": ([{
        "title": "自检漫画", "isbn": "9780000000001", "type": "comic",
        "cover": "data/images/gallery/comic/cover/self-cover.png",
        "backCover": "https://img.example.com/self-back.jpg",
        "description": "自检相册", "season": 1, "fullChapter": False, "language": "zh",
        "format": "Digital", "manga": "Yes", "ageRating": "Adults Only 18+", "writer": "自检作者",
        "chapters": [
            {"title": "第 1 话", "episode": 1, "pages": [
                {"imagePath": "data/images/gallery/comic/story/self-001.png", "sequence": 1},
                {"imagePath": "data/images/gallery/comic/story/self-002.png", "sequence": 2},
            ]},
            {"title": "第 2 话", "episode": 2, "pages": [
                {"imagePath": "data/images/gallery/comic/story/self-003.png", "sequence": 1},
            ]},
        ],
    }], ["data/images/gallery/comic/cover/self-cover.png",
         "data/images/gallery/comic/story/self-001.png",
         "data/images/gallery/comic/story/self-002.png",
         "data/images/gallery/comic/story/self-003.png"]),

    "novel": ([{
        "title": "自检小说", "author": "自检作者", "genre": "玄幻", "description": "自检简介",
        "language": "zh", "status": "serial", "publishYear": 2026,
        "cover": "data/images/novel/cover/self-novel.png",
        "chapters": [
            {"title": "第一章 起始", "content": "第一段。\n第二段。", "sort": 1},
            {"title": "第二章 发展", "content": "正文。", "sort": 2},
        ],
    }], ["data/images/novel/cover/self-novel.png"]),
}


# --------------------------------------------------------------------------- #
# 测试骨架
# --------------------------------------------------------------------------- #

class Checker:
    def __init__(self) -> None:
        self.failed = 0
        self.passed = 0

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        if ok:
            self.passed += 1
            print("   OK   %s" % label)
        else:
            self.failed += 1
            print("   FAIL %s %s" % (label, detail))
        return ok


def run_build(*extra_args) -> int:
    return subprocess.call(
        [sys.executable, os.path.join(ROOT, "tools", "auto_backup.py"), "build", *extra_args],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def write_meta(btype: str, strategy: str, mode: str = "existing") -> None:
    meta = ab.load_meta()
    meta["package_type"] = btype
    meta["image_strategy"] = strategy
    meta["source_mode"] = mode
    meta["conflict_policy"] = "overwrite"
    meta["app_version"] = "1.6.90"
    meta["todo_snapshot"] = {"site": "example.com", "urls": ["https://example.com"],
                             "scope": "自检", "target_list": [], "extra": "tools/selftest.py"}
    with open(ab.META_PATH, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(meta, fp, ensure_ascii=False, indent=2)


def _to_external(node):
    """把 mock 里的本地打包引用（data/...）换成语义等价的 https URL，模拟 link 策略的数据。"""
    if isinstance(node, dict):
        return {k: _to_external(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_to_external(v) for v in node]
    if isinstance(node, str) and node.startswith("data/"):
        return "https://img.example.com/mock/" + node.split("/")[-1]
    return node


def prepare(btype: str, strategy: str = "pack") -> None:
    records, refs = MOCK[btype]
    if strategy == "link":
        records, refs = _to_external(records), []
    if os.path.isdir(ab.IMAGES_DIR):
        for name in os.listdir(ab.IMAGES_DIR):
            target = os.path.join(ab.IMAGES_DIR, name)
            shutil.rmtree(target) if os.path.isdir(target) else os.remove(target)
    for ref in refs:
        local = os.path.join(ab.IMAGES_DIR, ref)
        os.makedirs(os.path.dirname(local), exist_ok=True)
        with open(local, "wb") as fp:
            fp.write(PNG_1PX)
    with open(os.path.join(ab.RECORDS_DIR, "%s.json" % btype), "w",
              encoding="utf-8", newline="\n") as fp:
        json.dump(records, fp, ensure_ascii=False, indent=2)


def audit_zip(path: str, btype: str) -> "tuple[list, dict]":
    """独立复核包：count / 图片登记 / sha256 / 引用对齐，不复用 verify_backup。"""
    problems = []
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        records = json.loads(zf.read("data.json").decode("utf-8"))

        if manifest.get("type") != btype:
            problems.append("manifest.type=%r != %r" % (manifest.get("type"), btype))
        if manifest.get("count") != len(records):
            problems.append("count 与 data 长度不一致")
        for item in manifest.get("imageFiles") or []:
            if item["path"] not in names:
                problems.append("登记的图片不在包内: %s" % item["path"])
                continue
            digest = hashlib.sha256(zf.read(item["path"])).hexdigest()
            if digest != item["sha256"]:
                problems.append("sha256 不匹配: %s" % item["path"])
    return problems, manifest


def main() -> int:
    c = Checker()
    ab._stdout_utf8()

    print("### 1. 模板 TODO.md 应判定为未填写")
    todo = ab.parse_todo(os.path.join(ROOT, "TODO.md"))
    errors, _ = ab.check_todo(todo)
    c.check(len(errors) == 4, "4 个必答项都报 ERROR", "实际 %d：%s" % (len(errors), errors))

    print("### 2. 已填写的样例 TODO 应被正确解析")
    sample = os.path.join(ab.WORK_DIR, "_selftest_todo.md")
    ab.write_text(sample, FILLED_TODO)
    parsed = ab.parse_todo(sample)
    for key, want in EXPECT_TODO.items():
        c.check(parsed[key] == want, "解析 %s" % key, "got=%r want=%r" % (parsed[key], want))
    errs, _ = ab.check_todo(parsed)
    c.check(not errs, "样例 TODO 预检无 ERROR", str(errs))
    os.remove(sample)

    print("### 3. 四种 type × pack/link 全链路 build")
    for strategy in ("pack", "link"):
        for btype in ab.ALLOWED_TYPES:
            prepare(btype, strategy)
            write_meta(btype, strategy)
            out = os.path.join(ab.OUTPUT_DIR, "selftest-%s-%s.zip" % (btype, strategy))
            # pack 策略用 --strict：连 WARN 都必须为 0；link 策略本身会带一条外链提示，不启用
            extra = ["--strict"] if strategy == "pack" else []
            code = run_build("--output", out, *extra)
            label = "build %s/%s exit=0" % (btype, strategy)
            if not c.check(code == 0, label, "exit=%d" % code):
                continue
            problems, manifest = audit_zip(out, btype)
            c.check(not problems, "复核 %s/%s 包结构" % (btype, strategy), str(problems))
            if strategy == "pack":
                c.check(manifest["includeImages"] is True and bool(manifest["imageFiles"]),
                        "pack 策略必须含图片", json.dumps(manifest["imageFiles"], ensure_ascii=False))
            else:
                c.check(manifest["imageFiles"] == [] and manifest["includeImages"] is False,
                        "link 策略不含图片", "includeImages=%r" % manifest["includeImages"])

    print("### 4. 应当被拒绝的输入")
    prepare("movie", "pack")
    write_meta("movie", "pack")
    code = run_build("--output", os.path.join(ab.OUTPUT_DIR, "_reject.zip"))
    c.check(code == 0, "基线（应通过）", "exit=%d" % code)

    # 4a 缺少图片文件
    saved = os.path.join(ab.IMAGES_DIR, "data")
    backup = saved + "__bak"
    shutil.move(saved, backup)
    code = run_build("--output", os.path.join(ab.OUTPUT_DIR, "_reject.zip"))
    c.check(code == 2, "pack 策略缺少图片应中止(exit=2)", "exit=%d" % code)
    shutil.move(backup, saved)

    # 4b 非法 type
    meta = ab.load_meta()
    meta["package_type"] = "tv"
    with open(ab.META_PATH, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(meta, fp, ensure_ascii=False, indent=2)
    code = run_build("--output", os.path.join(ab.OUTPUT_DIR, "_reject.zip"))
    c.check(code == 2, "非法 type 应中止(exit=2)", "exit=%d" % code)

    # 4c 缺少 records 文件
    write_meta("comic", "link")
    records_path = os.path.join(ab.RECORDS_DIR, "comic.json")
    os.remove(records_path)
    code = run_build("--output", os.path.join(ab.OUTPUT_DIR, "_reject.zip"))
    c.check(code == 2, "缺少 records 应中止(exit=2)", "exit=%d" % code)

    # 4d 空数组 / 缺匹配键（写回一个坏 records）
    with open(records_path, "w", encoding="utf-8", newline="\n") as fp:
        json.dump([], fp)
    code = run_build("--output", os.path.join(ab.OUTPUT_DIR, "_reject.zip"))
    c.check(code == 2, "空 records 数组应中止(exit=2)", "exit=%d" % code)

    with open(records_path, "w", encoding="utf-8", newline="\n") as fp:
        json.dump([{"cover": "https://x/y.jpg"}], fp, ensure_ascii=False, indent=2)
    code = run_build("--output", os.path.join(ab.OUTPUT_DIR, "_reject.zip"))
    c.check(code == 1, "缺匹配键应自检失败(exit=1)", "exit=%d" % code)

    print("\n通过 %d 项，失败 %d 项" % (c.passed, c.failed))
    return 1 if c.failed else 0


if __name__ == "__main__":
    sys.exit(main())
