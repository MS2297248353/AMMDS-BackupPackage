#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AMMDS 标准备份包 生成 / 自检 脚本（无第三方依赖，Python 3.8+）

用途：
  1) build_backup(...)  : 按《AMMDS 备份包生成规范》产出可被 AMMDS 导入的 zip 备份包
  2) verify_backup(...) : 按 AMMDS 的「标准备份包校验」规则自检产出的包

命令行：
  python ammds_backup_pack.py demo   --out ./ai-backup-samples   # 生成 4 类样例包并自检
  python ammds_backup_pack.py verify ./ai-backup-samples/movie.zip

本脚本与 AMMDS 导出实现（BackupZipUtils / BackupManifest）保持一致：
相同 records + 相同 images 会得到与 AMMDS 自身导出完全同构的包。
"""

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime

FORMAT = "ammds-backup"
FORMAT_VERSION = 1
DEFAULT_APP_VERSION = "1.6.80"
ALLOWED_TYPES = ("movie", "actor", "comic", "novel")
MANIFEST_ENTRY = "manifest.json"
DATA_ENTRY = "data.json"
IMAGE_DIR = "images/"

# 各类型的平铺图片字段（与 AMMDS imageFieldsOf 一致）
FLAT_IMAGE_FIELDS = {
    "movie": ["poster", "fanart", "thumb", "extrafanart", "posterHd", "fanartHd", "thumbHd"],
    "actor": ["poster", "thumb"],
    "novel": ["cover", "backCover"],
    "comic": ["cover", "backCover"],
}


# --------------------------------------------------------------------------- #
# 生成
# --------------------------------------------------------------------------- #

def safe_key(raw, index):
    """条目 key 安全化：非 [a-zA-Z0-9_-] 替换为下划线，为空时用 item_<index>"""
    key = re.sub(r"[^a-zA-Z0-9_-]", "_", str(raw if raw is not None else ""))
    key = re.sub(r"^_+|_+$", "", key)
    return key or "item_%d" % index


def _ext(ref):
    ext = os.path.splitext(str(ref))[1].lower()
    return ext if ext else ".jpg"


def _slots(btype, record, key):
    """收集条目的 (包内路径, ref) 候选，规则与 AMMDS 扫描一致"""
    slots = []
    for field in FLAT_IMAGE_FIELDS.get(btype, []):
        value = record.get(field)
        if value is None:
            continue
        if isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, str) and item.strip():
                    slots.append(("images/%s/%s_%d%s" % (key, field, idx, _ext(item)), item))
        elif isinstance(value, str) and value.strip():
            slots.append(("images/%s/%s_0%s" % (key, field, _ext(value)), value))
    if btype == "comic":
        page_index = 0
        for chapter in record.get("chapters") or []:
            for page in (chapter or {}).get("pages") or []:
                ref = (page or {}).get("imagePath")
                page_index += 1
                if isinstance(ref, str) and ref.strip():
                    slots.append(("images/%s/pages/page%05d%s" % (key, page_index, _ext(ref)), ref))
    return slots


def entry_key(btype, record, index):
    """条目 key：漫画/小说用 isbn 优先，其次名称/标题"""
    for field in ("isbn", "title", "name", "originalTitle"):
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            return safe_key(value, index)
    return safe_key(None, index)


def build_backup(out_zip, btype, records, images=None, include_images=None,
                 app_version=DEFAULT_APP_VERSION):
    """
    生成标准备份包

    :param out_zip:        产物 zip 路径
    :param btype:          movie / actor / comic / novel
    :param records:        data.json 的条目数组（list[dict]）
    :param images:         {ref: 本地图片文件路径}；ref 必须与 records 中图片字段的值完全一致
    :param include_images: None=按 images 是否非空自动判定；False=只保留引用不打包图片
    :param app_version:    manifest.appVersion
    :return: manifest 字典
    """
    if btype not in ALLOWED_TYPES:
        raise ValueError("不支持的 type: %s" % btype)
    if not isinstance(records, list):
        raise ValueError("records 必须是数组")
    images = images or {}
    if include_images is None:
        include_images = bool(images)

    # ref -> 包内路径（同一 ref 只打包一次，首次出现的字段/序号优先）
    ref_to_path = {}
    if include_images:
        for index, record in enumerate(records):
            key = entry_key(btype, record, index)
            for path, ref in _slots(btype, record, key):
                if ref in images and ref not in ref_to_path:
                    ref_to_path[ref] = path

    image_files = []
    for ref, path in ref_to_path.items():
        with open(images[ref], "rb") as fp:
            payload = fp.read()
        image_files.append({
            "ref": ref,
            "path": path,
            "sha256": hashlib.sha256(payload).hexdigest(),
        })

    manifest = {
        "format": FORMAT,
        "formatVersion": FORMAT_VERSION,
        "type": btype,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "appVersion": app_version,
        "includeImages": bool(image_files),
        "count": len(records),
        "imageFiles": image_files,
    }

    parent = os.path.dirname(os.path.abspath(out_zip))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_ENTRY, json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr(DATA_ENTRY, json.dumps(records, ensure_ascii=False, indent=2))
        for ref, path in ref_to_path.items():
            zf.write(images[ref], path)
    return manifest


# --------------------------------------------------------------------------- #
# 自检（等价于 AMMDS 的 BackupValidator：结构 + 清单，不校验图片摘要内容）
# --------------------------------------------------------------------------- #

def _data_image_refs(btype, records):
    refs = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        for field in set(FLAT_IMAGE_FIELDS.get(btype, [])) | {"poster", "fanart", "thumb",
                                                             "extrafanart", "cover", "backCover"}:
            value = record.get(field)
            if isinstance(value, str) and value.strip():
                refs.add(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip():
                        refs.add(item)
        for chapter in record.get("chapters") or []:
            for page in (chapter or {}).get("pages") or []:
                ref = (page or {}).get("imagePath")
                if isinstance(ref, str) and ref.strip():
                    refs.add(ref)
    return refs


def verify_backup(zip_path):
    """
    自检备份包，返回 (problems, warnings)；problems 非空则 AMMDS 会拒绝导入
    """
    problems, warnings = [], []
    with zipfile.ZipFile(zip_path) as zf:
        entries = [n for n in zf.namelist() if not n.endswith("/")]
        for name in entries:
            if not name:
                problems.append("存在空条目名")
            if name.startswith("/"):
                problems.append("条目路径以 / 开头: %s" % name)
            if "\\" in name:
                problems.append("条目路径包含 '\\': %s" % name)
            if ":" in name:
                problems.append("条目路径包含 ':': %s" % name)
            if ".." in name.split("/"):
                problems.append("条目路径包含 '..': %s" % name)
        if MANIFEST_ENTRY not in entries:
            problems.append("缺少必需文件 %s" % MANIFEST_ENTRY)
        if DATA_ENTRY not in entries:
            problems.append("缺少必需文件 %s" % DATA_ENTRY)
        if problems:
            return problems, warnings

        try:
            manifest = json.loads(zf.read(MANIFEST_ENTRY).decode("utf-8"))
            records = json.loads(zf.read(DATA_ENTRY).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return ["manifest.json/data.json 解析失败: %s" % exc], warnings

        btype = manifest.get("type")
        if manifest.get("format") != FORMAT:
            problems.append("format 必须为 %s，实际 %r" % (FORMAT, manifest.get("format")))
        version = manifest.get("formatVersion")
        if not isinstance(version, int) or version < 1 or version > FORMAT_VERSION:
            problems.append("formatVersion 非法：%r（当前支持 1）" % version)
        if btype not in ALLOWED_TYPES:
            problems.append("type 非法：%r（允许 %s）" % (btype, "/".join(ALLOWED_TYPES)))
        if not isinstance(records, list):
            problems.append("data.json 必须是 JSON 数组")
            records = []
        if manifest.get("count") != len(records):
            problems.append("count=%r 与 data.json 条目数 %d 不一致"
                            % (manifest.get("count"), len(records)))
        if not manifest.get("generatedAt"):
            warnings.append("缺少 generatedAt")
        if not manifest.get("appVersion"):
            warnings.append("缺少 appVersion")

        image_files = manifest.get("imageFiles")
        if not isinstance(image_files, list):
            problems.append("imageFiles 必须是数组")
            image_files = []
        include_images = bool(manifest.get("includeImages"))
        data_refs = _data_image_refs(btype, records) if btype in ALLOWED_TYPES else set()
        registered = set()
        for item in image_files:
            ref = (item or {}).get("ref")
            path = (item or {}).get("path")
            if not ref:
                problems.append("imageFiles 存在空 ref")
            elif ref not in data_refs:
                warnings.append("imageFiles.ref 未出现在 data.json 图片字段中: %s" % ref)
            if not path:
                problems.append("imageFiles 存在空 path")
                continue
            if not path.startswith(IMAGE_DIR):
                problems.append("图片路径必须位于 %s 下: %s" % (IMAGE_DIR, path))
            if path not in entries:
                problems.append("图片清单登记的包内文件不存在: %s" % path)
            if path in registered:
                warnings.append("imageFiles 存在重复 path: %s" % path)
            registered.add(path)

        packed = {n for n in entries if n.startswith(IMAGE_DIR)}
        if include_images and not image_files and packed:
            problems.append("includeImages=true 但 imageFiles 为空，包内却存在 images/ 文件")
        if include_images and not image_files and not packed:
            warnings.append("includeImages=true 但包内没有任何图片")
        if not include_images and image_files:
            warnings.append("includeImages=false 但 imageFiles 不为空")
        if not include_images and packed:
            warnings.append("includeImages=false 但包内存在 images/ 文件")
        for name in packed:
            if name not in registered:
                warnings.append("包内图片未登记在 imageFiles 中: %s" % name)
        for name in entries:
            if name in (MANIFEST_ENTRY, DATA_ENTRY) or name.startswith(IMAGE_DIR):
                continue
            warnings.append("包内存在未识别的条目: %s" % name)
    return problems, warnings


# --------------------------------------------------------------------------- #
# 样例（用于自测 / 联调）
# --------------------------------------------------------------------------- #

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082")


def _write_png(path):
    with open(path, "wb") as fp:
        fp.write(PNG_1PX)


def demo(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    img_dir = os.path.join(out_dir, "src-images")
    os.makedirs(img_dir, exist_ok=True)

    samples = {}

    # 影视
    poster = os.path.join(img_dir, "movie-poster.png")
    _write_png(poster)
    samples["movie"] = (
        [{
            "originalTitle": "AI-001 Sample Movie",
            "titleCn": "示例影片",
            "plot": "由 AI 抓取并规范化生成的简介",
            "rating": 8.5,
            "premiered": "2026-08-01",
            "runtime": 120,
            "poster": ["data/images/media/2026/08/ai-001-poster.png"],
            "genre": ["剧情"],
            "uniqueid": ["AI-001"],
            "actors": [{"name": "示例演员", "role": "女优"}],
            "dataSource": "user",
        }],
        {"data/images/media/2026/08/ai-001-poster.png": poster},
    )

    # 演员
    actor_poster = os.path.join(img_dir, "actor-poster.png")
    _write_png(actor_poster)
    samples["actor"] = (
        [{
            "name": "示例演员",
            "aliases": ["示例"],
            "gender": "female",
            "heightCm": 160,
            "bloodType": "A",
            "poster": "data/images/actor/2026/08/ai-actor.png",
            "tag": ["AI生成"],
            "dataSource": "user",
        }],
        {"data/images/actor/2026/08/ai-actor.png": actor_poster},
    )

    # 漫画（相册 + 章节 + 章节页）
    cover = os.path.join(img_dir, "comic-cover.png")
    page1 = os.path.join(img_dir, "comic-page1.png")
    page2 = os.path.join(img_dir, "comic-page2.png")
    for f in (cover, page1, page2):
        _write_png(f)
    samples["comic"] = (
        [{
            "title": "示例漫画",
            "type": "comic",
            "isbn": "9780000000001",
            "cover": "data/images/gallery/comic/cover/ai-comic-cover.png",
            "description": "由 AI 抓取生成的漫画",
            "season": 1,
            "fullChapter": False,
            "language": "zh",
            "format": "Digital",
            "manga": "Yes",
            "ageRating": "Adults Only 18+",
            "writer": "示例作者",
            "chapters": [{
                "title": "第 1 话",
                "episode": 1,
                "pages": [
                    {"imagePath": "data/images/gallery/comic/story/ai-comic-001.png", "sequence": 1},
                    {"imagePath": "data/images/gallery/comic/story/ai-comic-002.png", "sequence": 2},
                ],
            }],
        }],
        {
            "data/images/gallery/comic/cover/ai-comic-cover.png": cover,
            "data/images/gallery/comic/story/ai-comic-001.png": page1,
            "data/images/gallery/comic/story/ai-comic-002.png": page2,
        },
    )

    # 小说
    novel_cover = os.path.join(img_dir, "novel-cover.png")
    _write_png(novel_cover)
    samples["novel"] = (
        [{
            "title": "示例小说",
            "author": "示例作者",
            "genre": "玄幻",
            "description": "由 AI 抓取生成的小说",
            "language": "zh",
            "status": "serial",
            "cover": "data/images/novel/cover/ai-novel-cover.png",
            "chapters": [
                {"title": "第一章 起始", "content": "第一段正文。\n第二段正文。", "sort": 1},
                {"title": "第二章 发展", "content": "第三章之前的正文。", "sort": 2},
            ],
        }],
        {"data/images/novel/cover/ai-novel-cover.png": novel_cover},
    )

    results = []
    for btype, (records, images) in samples.items():
        out_zip = os.path.join(out_dir, "%s.zip" % btype)
        manifest = build_backup(out_zip, btype, records, images)
        problems, warnings = verify_backup(out_zip)
        results.append((btype, out_zip, manifest, problems, warnings))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="AMMDS 标准备份包 生成/自检")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_demo = sub.add_parser("demo", help="生成 4 类样例包并自检")
    p_demo.add_argument("--out", default="./ai-backup-samples")

    p_verify = sub.add_parser("verify", help="自检已有备份包")
    p_verify.add_argument("zip_path")

    args = parser.parse_args(argv)
    if args.cmd == "demo":
        failed = False
        for btype, out_zip, manifest, problems, warnings in demo(args.out):
            print("[%s] %s  条目=%d 图片=%d" % (btype, out_zip, manifest["count"],
                                               len(manifest["imageFiles"])))
            for w in warnings:
                print("    WARN  %s" % w)
            for p in problems:
                failed = True
                print("    ERROR %s" % p)
        print("自检%s" % ("失败" if failed else "通过"))
        return 1 if failed else 0

    problems, warnings = verify_backup(args.zip_path)
    for w in warnings:
        print("WARN  %s" % w)
    for p in problems:
        print("ERROR %s" % p)
    print("校验%s：%s" % ("通过" if not problems else "未通过", args.zip_path))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
