# AI 执行合同（收到「完成待办事项」后照此执行）

> **读者**：AI 编码助手。
> **触发**：用户（人类）说出类似「完成待办事项」「按 TODO 生成备份包」的话。
> **目标**：在本仓库内产出 **一个可被 AMMDS 导入的 zip 备份包**，并附带交付说明。
> **唯一权威规范**：`Rule/AI备份包生成规范.md`（格式细节一律以它为准，本文件只讲流程）。

---

## 0. 总原则

1. **用户只回答 4 个问题**（见 `TODO.md`）。其余一切——字段映射、目录结构、文件名、manifest、镜像命名、
   校验——都是**你的责任**，不要回头去问用户。
2. **但绝对不要编造数据**。抓不到就省略字段（规范第 4.3 节），不要写 `"未知"` / `"-"`；宁可条目少几条，
   也不要造假的番号、ISBN、简介、图片。
3. **唯一事实来源**：`work/records/<type>.json`（参与打包）+ `work/_meta.json`（打包参数）。
   `work/source/` 只作留痕，不参与打包。
4. 只用 Python 3.8+ 标准库（`Rule/ammds_backup_pack.py` 本身就是零依赖的）。不要给用户装第三方包。
5. **不要写入任何密钥**（Cookie / Token / 账号密码）到仓库任何文件；会话凭证只放内存或环境变量。
6. 尊重源站：默认 1 req/s 起步、遵守 robots、失败重试 3 次后跳过并记录，不要把站点打挂。

---

## 1. 第 1 步：预检（必做，先跑命令再动手）

```bash
python tools/auto_backup.py init        # 幂等；缺什么补什么，不覆盖已有文件
python tools/auto_backup.py todo        # 预检 TODO.md 是否填完整
python tools/auto_backup.py selftest    # 可选：确认框架自身可用（覆盖 work/ 与 output/，勿在交付前跑）
```

- `todo` 退出码 **0** → 继续第 2 步。
- `todo` 退出码 **非 0** → **停下来**，把打印出的 `ERROR` 行整理成一句人话，向用户提**不超过 3 个**问题，
  然后等回答。**不要**替用户猜 Q2/Q3/Q4，也不要用默认值偷偷跑过去。
  - 唯一例外：用户已经在对话里明确说过的答案，可直接采信并在 `_meta.todo_snapshot.extra` 里注明出处。

---

## 2. 第 2 步：把 TODO 归一化成 `work/_meta.json`

`TODO.md` 是给人写的，允许口语化；`work/_meta.json` 是给脚本读的，字段必须严格。你来翻译。

| `_meta.json` 字段 | 允许值 | 来自 |
| --- | --- | --- |
| `package_type` | `movie` / `actor` / `comic` / `novel` | Q2（**只能是这 4 个之一**） |
| `source_mode` | `scrape`（要联网抓）/ `existing`（用户已给数据） | Q4 |
| `image_strategy` | `pack` / `link` / `none` | Q3 |
| `app_version` | 字符串，如 `"1.6.80"` | 选填项，缺省 `1.6.80` |
| `conflict_policy` | `skip` / `overwrite` / `merge` | 选填项，缺省 `skip` |
| `todo_snapshot.site/urls/scope/target_list/image_detail/extra` | 字符串 / 数组 | Q1、Q3 备注、选填「额外要求」**原样抄录** |
| `source.input_paths` | 路径数组 | `existing` 模式：Q4 填的路径（存在性要验证） |
| `source.entry_url` / `fetched_at` / `pages` / `notes` | — | 抓取阶段回填 |
| `notes` | 字符串 | 你对本次产物的补充说明（会进交付说明第 6 节） |

写完后确认 `python tools/auto_backup.py todo` 仍然通过（它会顺带校验 `_meta.json`）。

**逐项判定规则（AI 自动识别，不要问用户）**

