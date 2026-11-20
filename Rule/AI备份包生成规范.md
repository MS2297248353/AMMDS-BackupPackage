# AMMDS 备份包生成规范（AI 生成器专用）

> **读者**：AI 编码助手（或数据工程师）。
> **场景**：你被要求抓取某个站点/接口的数据，并产出一个能被 **AMMDS** 直接导入的备份包。
> **输入**：本规范 + 用户给出的抓取目标（站点地址 / 接口 / 数据类型 / 数量范围 / 是否需要图片）。
> **唯一交付物**：一个 zip 备份包（建议命名 `ammds-backup-<type>-<yyyyMMddHHmmss>.zip`）。
> **验收**：本包必须①通过第 11 节自检脚本（0 ERROR）②被 AMMDS「数据导入 → 解析预览」判定为**校验通过**③导入结果 `failed=0`。

---

## 1. 先看这个：十条铁律

| # | 铁律 |
| --- | --- |
| 1 | zip **根目录**必须有 `manifest.json` 与 `data.json`（二者缺一，整包被拒绝） |
| 2 | `manifest.format` 固定为 `"ammds-backup"`；`manifest.formatVersion` 固定为 `1` |
| 3 | `manifest.type` ∈ `movie` / `actor` / `comic` / `novel`，且必须与内容结构匹配（**zip 包以 manifest.type 为准**） |
| 4 | `manifest.count` 必须**严格等于** `data.json` 数组的元素个数 |
| 5 | `images/` 下的每个文件都必须在 `manifest.imageFiles` 中登记 `{ref, path, sha256}` |
| 6 | `imageFiles[].path` 必须以 `images/` 开头，且与 zip 内条目名**逐字符一致** |
| 7 | `data.json` 中图片字段的值必须与 `imageFiles[].ref` **完全一致**（区分大小写） |
| 8 | `http(s)://` 外链图片**只**写在 `data.json` 里，**不要**登记进 `imageFiles` |
| 9 | 条目名不得为空、不得以 `/` 开头，不得包含 `\`、`:` 或 `..` 路径段 |
| 10 | 日期用 `yyyy-MM-dd`；枚举只写 code（禁止中文名）；**整数字段必须写整数**（写 `120.0` 会导致该条目导入失败） |

---

## 2. 产物结构

```
ammds-backup-movie-20260911153000.zip
├── manifest.json                 # 必需，根目录
├── data.json                     # 必需，根目录，JSON 数组
└── images/                       # 可选：仅当有图片要打包时存在
    └── <条目key>/                # 每个条目一个目录（key 由标识安全化，见 8.3）
        ├── poster_0.jpg          # 平铺图片字段：<字段名>_<序号>.<ext>
        ├── fanart_0.jpg
        └── pages/                # 仅漫画：章节页图片
            ├── page00001.jpg
            └── page00002.jpg
