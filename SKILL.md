---
name: ammds-backup-package
description: 把爬取的数据或用户已有的数据文件制作为可被 AMMDS 导入的标准备份包（zip）。当用户要求制作备份包、生成 AMMDS 导入包、按备份包规范或 AI备份包生成规范做包，或处理 movie/actor/comic/novel 四类备份包时使用。内置零依赖 Python 脚本与格式规范，负责归一化数据、处理图片、打包并自检，直到 0 ERROR 才交付。
agent_created: true
---

# AMMDS 备份包制作

## 概述

把「把某个站点的数据做成 AMMDS 能导入的标准备份包」压缩成：用户填 4 个问题，本技能负责其余全部工作——字段映射、图片处理、manifest/data 生成、zip 打包、结构自检与交付说明。全程只用 Python 3.8+ 标准库，不装第三方依赖。

## 何时使用

- 用户说「把这些数据做成 AMMDS 备份包」「生成导入包」「按规范做备份包」
- 用户给出爬取结果 / 导出文件，要转成 movie / actor / comic / novel 四类备份包
- 用户提到 `ammds-backup`、`manifest.json`、`data.json`、备份包规范、模板仓库 AMMDS-BackupPackage

## 内置资源

- `AI.md`：收到制作请求后的**执行合同**（流程权威）。开始工作前先完整读一遍。
- `Rule/AI备份包生成规范.md`：**格式权威**（字段表、铁律、自检清单）。任何格式细节以它为准。
- `TODO.md`：用户填写的 4 个问题（输入）。`docs/示例-TODO.md` 是填好的参考。
- `docs/生成记录规范.md`：中间产物 records / images 的组织方式。
- `tools/auto_backup.py`：自动化驱动（init / todo / build / verify / report）。
- `tools/selftest.py`：框架自检（内置 mock 数据，会覆盖 work/ 与 output/，交付前不要跑）。
- `Rule/ammds_backup_pack.py`：打包与校验的参考实现（零依赖）。
- `run.cmd`：Windows 一键入口（`run.cmd init|todo|build|verify|report`）。

以下命令都在本技能根目录（含 `AI.md` 与 `tools/` 的目录）下执行。若需保持技能目录干净，可先把整个技能目录复制到工作区再运行。

## 工作流

严格按 `AI.md` 执行。摘要如下：

1. **预检**：跑 `python tools/auto_backup.py init`（幂等）与 `python tools/auto_backup.py todo`。todo 报 ERROR 就停下来问用户缺的那几项（不超过 3 个问题），不要替用户猜类型 / 图片策略 / 数据源。
2. **归一化 TODO → `work/_meta.json`**：把用户口语化的 4 个答案翻译成严格字段（`package_type` / `source_mode` / `image_strategy` 等）。
3. **取数据 → `work/source/`**：scrape 模式先抓 1 个列表页 + 1 个详情页侦察真实结构再写正式脚本，保存原始响应；existing 模式先复制用户文件再读结构。脚本放 `work/scripts/`。
4. **归一化记录 → `work/records/<type>.json`**：顶层 JSON 数组，字段名严格按规范第 5 节；整数写整数、日期写 `yyyy-MM-dd`、枚举只写 code、取不到就省略字段。图片引用按 `image_strategy` 决定：`pack` 写 `data/...` 引用键并下载到 `work/images/<ref>`；`link` 写完整 URL；`none` 不写图片字段。
5. **打包 + 自检 + 交付**：`pack` 策略先把图片按 ref 放到 `work/images/`，再跑 `python tools/auto_backup.py build`（严谨版加 `--strict`）。必须 ERROR=0 才交付；非零就按打印的错误逐条修并重跑。交付时给出包路径、体积、SHA-256 前 8 位、type / 条目数 / 图片数、导入路径与遗留风险，明细写入 `output/deliver.md`。

## 唯一事实来源

- 参与打包：`work/records/<type>.json` + `work/_meta.json`（参数）。
- `work/source/` 只留痕，不参与打包；删掉 `work/` 与 `output/` 后可重跑（`init` 幂等）。
- `Rule/` 是只读规则，不要改动或删除。

## 停下来问用户的情形

- `todo` 预检报 ERROR（站点 / 入口、四选一类型、图片策略、有无现成数据）
- 用户选的类型与数据明显不符
- 抓取需要登录 / 全站反爬
- `pack` 策略下有图片抓不到
- 体积可能上 GB，需确认继续

## 硬性禁止

- 不问用户就自己编 `package_type`；往数据里写「未知」「-」等占位符
- 整数写 `120.0`、日期写 `2026/08/01`、枚举写中文名
- 把外链登记进 `imageFiles`，或把 pack 引用写成完整 URL
- 手工改 manifest 的 `count` / `imageFiles`，或未经自检 / 用 `--force` 冒充通过
- 改动 `Rule/` 下的文件、改动用户原始数据、写入任何密钥（Cookie / Token / 密码）