| 情况 | 你的处理 |
| --- | --- |
| Q3 勾 `pack` 但 `image_strategy` 想放宽（图太多/抓不到） | 只有用户说了「可以外链」才允许改成 `link`；否则如实报错让用户决定 |
| 用户给的路径不存在 / 是空目录 | 报错并让用户确认路径，不要跳过 |
| 用户填了多个站点 | 全部写进 `todo_snapshot.urls`，逐个抓取并在 `notes` 里说明来源占比 |
| 用户写了非法枚举（如 `tv`、`漫画`） | 不猜；回到第 1 步提问 |

---

## 3. 第 3 步：取数据 → `work/source/`

### 3.1 `scrape` 模式（Q4 = no）

1. **先侦察再写码**：抓 1 个列表页 + 1 个详情页，把真实结构（HTML 选择器 / JSON 字段路径）写进
   `work/source/<site>-notes.md`，再写正式脚本。不要凭空假设 DOM 结构。
2. 脚本放 `work/scripts/`，命名 `fetch_<site>.py`；要求：
   - 可重复执行（已抓过的条目跳过，靠 `work/source/` 里已有文件判断）；
   - 保存**原始响应**到 `work/source/<site>-<type>-<yyyyMMdd>.raw.json`（或 `.html`），
     便于之后复现与人工核对；
   - 打印进度（`已抓 12/50`）、写失败清单到 `work/source/<site>-failed.txt`。
3. 抓不到或站点改版时：记录实际报错与已抓到的数量，**不要为了凑数造假**。

### 3.2 `existing` 模式（Q4 = yes）

1. 把用户文件**复制**到 `work/source/`（不改原文件），路径记入 `_meta.source.input_paths`。
2. 先读文件确定真实结构（JSON / CSV / Excel / 数据库导出 / 目录树），据此写转换脚本。
3. 用户数据可能不完整或不合规：**按规范补齐必填**，补不了的按第 4 步报错，不要静默丢弃。

---

## 4. 第 4 步：归一化成 `work/records/<type>.json`（最关键的一步）

产物：`work/records/<package_type>.json`，**顶层 JSON 数组**，字段名严格按规范第 5 节。
逐条对照检查（这些是最常见的翻车点）：

- [ ] `movie` 每条必须有 `uniqueid`（数组）；`actor` 必须有 `name`；`comic` / `novel` 必须有 `title`。
- [ ] 整数型字段（`runtime` / `pageCount` / `season` / `episode` / `sequence` / `sort` / `fileSizeByte`
      / `resolutionWidth` / `resolutionHeight` / `duration`）写**整数**：`120` ✅，`120.0` ❌。
- [ ] 日期一律 `yyyy-MM-dd` 字符串；枚举只写 code（规范第 6 节）。
- [ ] 数组 vs 单值：`movie.poster` 是**数组**，`actor.poster` 是**单值**，`comic/novel.cover` 是**单值**，
      `movie.posterHd/fanartHd/thumbHd` 是**单值**。
- [ ] 不要写 `id` / `createdTime` / `updatedTime` / `version`（会被忽略）。
- [ ] `comic` 的 `chapters[].pages[].imagePath` 按阅读顺序排列；`novel` 的 `chapters[].sort` 从 1 递增。
- [ ] 不要写派生字段：`comic.pageCount` / `episodeCount`、`novel` 的计数（写了也会被重算）。

**图片引用规则（与第 5 步强相关，务必先定好）**

| `image_strategy` | `data.json` 里图片字段的值 | 是否下载到 `work/images/` |
| --- | --- | --- |
| `pack` | `data/images/...jpg` 形式**引用键**（以 `data` 开头，扩展名与真实格式一致） | ✅ 必须，路径 = `work/images/<ref>` |
| `link` | 完整 `http(s)://` URL（保留原大小写与查询参数） | ❌ 不下载 |
| `none` | 不写任何图片字段 | ❌ |

> `ref` 只是"键"，不需要在生成机器上真实存在该路径；但 AMMDS 落盘时会用 `ref` 的扩展名，
> 所以**扩展名必须正确**。中文字段值做 `ref` 没问题（会被放进 zip 条目名），但为避免跨平台编码差异，
> 建议 `ref` 只用 ASCII。

