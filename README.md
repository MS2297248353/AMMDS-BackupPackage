# AMMDS 备份包 · 模板仓库

把「我想把某站点的数据做成 AMMDS 能导入的备份包」这件事，压缩成 **填 4 个空 + 说一句话**。

你不需要懂 `manifest.json`、字段名、图片命名、zip 结构——这些都在 `Rule/` 里写死了，
由一个零依赖的 Python 脚本负责生成和自检。你只回答 4 个问题，然后让 AI 跑流程。

---

## 30 秒上手

1. 打开 `TODO.md`，回答 4 个问题（只有 4 个），保存。
   没主意可以先看 `docs/示例-TODO.md`（一份填好的参考）。
2. 对 AI 说一句：**「完成待办事项」**。
3. 等它交付。产物在 `output/`：
   - `ammds-backup-<type>-<时间戳>.zip` —— 备份包本体
   - `deliver.md` —— 交付说明（条目数、图片数、体积、SHA-256、导入步骤、遗留风险）

> 想自己手动跑一遍：
> ```bash
> python tools/auto_backup.py init     # 铺开 work/ 工作区（幂等）
> python tools/auto_backup.py todo     # 预检 TODO 是否填完整
> python tools/auto_backup.py build    # 打包 + 自检 + 写交付说明
> ```
> Windows 上也可以直接用 `run.cmd init` / `run.cmd todo` / `run.cmd build`。
> 只需要 Python 3.8+，**不需要装任何第三方库**。

> 想先确认这套框架本身没坏：`python tools/auto_backup.py selftest`
> （用内置 mock 数据跑通 4 种类型 × 2 种图片策略，44 项断言；会覆盖 `work/` 与 `output/`）。

---

## 你要回答的 4 个问题

| # | 问题 | 为什么必须问 |
| --- | --- | --- |
| Q1 | 数据从哪个站点/入口来？抓多少？ | 抓取目标无法从文件里推断 |
| Q2 | 要哪一种包？`movie` / `actor` / `comic` / `novel` 四选一 | 决定 `manifest.type` 与整套字段结构 |
| Q3 | 图片怎么处理？`pack`（打包）/ `link`（外链）/ `none`（不要图） | 决定包体积与是否需要下载图片 |
| Q4 | 你已经有数据文件了，还是要 AI 去抓？ | 决定走转换管线还是抓取管线 |

其余全部由 AI 自动识别：字段映射、目录结构、文件名安全化、`manifest.json`、`imageFiles` 登记、
`sha256`、图片扩展名、日期格式、枚举 code、条目匹配键……**都不用你操心**。

---

## 目录结构

```
AMMDS-BackupPackage/
├── TODO.md                  ← 【你填这里】4 个问题
├── AI.md                    ← 【AI 读这里】收到「完成待办事项」后的执行合同
├── README.md                ← 本文件
├── Rule/                    ← 规则区：只读，不要改
│   ├── AI备份包生成规范.md    ← 格式唯一权威（字段表 / 铁律 / 自检清单）
│   └── ammds_backup_pack.py   ← 生成 + 校验参考实现（零依赖）
├── docs/
│   ├── 生成记录规范.md        ← 中间产物（records / images）怎么组织
│   └── 示例-TODO.md           ← 一份填好的 TODO，供参考
├── tools/
│   ├── auto_backup.py       ← 模板仓库的自动化驱动（init / todo / build / verify / report）
│   └── selftest.py          ← 框架自检（内置 mock 数据，无需外部依赖）
├── run.cmd                  ← Windows 一键入口
├── work/                    ← 【AI 工作区】脚本产物，可随时删掉重来
│   ├── _meta.json           ← TODO 归一化后的机器配置（打包参数的唯一事实来源）
│   ├── source/              ← 原始留痕（抓取结果 / 用户提供的原文件副本）
│   ├── scripts/             ← AI 写的抓取与转换脚本
│   ├── records/             ← 【参与打包】movie.json / actor.json / comic.json / novel.json
│   ├── images/              ← 【参与打包】pack 策略下的本地图片池，按 ref 建目录
│   └── build_config.json    ← 构建开关（run_verify / fail_on_warning）
└── output/                  ← 产物：*.zip + deliver.md
```

关键分工：**`work/source/` 只留痕，`work/records/` + `work/images/` 才进包。**
删掉 `work/` 与 `output/` 不会影响规则，重跑即可（`init` 幂等，不会覆盖已有文件）。

---

## 一份备份包是怎么被约束住的

```
TODO.md  ──AI 归一化──▶  work/_meta.json  ──参数──┐
                          work/source/*  ──转换──▶ work/records/<type>.json ──┐
                                             work/images/<ref>  ──图片池──────┤
                                                                              ▼
                                        Rule/ammds_backup_pack.py build_backup()
                                                                              │
                                                    output/ammds-backup-*.zip │
                                                                              ▼
                                        verify_backup() + 质量自查 → 0 ERROR 才算交付
```

生成的包满足 AMMDS 的全部硬性要求：根目录 `manifest.json` + `data.json`、
`format=ammds-backup`、`formatVersion=1`、`count` 与数组长度严格一致、
`imageFiles[].path` 与 zip 条目逐字符一致、`data.json` 图片值与 `ref` 完全一致、
条目名无 `..`/`\`/`:`。细节见 `Rule/AI备份包生成规范.md`。

---

## 四种包分别长什么样

| type | 匹配键（必填） | 结构要点 |
| --- | --- | --- |
| `movie` | `uniqueid`（数组） | `poster`/`fanart`/`thumb` 是**数组**，`posterHd` 等是**单值**；`actors` 是对象数组 |
| `actor` | `name` | `poster` 是**单值**，`thumb` 是数组；身高体重三围写数字 |
| `comic` | `title`（有 `isbn` 更利于匹配） | `cover`/`backCover` 单值；`chapters[].pages[].imagePath` 承载每页图片；完整迁移必须选 `pack` |
| `novel` | `title` | `cover`/`backCover` 单值；`chapters[{title, content, sort}]`，`sort` 从 1 递增 |

---

## 常见问题

**Q：我需要装什么？**
A：只要 Python 3.8+。`Rule/ammds_backup_pack.py` 与 `tools/auto_backup.py` 都是标准库实现。

**Q：为什么不让我直接写 JSON？**
A：字段名拼错不会报错，只会「静默丢数据」（规范第 11.3 节）。让 AI 按规范生成、让脚本自检，
比人工比对 60 多个字段名靠谱。

**Q：图片一定要下载吗？**
A：不一定。`link` 只写外链，包体积极小，但依赖源站图片长期可访问；`pack` 离线可用。
漫画/相册的**完整迁移必须选 `pack`**。

**Q：包有多大 / 要跑多久？**
A：取决于图片量。元数据包通常几十 KB～几 MB；整个漫画库可能上百 MB～GB 级。交付说明里会写清体积。

**Q：AI 会不会瞎编数据？**
A：`AI.md` 第 0 节与第 7 节明确禁止编造与占位符；抓不到的字段一律省略。交付说明也会列出抓取失败清单。

**Q：导入后怎么用？**
A：AMMDS → **系统 → 备份恢复 → 数据导入** → 选 zip → 「解析预览」显示**校验通过** →
选冲突策略（首次导入推荐 `skip` 或 `overwrite`）→ 开始导入，确认 `failed=0`。

**Q：我改坏了 `work/` 怎么办？**
A：直接删掉 `work/` 和 `output/`，重跑 `python tools/auto_backup.py init` 并让 AI 重做。
`Rule/` 是只读规则，别删。