```

- 未打包任何图片时：**不要**创建 `images/` 目录，`manifest.includeImages` 写 `false`、`imageFiles` 写 `[]`。
- zip 条目名请使用 UTF-8 编码；推荐 `imageFiles[].path` 全部使用 ASCII（避免跨平台编码差异导致第 6 条铁律不满足）。
- 允许存在目录条目（以 `/` 结尾），但不要放 `manifest.json` / `data.json` / `images/**` 之外的"未识别条目"（只会产生提示，但没必要）。

---

## 3. manifest.json 规范

| 字段 | 类型 | 必填 | 取值 / 说明 |
| --- | --- | --- | --- |
| `format` | string | 是 | 固定 `"ammds-backup"` |
| `formatVersion` | int | 是 | 固定 `1` |
| `type` | string | 是 | `"movie"` / `"actor"` / `"comic"` / `"novel"` |
| `generatedAt` | string | 是 | ISO-8601 带时区，如 `"2026-09-11T15:30:00+08:00"` |
| `appVersion` | string | 是 | 目标 AMMDS 版本号，如 `"1.6.80"`（未知时用用户提供的版本，或 `"1.6.80"`） |
| `includeImages` | boolean | 是 | 是否打包图片；必须与是否存在 `images/` 文件一致 |
| `count` | int | 是 | `data.json` 数组长度（必须一致） |
| `imageFiles` | array | 是 | 图片映射数组，无图片时 `[]` |

`imageFiles[]` 元素：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ref` | string | 图片引用键，必须与 `data.json` 里该图片字段的值**逐字符相同**；约定以 `data` 开头 |
| `path` | string | zip 内相对路径，必须以 `images/` 开头，且 zip 中确实存在该条目 |
| `sha256` | string | 该文件字节的 SHA-256（小写十六进制）。AMMDS 导入时不强制校验，但必须写正确值 |

完整示例：

```json
{
  "format": "ammds-backup",
  "formatVersion": 1,
  "type": "movie",
  "generatedAt": "2026-09-11T15:30:00+08:00",
  "appVersion": "1.6.80",
  "includeImages": true,
  "count": 2,
  "imageFiles": [
    {
      "ref": "data/images/media/2026/09/ai-001-poster.jpg",
      "path": "images/AI-001/poster_0.jpg",
      "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    }
  ]
}
```

---

## 4. data.json 通用约定

1. **顶层必须是 JSON 数组**（`[ {...}, {...} ]`）。对象形式 `{"type":..,"items":[..]}` 仅用于单文件兼容模式，zip 包内请勿使用。
2. 字段名使用**驼峰**（与下表一致），例如 `originalTitle`、`imagePath`、`fullChapter`。
3. 取不到的字段**直接省略**（或写 `null`）；不要写 `"未知"`、`"-"`、`"N/A"` 之类占位符污染数据。
4. 导入端**忽略未知字段**（多写字段不会报错），但错拼的字段名等于"数据丢失"，请严格按表书写。
5. **数值类型严格**：
   - 整数型字段（`runtime`、`pageCount`、`resolutionWidth`、`season`、`episode`、`sequence`、`sort`、`fileSizeByte` 等）必须写**整数**：`120` ✅ / `120.0` ❌（会解析失败，条目导入失败）。
   - 浮点字段（`rating`、`score`、`heightCm`、`communityRating` 等）写数字：`8.5` ✅。
6. **日期**统一 `yyyy-MM-dd` 字符串（如 `"2026-08-01"`）；格式非法会被置空（不报错，但数据丢失）。
7. **枚举**只写 code（见第 7 节），非法值会被容错回退或置空。
8. **数组 vs 单值**（最容易写错，务必对照）：

| 字段 | 归属 | 形态 |
| --- | --- | --- |
| `poster` | movie | **数组** `["data/...jpg"]` |
| `poster` | actor | **单值字符串** `"data/...jpg"` |
| `thumb` | actor | **数组** |
| `cover` / `backCover` | comic / novel | **单值字符串** |
| `posterHd` / `fanartHd` / `thumbHd` | movie | **单值字符串** |

   > 容错说明：导入端允许"单值当数组"（`"poster": "x.jpg"` 可被接受），但请一律按上表书写。
9. 不要写 `id`、`createdTime`、`updatedTime`、`version`：导入时一律忽略，主键由 AMMDS 重新生成。

---

## 5. 四种类型的 data.json 字段表

字段类型标记：`S`=字符串、`S[]`=字符串数组、`I`=整数、`N`=数字、`B`=布尔、`O[]`=对象数组。
**必填**列：`★`=不写会导致该条目导入失败或无法匹配；`·`=可选。

### 5.1 `movie`（影视）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `uniqueid` | S[] | ★ | 识别码/番号列表，**导入匹配依据**（至少写一个；大小写不敏感匹配） |
| `originalTitle` | S | ★ | 原始标题（识别码未命中时 `merge` 策略按标题匹配） |
| `titleCn` | S | · | 中文标题 |
| `plot` / `plotCn` | S | · | 简介 / 中文简介 |
| `tagline` | S | · | 标语 |
| `outline` | S | · | 大纲 |
| `rating` | N | · | 评分（10 分制） |
| `premiered` | S | · | 首映日期 `yyyy-MM-dd` |
| `runtime` | I | · | 时长（分钟） |
| `mpaa` | S | · | 分级，默认 `R18+` |
| `language` / `country` | S | · | 语言 / 国家 |
| `mosaic` | S | · | `有码` / `无码` |
| `genre` | S[] | · | 类型列表 |
| `tag` | S[] | · | 标签列表 |
| `studio` | S[] | · | 制作公司 |
| `issueStudio` | S[] | · | 发行公司 |
| `director` | S[] | · | 导演 |
| `actors` | O[] | · | 演员列表 `[{"name":"姓名","role":"女优"}]`（`role` 缺省视为 `女优`） |
| `sets` | O[] | · | 系列 `[{"name":"系列名","overview":"描述"}]` |
| `sourceLinks` | O[] | · | 影视源 `[{"platform":"站点","link":"https://..."}]` |
| `extend` | O[] | · | 扩展键值 `[{"extendKey":"k","extendValue":"v"}]` |
| `platform` | O[] | · | 平台信息 `[{"platform":"站点","link":"https://..."}]` |
| `magnet` | O[] | · | 磁力 `[{"name":"n","link":"magnet:?xt=...","size":1073741824,"hash":"...","date":"2026-08-01"}]` |
| `subtitle` | O[] | · | 字幕 `[{"sid":"..","name":"..","link":"..","language":"zh","extension":"srt","duration":0,"path":""}]` |
| `trailer` | S | · | 预告片地址 |
| `dataSource` | S | · | 数据源 code（见 7.1） |
| `shared` | B | · | 共享状态，默认 `false` |
| `pHash` / `osHash` | S[] | · | 指纹列表 |
| `poster` | S[] | · | 封面图（**数组**） |
| `fanart` | S[] | · | 背景图（数组） |
| `thumb` | S[] | · | 缩略图（数组） |
| `extrafanart` | S[] | · | 剧照（数组） |
| `posterHd` / `fanartHd` / `thumbHd` | S | · | 高清图（**单值**） |
| `mediaDir` / `originalFilePath` / `arrangeFilePath` / `fileName` | S | · | 文件信息（抓取场景通常不写） |
| `filePath` | S[] | · | 文件路径列表 |
| `audioCodec` / `videoCodec` | S | · | 编码信息 |
| `resolutionWidth` / `resolutionHeight` | I | · | 分辨率 |
| `fileSizeByte` | I | · | 文件大小（字节） |

### 5.2 `actor`（演员）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | S | ★ | 姓名（艺名），**导入匹配依据**，不可为空 |
| `aliases` | S[] | · | 别名 |
| `gender` | S | · | `male` / `female` / `shemale` |
| `heightCm` / `weightKg` | N | · | 身高(cm) / 体重(kg) |
| `birthDate` | S | · | 出生日期 `yyyy-MM-dd` |
| `nationality` | S | · | 国籍 |
| `bloodType` | S | · | `A`/`B`/`AB`/`O`/`RH+`/`RH-` |
| `bustChestCm` / `waistCm` / `hipsCm` | N | · | 三围(cm) |
| `cupSize` | S | · | 罩杯（单个字符 A-J） |
| `penisCm` | N | · | 长度(cm) |
| `debutDate` | S | · | 出道日期 `yyyy-MM-dd` |
| `agency` | S[] | · | 经纪公司 |
| `tag` / `style` / `specialFeatures` | S[] | · | 标签 / 风格 / 特征 |
| `score` | N | · | 评分（10 分制） |
| `socialLinks` | O[] | · | `[{"platform":"Twitter","link":"https://..."}]` |
| `retired` / `deceased` | B | · | 是否退役 / 是否亡故 |
| `poster` | S | · | 大头照（**单值**） |
| `thumb` | S[] | · | 海报列表（数组） |
| `bio` | S | · | 简介 |
| `extend` / `platform` | O[] | · | 同影视（`extendKey/extendValue`、`platform/link`） |
| `dataSource` | S | · | 数据源 code |
| `shared` | B | · | 共享状态 |

### 5.3 `comic`（漫画 / 相册）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | S | ★ | 相册名称，不可为空 |
| `isbn` | S | · | **导入匹配优先依据**（有则优先按 ISBN 匹配，否则按名称忽略大小写匹配） |
| `type` | S | · | `comic`（默认）/ `album` |
| `cover` / `backCover` | S | · | 封面 / 封底（**单值**） |
| `description` / `notes` / `web` | S | · | 描述 / 备注 / 链接 |
| `season` | I | · | 季，默认 `1` |
| `fullChapter` | B | · | 全集模式（此时只应有一个章节），默认 `false` |
| `arrange` | B | · | 是否已整理，默认 `false` |
| `publishDate` | S | · | 出版日期 `yyyy-MM-dd` |
| `publisher` / `imprint` / `series` | S | · | 出版商 / 印刷商 / 系列 |
| `genre` | S | · | 分类 |
| `tags` | S[] | · | 标签 |
| `language` | S | · | 语言，默认 `zh` |
| `format` | S | · | `Digital`（默认）/ `Print` |
| `blackAndWhite` | B | · | 是否黑白，默认 `false` |
| `manga` | S | · | `Yes`（默认）/ `No` / `Unknown` / `YesAndRightToLeft` |
| `characters` / `teams` / `locations` | S[] | · | 角色 / 团队 / 地点 |
| `ageRating` | S | · | 年龄分级 code（见 7.4），默认 `Adults Only 18+` |
| `communityRating` | N | · | 社区评分 0.0–5.0 |
| `writer` `penciller` `inker` `colorist` `letterer` `coverArtist` `editor` `translator` | S | · | 创作者信息（抓不到可只写 `writer`） |
| `chapters` | O[] | ★ | 章节数组，结构见下 |

`chapters[]`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `title` | S | 章节名（为空时导入端按「第 N 话」补齐） |
| `episode` | I | 章节序号（为空或非法时按顺序补齐） |
| `description` | S | 章节描述 |
| `pages` | O[] | 章节页数组（**完整迁移必须写**） |

`chapters[].pages[]`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `imagePath` | S | 页图片引用（打包时用 `data/...` 键；外链时用 `http(s)://`） |
| `sequence` | I | 页序（仅参考，导入端按数组顺序重建 1..N） |

> 相册/章节的 `pageCount`、`episodeCount` 是派生字段，**不要写**（写了也会被重算）。

### 5.4 `novel`（小说）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | S | ★ | 书名，不可为空（为空该条目被跳过并计入失败） |
| `isbn` | S | · | 与标题共同作为导入匹配依据 |
| `subtitle` / `author` | S | · | 副标题 / 作者 |
| `genre` | S | · | 类型（单值） |
| `tags` / `category` | S[] | · | 标签 / 分类 |
| `rating` | N | · | 评分 0–10 |
| `description` | S | · | 简介 |
| `publisher` / `publishYear` | S | · | 出版社 / 出版年份 |
| `language` | S | · | 语言，默认 `zh` |
| `pageCount` | I | · | 页数 |
| `series` | S | · | 系列 |
| `cover` / `backCover` | S | · | 封面 / 封底（**单值**） |
| `status` | S | · | 状态 code（见 7.5），默认 `continue` |
| `chapters` | O[] | ★ | 章节数组：`[{"title":"第一章","content":"正文","sort":1}]` |

> `chapters[].title` 为空的章节会被跳过；`content` 可为纯文本或 HTML 片段（换行用 `\n`，不要写 `\r\n` 混排）。

---

## 6. 枚举取值（只写 code）

| 字段 | 归属 | 合法取值 |
| --- | --- | --- |
| `dataSource` | movie / actor | `official` `metatube` `theporndb` `stashbox` `fanza_dmm` `r18dev` `thejavdb` `plugin` `user` `local`（抓取场景推荐 `user`） |
| `gender` | actor | `male` `female` `shemale` |
| `bloodType` | actor | `A` `B` `AB` `O` `RH+` `RH-` |
| `type` | comic | `comic` `album` |
| `ageRating` | comic | `Unknown` `Adults Only 18+` `Early Childhood` `Everyone` `Everyone 10+` `G` `Kids to Adults` `M` `MA15+` `Mature 17+` `PG` `R18+` `Rating Pending` `Teen` `X18+`（含空格，原样写） |
| `status` | novel | `finish` `serial` `draft` `continue` `writing` |

非法枚举不会中断导入，但会被回退为默认值或置空，导致数据不准。

---

## 7. 图片处理规范

### 7.1 两种策略，二选一（可混用）

| 策略 | `data.json` 字段值 | 是否进 `imageFiles` | 是否在 `images/` 内 | 适用 |
| --- | --- | --- | --- | --- |
| **A. 外链**（不打包） | 完整 `http(s)://...` URL | ❌ 不要登记 | ❌ | 源站图片可长期访问、或用户不要求离线图片 |
| **B. 打包**（推荐做封面/海报；漫画完整迁移必须用） | 以 `data` 开头的引用键，如 `data/images/media/2026/09/ai-001-poster.jpg` | ✅ 必须登记 | ✅ 必须存在 | 需要离线可用 / 目标机器无法访问源站 |

- 策略 B 中，`ref` 只是"键"，**不需要**在生成机器上真实存在该路径；AMMDS 导入时会按 `imageFiles` 把包内文件落盘到 `data/images/...` 并把字段值**回写**为新路径。
- 但 `ref` 的**扩展名会决定落盘文件扩展名**，所以请让 `ref` 以正确的图片扩展名结尾（`.jpg` / `.png` / `.webp` / `.gif`）。
- 策略 A 的 URL 请保留原始大小写与查询参数（`%20` 等），不要二次编码。

### 7.2 打包细节

1. 下载图片后先确认是**真实图片字节**（AMMDS 不校验图片内容，但错误内容会导致前端显示破图）。
2. 同一 `ref` 在多个字段/多条记录中重复出现时，**只打包一次**，`imageFiles` 只登记一条。
3. `path` 生成规则（与 AMMDS 自身导出同构，推荐照抄）：

   | 场景 | `path` |
   | --- | --- |
   | 平铺字段（含数组） | `images/<条目key>/<字段名>_<序号从0开始>.<ext>`，如 `images/AI-001/poster_0.jpg` |
   | 漫画章节页 | `images/<条目key>/pages/page<5位序号从1开始>.<ext>`，如 `images/SAMPLE/pages/page00001.jpg` |

4. `<条目key>` 安全化规则：`标识.replaceAll("[^a-zA-Z0-9_-]", "_")` 后去掉首尾下划线，为空则用 `item_<下标>`。标识优先级：`isbn` → `title`（小说/漫画）／`name`（演员）／`originalTitle`（影视）。中文标题会整体变成下划线，此时建议改用 `isbn`/识别码 或 `item_<下标>`。
5. `sha256` = 该文件字节的 SHA-256 小写十六进制。
6. 漫画章节页图片数量可能很大：单个相册几百页、整库上万页属正常，请如实打包并在交付说明中提示包体积。

---

## 8. 从抓取结果到备份包的映射指引

### 8.1 影视（movie）

| 抓取到的信息 | 目标字段 |
| --- | --- |
| 番号 / 识别码（如 `ABC-123`） | `uniqueid: ["ABC-123"]`（**必须**） |
| 标题 | `originalTitle`（必写）、中文标题写 `titleCn` |
| 简介 / 大纲 | `plot` / `plotCn` / `outline` |
| 发行日期 / 首映日期 | `premiered`（转 `yyyy-MM-dd`） |
| 时长（分钟） | `runtime`（整数） |
| 评分 | `rating`（0–10 小数） |
| 制作商 / 发行商 | `studio: []` / `issueStudio: []` |
| 导演 | `director: []` |
| 演员（姓名 / 角色） | `actors: [{"name":"..","role":"女优"}]` |
| 类型 / 标签 | `genre: []` / `tag: []` |
| 系列 | `sets: [{"name":"..","overview":".."}]` |
| 封面 / 剧照 / 预告 | `poster: [ref]` / `extrafanart: [ref]` / `trailer` |
| 磁力链接 | `magnet: [{"name":"..","link":"magnet:?xt=..","size":<字节>,"hash":".."}]` |
| 字幕 | `subtitle: [{...}]` |
| 数据来源 | `dataSource: "user"`（自建抓取） |

### 8.2 演员（actor）

姓名 → `name`（**必须**）；别名 → `aliases`；性别 → `gender`；身高/体重/三围 → 对应 `*Cm`/`weightKg`；出生日期 → `birthDate`；国籍 → `nationality`；经纪公司 → `agency`；社交账号 → `socialLinks`；头像 → `poster`（**单值**）；图集 → `thumb`。

### 8.3 漫画（comic）

相册标题 → `title`（**必须**）；ISBN → `isbn`（有则强烈建议写，导入匹配优先）；作者 → `writer`；发布时间 → `publishDate`；分类/标签 → `genre`/`tags`；封面/封底 → `cover`/`backCover`；目录（章节列表）→ `chapters[].title` + `episode`；每话图片列表 → `chapters[].pages[].imagePath`（按阅读顺序）+ `sequence`。

> 若用户只要求"元数据"而不要求图片：`pages` 里仍建议保留 `imagePath`（可用源站外链），这样导入后仍能看到章节结构；若要**完整迁移**，必须按策略 B 打包全部页面图片。

### 8.4 小说（novel）

书名 → `title`（**必须**）；作者 → `author`；简介 → `description`；分类 → `genre`；标签 → `tags`；状态（完结/连载）→ `status`；封面 → `cover`；目录正文 → `chapters[{title,content,sort}]`（`sort` 从 1 递增）。

---

## 9. 参考实现（可直接复制运行）

以下脚本与 AMMDS 自身导出实现同构；`build_backup()` 负责产出，`verify_backup()` 负责自检（等价于 AMMDS 的「标准备份包校验」）。
（同目录 `ammds_backup_pack.py` 为同一脚本的可执行副本。）

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AMMDS 标准备份包 生成 / 自检（无第三方依赖，Python 3.8+）"""

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
MANIFEST_ENTRY, DATA_ENTRY, IMAGE_DIR = "manifest.json", "data.json", "images/"

FLAT_IMAGE_FIELDS = {
    "movie": ["poster", "fanart", "thumb", "extrafanart", "posterHd", "fanartHd", "thumbHd"],
    "actor": ["poster", "thumb"],
    "novel": ["cover", "backCover"],
    "comic": ["cover", "backCover"],
}


def safe_key(raw, index):
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
    for field in ("isbn", "title", "name", "originalTitle"):
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            return safe_key(value, index)
    return safe_key(None, index)


def build_backup(out_zip, btype, records, images=None, include_images=None,
                 app_version=DEFAULT_APP_VERSION):
    """
    :param out_zip:  产物 zip 路径
    :param btype:    movie / actor / comic / novel
    :param records:  data.json 条目数组（list[dict]）
    :param images:   {ref: 本地图片文件路径}，ref 必须与 records 中图片字段的值一致
    :param include_images: None=按 images 是否非空自动判定；False=只保留引用不打包
    """
    if btype not in ALLOWED_TYPES:
        raise ValueError("不支持的 type: %s" % btype)
    if not isinstance(records, list):
        raise ValueError("records 必须是数组")
    images = images or {}
    if include_images is None:
        include_images = bool(images)

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
        image_files.append({"ref": ref, "path": path,
                            "sha256": hashlib.sha256(payload).hexdigest()})

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


def _data_image_refs(records):
    refs = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        for field in ("poster", "fanart", "thumb", "extrafanart", "cover", "backCover"):
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
    """自检备份包，返回 (problems, warnings)；problems 非空 => AMMDS 会拒绝导入"""
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
        except Exception as exc:
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
        data_refs = _data_image_refs(records)
        registered = set()
        for item in image_files:
            ref, path = (item or {}).get("ref"), (item or {}).get("path")
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


def main(argv=None):
    parser = argparse.ArgumentParser(description="AMMDS 标准备份包 生成/自检")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_verify = sub.add_parser("verify", help="自检已有备份包")
    p_verify.add_argument("zip_path")
    args = parser.parse_args(argv)
    problems, warnings = verify_backup(args.zip_path)
    for w in warnings:
        print("WARN  %s" % w)
    for p in problems:
        print("ERROR %s" % p)
    print("校验%s：%s" % ("通过" if not problems else "未通过", args.zip_path))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
```

用法（在产出包的目录中执行）：

```bash
# 自检（必须执行，退出码 0 才算通过）
python ammds_backup_pack.py verify ./ammds-backup-movie-20260911153000.zip
```

---

## 10. 完整示例：一个最小可导入的影视包

`data.json`（2 条影视 + 1 张打包封面）：

```json
[
  {
    "uniqueid": ["AI-001"],
    "originalTitle": "AI-001 Sample Movie",
    "titleCn": "示例影片",
    "plot": "抓取并规范化生成的简介",
    "premiered": "2026-08-01",
    "runtime": 120,
    "rating": 8.5,
    "genre": ["剧情"],
    "studio": ["示例制作"],
    "director": ["示例导演"],
    "actors": [{"name": "示例演员", "role": "女优"}],
    "poster": ["data/images/media/2026/09/ai-001-poster.jpg"],
    "magnet": [{"name": "AI-001", "link": "magnet:?xt=urn:btih:EXAMPLE", "size": 1073741824}],
    "dataSource": "user"
  },
  {
    "uniqueid": ["AI-002"],
    "originalTitle": "AI-002 Another Movie",
    "poster": ["https://img.example.com/ai-002.jpg"],
    "dataSource": "user"
  }
]
```

`manifest.json`：

```json
{
  "format": "ammds-backup",
  "formatVersion": 1,
  "type": "movie",
  "generatedAt": "2026-09-11T15:30:00+08:00",
  "appVersion": "1.6.80",
  "includeImages": true,
  "count": 2,
  "imageFiles": [
    {
      "ref": "data/images/media/2026/09/ai-001-poster.jpg",
      "path": "images/AI-001/poster_0.jpg",
      "sha256": "<该文件字节的 SHA-256>"
    }
  ]
}
```

zip 内容：

```
manifest.json
data.json
images/AI-001/poster_0.jpg
```

要点：第 2 条只有外链封面 → 不登记 `imageFiles`、不进 `images/`；第 1 条封面走"打包"策略 → 字段值与 `ref` 完全一致。

漫画条目片段（章节页打包）：

```json
{
  "title": "示例漫画",
  "isbn": "9780000000001",
  "type": "comic",
  "cover": "data/images/gallery/comic/cover/ai-comic-cover.jpg",
  "chapters": [
    {
      "title": "第 1 话",
      "episode": 1,
      "pages": [
        {"imagePath": "data/images/gallery/comic/story/ai-001.jpg", "sequence": 1},
        {"imagePath": "data/images/gallery/comic/story/ai-002.jpg", "sequence": 2}
      ]
    }
  ]
}
```

对应 `imageFiles` 需登记 3 条：`images/9780000000001/cover_0.jpg`、`images/9780000000001/pages/page00001.jpg`、`images/9780000000001/pages/page00002.jpg`（条目 key 取 `isbn`）。

> 注意：纯中文标识经安全化后会变成空串并回退为 `item_<下标>`（如 `images/item_0/...`），因此**建议**为漫画/小说填写 `isbn`，或在标识中包含字母/数字，以便包内目录可读。

---

## 11. 会被拒绝 / 会导致条目失败的原因（自查清单）

### 11.1 整包被拒绝（AMMDS 直接拒绝导入，并给出错误清单）

| 现象 | 原因 |
| --- | --- |
| 缺少必需文件 `manifest.json` | 未写入根目录，或写成了嵌套目录 |
| 缺少必需文件 `data.json` | 同上 |
| `format` 不是 `ammds-backup` | 写错格式标识 |
| `formatVersion` 不支持 | 写了 `2` 或非整数 |
| `type` 不支持 | 写了 `tv` / `series` / 中文等 |
| 清单条目数与数据不一致 | `count` 与数组长度不同（最常见错误） |
| 图片清单登记的包内文件不存在 | `path` 拼错、大小写不一致、或忘了写入 zip |
| 图片路径不在 `images/` 下 | `path` 写成了 `pic/...` 或绝对路径 |
| 条目路径非法 | 以 `/` 开头、含 `\`、`:` 或 `..` |

### 11.2 条目级失败（包能导入，但该条计入 `failed`）

| 现象 | 原因 |
| --- | --- |
| 小说/漫画条目「缺少标题」 | `title` 为空 |
| 演员条目保存失败 | `name` 为空（数据库非空约束） |
| 数值字段解析异常 | 整数型字段写了小数（如 `"runtime": 120.0`） |
| 时间字段异常 | 日期不是 `yyyy-MM-dd`（会被置空） |

### 11.3 不报错但结果不对（最需要小心）

| 现象 | 原因 |
| --- | --- |
| 图片字段变成"原样保留的坏路径" | `data.json` 里的值与 `imageFiles[].ref` 不一致 → 该图不会被落盘回写 |
| 封面/剧照丢失 | 字段名拼错（未知字段被忽略），如把 movie 的 `poster` 写成 `posters`、漫画页写成 `imagePaths` |
| 一条图片都没打入包 | 勾了"同时导出图像文件"但 `imageFiles` 为空、或 `includeImages=false` |
| 前端显示破图 | 打包了非图片字节，或 ref 的扩展名与真实格式不符 |
| 导入后多出奇怪记录 | 把占位符（`"未知"`、`"-"`）写进了标题/姓名，占用了匹配键 |

---

## 12. 交付前检查表（逐项打勾）

1. [ ] `manifest.type` 与内容结构一致，且是四类之一
2. [ ] `manifest.format = "ammds-backup"`、`formatVersion = 1`
3. [ ] `manifest.count` 与 `data.json` 数组长度一致
4. [ ] `data.json` 顶层是数组；条目字段名与第 5 节表一致；整数字段是整数
5. [ ] 每条记录都有匹配键：movie 有 `uniqueid`、actor 有 `name`、comic/novel 有 `title`
6. [ ] 所有打包图片：字段值 == `imageFiles[].ref`，`path` 以 `images/` 开头且确实在 zip 内，`sha256` 正确
7. [ ] 所有外链图片：完整的 `http(s)://` URL，且**没有**出现在 `imageFiles`
8. [ ] 没有 `..` / `\` / `:` / 绝对路径条目
9. [ ] 已运行第 9 节自检脚本，输出"校验通过"（0 ERROR）
10. [ ] 交付说明中写明：类型、条目数、是否含图片及图片数量、包体积、建议的导入冲突策略

建议的导入操作（告知用户）：AMMDS → 系统 → 备份恢复 → 数据导入 → 上传该 zip → 「解析预览」应显示**校验通过** → 选择冲突策略（首次导入推荐「覆盖更新」或「跳过已存在」）→ 开始导入。

> 冲突策略参考：`skip` 命中即跳过；`overwrite` 覆盖已有记录（漫画会删除重建章节与页）；`merge` 字段级合并（影视/演员）、漫画补充缺失章节、小说整本重建。
