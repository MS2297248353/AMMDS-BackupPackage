# 示例：一份填好的 TODO.md

> 这是 `TODO.md` 的**参考填法**，演示「用户只需要回答 4 个问题」到底长什么样。
> 场景：把 `example.com` 的漫画列表前 3 页抓下来，做成离线可用的 `comic` 备份包。
> 照抄的时候把内容换成你自己的即可；填完对 AI 说「完成待办事项」。

---

## Q1 [必答] 数据从哪里来？

- 站点名称或域名：`example.com`
- 入口链接（列表页 / 搜索页 / 详情页 / API 地址，一行一个）：

```
https://example.com/comics?page=1
https://example.com/api/comics?page=2
```

- 抓取范围（三选一，只留你要的一行）：

```
全站前 3 页
```

`<可选>` 指定清单（按编号 / ISBN / 关键字 / URL，一行一个）：

```
9780000000001
示例漫画 第二季
```

---

## Q2 [必答] 要生成哪一种备份包？（四选一）

- [ ] `movie` —— 影视
- [ ] `actor` —— 演员
- [x] `comic` —— 漫画 / 相册
- [ ] `novel` —— 小说

---

## Q3 [必答] 图片怎么处理？

- [x] `pack` —— **打包进 zip**（离线可用；漫画 / 相册的完整迁移必须选它）
- [ ] `link` —— **只写外链**（包体积极小，但依赖源站图片长期可访问）
- [ ] `none` —— **完全不要图片**（只要文字数据）

`<可选>` 只要封面/海报、不要全套图？在这里说明：

```
封面打包，章节页图片也打包
```

---

## Q4 [必答] 已备好数据了吗？

- [x] `no` —— **没有**，请按 Q1 去抓取（AI 写抓取脚本 → 抓取 → 归一化 → 打包）
- [ ] `yes` —— **有**，不必联网抓取，直接由我提供的文件生成

---

## 其他（选填，不填就用默认值）

| 项目 | 填这里 | 默认值 |
| --- | --- | --- |
| 导入时冲突策略 | `overwrite` | `skip` |
| AMMDS 版本号 | `1.6.90` | `1.6.80` |
| 额外要求 | 只要 2024 年之后发布的；标题保留原文 | 无 |

---

## 这份 TODO 会被 AI 归一化成什么

AI 读完上面 4 个答案后，会把这些写进 `work/_meta.json`：

```json
{
  "package_type": "comic",
  "source_mode": "scrape",
  "image_strategy": "pack",
  "app_version": "1.6.90",
  "conflict_policy": "overwrite",
  "todo_snapshot": {
    "site": "example.com",
    "urls": ["https://example.com/comics?page=1", "https://example.com/api/comics?page=2"],
    "scope": "全站前 3 页",
    "target_list": ["9780000000001", "示例漫画 第二季"],
    "image_detail": "封面打包，章节页图片也打包",
    "extra": "只要 2024 年之后发布的；标题保留原文"
  }
}
```

然后 AI 自己决定剩下的一切，不需要再问你：

- `manifest.json` 的 `type=comic`、`formatVersion=1`、`count` 与数组长度对齐
- 漫画条目的字段映射：列表页标题 → `title`、详情页 ISBN → `isbn`、目录 → `chapters[]`、
  每话图片 → `chapters[].pages[].imagePath`
- 下载图片到 `work/images/<ref>`（目录树就是 `ref` 本身）
- 生成 `imageFiles` 的 `path` / `sha256`（由 `Rule/ammds_backup_pack.py` 自动完成）
- 跑自检直到 **0 ERROR**，写出 `output/deliver.md`

最终产物：

```
output/ammds-backup-comic-20260101120000.zip
output/deliver.md
```

导入：AMMDS → 系统 → 备份恢复 → 数据导入 → 选 zip → 「解析预览」应显示**校验通过** →
冲突策略选 `overwrite` → 开始导入 → 确认 `failed=0`。