---

## 5. 第 5 步：打包 + 自检 + 交付说明

### 5.1 准备图片（仅 `pack` 策略）

在 `work/images/` 下**按 `ref` 原样建目录树**，把下载好的图片放进去：

```
work/images/data/images/media/2026/09/ai-001-poster.jpg   ← 对应 ref = data/images/media/2026/09/ai-001-poster.jpg
work/images/data/images/gallery/comic/story/ai-001.jpg
```

`build` 会自动把 `work/images/` 当成本地图片池，用 `ref` 作 key 交给 `build_backup()`，
因此规范第 1 节铁律 6、7（值与 `ref` 逐字符一致）**天然成立**，不需要你手工登记 `imageFiles`。

- 下载后校验确实是图片字节（magic number / `PIL` 不可用时看文件头），别把 403 HTML 当图片存下来。
- 同一 `ref` 只放一个文件；重复引用会自动只打包一次。
- `pack` 策略下若有引用在 `work/images/` 找不到文件，`build` 会直接中止并列出缺失清单——
  这时要么补下载，要么把该字段改成外链（需征得用户同意，因为那会破坏离线可用性）。

### 5.2 打包

```bash
python tools/auto_backup.py build            # 产出 output/ammds-backup-<type>-<时间戳>.zip
python tools/auto_backup.py build --strict   # 连 WARN 也要清零（更严）
```

`build` 会依次做：参数校验 → 读 records/images → `Rule/ammds_backup_pack.py` 产出 zip →
**结构自检**（规范第 9 节，等价 AMMDS「标准备份包校验」）→ **质量自查**（规范第 11 节）→
写 `output/deliver.md`。

- 退出码 `0` 且 `ERROR=0` → 交付。
- 退出码非 `0` → 按打印的 `ERROR` 逐条修，**修完必须重跑**，直到 0 ERROR。
  **绝对不要把未通过自检的包交给用户。**

### 5.3 交付

向用户回报（简洁版，明细在 `output/deliver.md`）：

- 包路径 + 包体积 + zip 的 SHA-256（前 8 位即可）
- `type` / 条目数 / 图片张数 / 自检 ERROR=0
- 导入路径：AMMDS → 系统 → 备份恢复 → 数据导入 → 选包 → 「解析预览」应显示**校验通过** →
  选冲突策略（默认 `skip`）→ 开始导入，确认 `failed=0`
- 遗留问题与风险（WARN、抓不到的条目、站点改动、需要用户复核的字段）

---

## 6. 停下来问用户的唯一情形

| 情形 | 你要问什么 |
| --- | --- |
| `todo` 预检报 ERROR | 只问缺的那几项（站点/入口、四选一类型、图片策略、有无现成数据） |
| 用户选的类型与数据明显不符 | 「你的数据看起来是漫画页，但 Q2 选了 movie，要改成 comic 吗？」 |
| 抓取需要登录 / 站点全站反爬 | 「需要你的 Cookie/账号才能继续，或者改为只处理你已导出的文件」 |
| `pack` 策略下有图片抓不到 | 「有 N 张图抓不到：①补下载 ②这些字段改外链 ③整包改成 link」 |
| 需要跑几万页漫画、体积可能上 GB | 「预计 X GB / Y 张图，确认继续吗？」 |

---

## 7. 反面清单（明确禁止）

- ❌ 用户没勾选就问也不问，自己编一个 `package_type`
- ❌ 往 `data.json` 里塞 `"未知"` / `"-"` / `"N/A"` 占位符
- ❌ 整数型字段写 `120.0`；日期写 `2026/08/01`；枚举写中文名
- ❌ 把 `http(s)://` 外链图片登记进 `imageFiles`，或把打包引用写成完整 URL
- ❌ 手工编辑 `manifest.json` 里的 `count` / `imageFiles`（应由脚本生成）
- ❌ 未经自检就把 zip 交付；或把 `--force` 当成"通过"
- ❌ 覆盖/删除 `Rule/` 下的文件；改动用户提供的原始数据文件
