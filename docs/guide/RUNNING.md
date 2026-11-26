# 运行手册

专业任务环境与教师候选轨迹生成管线。

[返回首页](../../README.md) · [代码地图](../ARCHITECTURE.md)

本文所有命令均在仓库根目录执行。

## 流程

真实来源池 → 意图生成与审查 → 信息支撑图与文件规划 → 文件构建与审查 → 独立探针与修复 → 独立教师求解 → 候选轨迹导出。

模型、任务并发、API 并发、阶段模型和容器资源通过配置控制。文件数量和格式由工作需要决定。环境可包含 PDF、DOCX、PPTX、XLSX、CSV、JSON 等实际可处理的文件。

当前实现、已验证范围及未完成项见 [实现状态清单](../IMPLEMENTATION_STATUS.md)。

## 03 纯 agentic 规划

03 默认由模型自主选择规划、检查和修订顺序，不固定运行 03A 至 03E。工具包括 save_plan、update_plan、check_plan、review_plan、submit_plan。审核使用同一阶段模型的新上下文。

提交要求当前版本通过结构检查与独立审核，所有实质问题都有关闭证据。计算口径、单位、时间窗和跨文件矛盾不能降为普通建议。合理的重复信息和业务冗余允许保留。修改后原审核失效。达到 plan_max_turns 上限仍未通过就停止并保留失败记录，不进入 04。默认上限为 20，可在管线策略中配置。

03 使用 stage_models 和 stage_credentials 中的 03_plan 配置，接口必须支持函数工具调用。纯文字接口不能承担此阶段，不会自动替换模型。03 不构建实际文件，沿用原有六块计划结构交给 04。

产物保存在任务的 03_plan 目录，包括各轮请求与响应、计划版本、审核证据、events.jsonl 和 validation.json。成功才写入 parsed.json 与 final_plan.json。已有成功任务仍可读取历史结果；需要用新方式重跑时使用新的任务运行目录。中断后的重新运行保留旧尝试目录，重新规划，不自动接续中断工具调用。

## 原素材入口

默认输入由 SOC、O*NET、本地技能索引和真实交付物生成。config/cases.json 等手写情境仅保留为测试样例，不作为默认来源。

| 来源 | 用途 | 固定信息 |
|---|---|---|
| BLS 2018 SOC | 大类、细分职业、职责和层级 | 论文引用的 major_groups.htm |
| O*NET | 细分角色、实际任务、技能与工作活动 | 31.0 版本 |
| 本地技能索引 | 技能召回、正文判断与技能组合 | 索引标识、向量模型名和正文哈希 |
| 真实交付物 | 反推工作意图，或作为任务输入复用 | 下载原文件、提取正文、URL 和哈希 |

BLS 官方地址为 https://www.bls.gov/soc/2018/major_groups.htm 。本机普通脚本收到 HTTP 403，返回页面说明自动采集受到限制。正常浏览器能够访问同一地址，因此通过 Chrome 保存了官方 HTML。resources/soc-2018 保存该页面和来源哈希，属于可核验的原素材快照。后续开发机默认读取这份固定快照，不依赖聊天或浏览器会话，也不切换其他来源。

需要更新 BLS 快照时，在浏览器打开同一官方地址并保存为仅 HTML，再显式导入。

```bash
python3 -m workfactory.sources.source_pools fetch-soc --import-html /absolute/path/major_groups.html
```

技能来自预先建好的本地索引，不在线采集。技能文档仅作为合成意图的素材，不执行其中的指令或脚本。索引的内容和导出方法见四路输入一节。

## 开发机准备

需要 Python 3.9 或更新版本、可用 Docker Engine 和模型接口。控制器使用 Python 标准库，读取技能索引另需 numpy。不需要 Node.js。Docker 中安装文档处理库和 LibreOffice，不依赖 Codex 或本机 Office。

```bash
git clone https://github.com/zorengao1/workfactory-pipeline.git
cd workfactory-pipeline
python3 -m workfactory.sources.source_pools fetch-soc
python3 -m workfactory.sources.source_pools fetch-onet
# 把技能索引放到 data/skill_index 后再生成候选输入
python3 -m workfactory.sources.source_pools build
docker build -t workfactory/runtime:v2 docker
python3 scripts/check_environment.py
python3 -m unittest discover -s tests -v
```

config/source-pools.json 控制 O*NET 版本、职业筛选表、技能索引位置、各路数量与抽样种子。data/source_pools/statistics.json 给出各路候选输入数量。候选输入数量不等于已生成环境或已验收轨迹数量。更换来源或配置后应创建新的批次目录。

小批量验证可以显式减少数量。

```bash
python3 -m workfactory.sources.source_pools build --occupations 23 --skill-cases 4 --mixed-cases 4 --deliverable-cases 4
```

每个职业不强制包含全部职责，只要求模型从来源支持的工作中选择一个可数字化执行的目标。业务情境和具体企业数据的合成须标注。

## 密钥与运行

密钥保存在仓库外部的 env 文件，模板为 config/credentials.env.example。不要提交密钥、本机配置或 runs/。默认模型入口支持 deepseek-v4.1-flash-1017、mimo-v2.6-flash、gpt-6.1-sol。

```bash
cp config/pipeline.json config/local.json
python3 -m workfactory.pipeline.batch_generate --config /absolute/path/credentials.env --pipeline-config config/local.json --output runs/batch-001 --model deepseek-v4.1-flash-1017
```

两个模型批次可以同时启动，模型分别用于本组构造和教师求解。

```bash
python3 -m workfactory.operations.run_models --config /absolute/path/credentials.env --pipeline-config config/local.json --output runs/batch-001 --models deepseek-v4.1-flash-1017 mimo-v2.6-flash
```

config/local.json 的 task_workers 控制每组完整任务并发，api_max_concurrency 控制每个模型的在途请求数。每个容器默认限制 2 GB 内存、1 CPU。接口配额与容器资源必须分别验证，64 并发尚未压测。

Linux 可以在已有的 tmux 或开发机作业调度器中运行上述命令。macOS 可使用 launchd 后台入口。

```bash
python3 -m workfactory.operations.service start --config /absolute/path/credentials.env --pipeline-config config/local.json --output runs/batch-001 --models deepseek-v4.1-flash-1017
python3 -m workfactory.operations.service status --output runs/batch-001
python3 -m workfactory.operations.service stop --output runs/batch-001
```

后台入口在关闭聊天或终端后仍可运行。睡眠、关机、退出系统登录会影响本地执行，不自动无限重启失败批次。Documents 下的后台脚本可能被 macOS 文件访问权限阻断，已验证的本地部署路径为 ~/workfactory-pipeline。

## 检查真实来源是否驱动模型

以下命令调用模型，分别读取法律、教育职业资料及两组真实技能文档，执行意图生成与审查。它只检查来源到意图这部分，不生成完整环境。

```bash
python3 scripts/check_source_inputs.py --config /absolute/path/credentials.env --output runs/source-input-check
```

## 输出与恢复

```text
runs/<batch>/<model>/<task>/
  seed.json
  status.json
  attempt-01/
    initial_plan.json
    materialization-00/
    repair-1/
    teacher_workspace/REQUEST.txt
    teacher_workspace/inputs/
    teacher_workspace/outputs/
    trajectory.json
```

各阶段保存请求、响应、工具结果与检查结论。trajectory.json 是教师候选轨迹，人工验收和训练数据合格分别记录。batch_report.py 汇总批次状态。

完成任务会跳过，通过检查的阶段会复用。请求已保存但响应未保存时可从对话恢复。响应已保存而工具状态不明时停止并要求审查。更改代码、配置或输入后应使用新批次目录，保留失败尝试。

API 调用入口为 pilot.py，限流在 api_gate.py，阶段编排在 batch_generate.py，工具循环在 tool_runtime.py，容器生命周期在 docker_runtime.py，阶段提示词和输出契约位于 prompts/ 与 schemas/。

## 当前验证与待完成部分

Dockerfile 已成功构建，容器内文档生成、读回与输入只读检查通过。已有 DeepSeek 候选轨迹及三条 GPT 混合来源联网候选轨迹完成执行，尚未统一完成人工验收和训练数据整理。

BLS、O*NET、skills CLI、GPT 原生 web_search 和真实交付物下载解析已接入。external_retrieval=true 需要显式配置 responses_web_search 后端及 Responses 接口模式，缺少配置时明确报错。

文件格式规划鼓励有业务意义的多样性，主动考虑论文涉及及其他可处理格式，按用途、受众和使用方式说明理由，构建审核增加必查 format_fitness，每份输入文件必须说明用途、受众、使用方式和格式选择理由，禁止因方便生成而默认使用 MD。根据任务实际需要选择 DOCX、PDF、PPTX、XLSX 等格式，鼓励合理组合，同类材料适合统一格式时保持统一，不强凑种类或数量。这一修改通过本地测试，尚未用新批次验证实际效果。旧批次使用旧提示词，历史结果不回写。

覆盖采样控制、程序证据包加单轮审核、独立成果验收、长轨迹拒绝采样、训练 token 掩码、细粒度恢复、跨机器调度和高并发压力测试仍待完成。逐项状态见 [实现状态清单](../IMPLEMENTATION_STATUS.md)。

GitHub 保存源码、配置、提示词、测试、说明、Dockerfile 和小型固定来源资源，不保存 Docker 镜像或容器。开发机从 Docker Hub 拉取基础镜像并按 Dockerfile 构建独立环境。

## Responses 接口

在外部凭据文件设置 `OPENAI_API_MODE=responses` 可使用 Responses 接口。适配器保留推理项、函数调用与工具结果，按完整历史恢复执行。可选 `REASONING_EFFORT` 指定服务支持的推理强度，不默认关闭推理。DeepSeek 和 MiMo 仍使用原 Chat Completions 接口。Responses 当前使用非流式响应，完整响应落盘后进入工具执行。

## 混合来源并发试跑

scripts/prepare_mixed_inputs.py 为指定职业预览 mixed 路的技能召回与模型判断，结果可作为小批量输入。候选由本地索引提名，模型判断真实适用性。

启用 external_retrieval 时显式配置 retrieval.backend 为 responses_web_search，并在外部凭据文件配置 OPENAI_API_MODE=responses。联网只发生在来源准备阶段，探针和教师只使用冻结后的可见任务材料。原生 web_search 请求强制执行检索并保存来源列表；候选真实交付物经下载和解析验证，失败候选逐个保留，不以搜索摘要代替已下载文件。最多检索三份候选，仍无可读文件则停止该任务。下载检查 Content-Length，截断文件保留后从同一 URL 重新获取。

python3 scripts/prepare_mixed_inputs.py --occupations 13-1151.00 17-2081.00 27-3031.00 --config /secure/model.env --audit runs/skill-discovery-preview --output data/source_pools/gpt-mixed-three-timed.json

config/gpt-mixed-three-timed-policy.json 是三并发示例配置。先完成来源采集，再运行 service.py 或 run_models.py。scripts/audit_run.py 根据已保存响应 ID 去重统计模型用量、原生联网调用、阶段用量和任务墙钟时间，可传入明确的单价文件计算模型费用估计。缺少单价不填写费用。scripts/watch_run_report.py 仅观察指定批次，更新报告并在批次结束后退出，不启动模型任务或安排后续批次。

## 原文件复用

03 接收冻结原文件目录，并可用 read_source_text 分段查阅下载文件的完整提取正文，返回读取范围和总长度。文字提取不等于已检查图表版式。适合任务的原文件可直接作为输入，围绕它做更新、审查或比较；仅作意图线索的来源继续留在构造侧。

reference_files 的 reuse 和 adapt 项须填写 source_ids，绑定 source_materials 中带 snapshot 的真实文件。reuse 必须保持单份原文件及其格式，04 前由控制器直接复制，04 完成后校验 SHA256 不变。adapt 由构建者读取原件并按计划改编，记录位置及内容损失。缺失或哈希不符的原文件会报错，不自动转成合成文件。

无需强制所有任务复用真实文件，也不要求模型一次读完整个文件。本次测试覆盖截断范围以后的正文读取、原文件复制、篡改拒绝、来源绑定及路径检查。真实模型自主选择 reuse 的端到端比例尚待批量验证。

来源准备完整保存提取正文并记录哈希，content 直接包含完整正文，不再保留 12000 字符限制。01 三个意图入口和 02 意图审核在发送请求前恢复旧缓存中的全文，并核验可用的文件哈希。全文缺失或损坏时明确失败，不退回预览。03 仍可搜索和分段查阅原文。超过模型上下文时由接口明确报错，不自动截断。每次 01 和 02 保存实际 input.json；旧阶段缓存缺少该文件或输入不一致时，要求使用新输出目录，避免沿用基于预览生成的意图及下游产物。历史文件保持不变。


## 真实交付物下载与解析检查

下载器对超时、断连、空响应、截断、408、429 和部分 5xx 最多尝试三次。普通重试等待 1 秒、2 秒；429 的数字 Retry-After 最多等待 60 秒。401、403、404、410 不自动重试，不绕过访问限制。下载上限为 20 MiB，每次最多 32 个分段，分段核验长度与可用的版本标记。旧临时文件保留归档，重启时重新下载。

空文件、PDF 链接返回 HTML、明显错误页面会明确拒绝。PDF 逐页提取并对低文本页执行 OCR，详见下方 PDF OCR 与检索边界。短文本只标记，不再仅因不足 500 字符直接淘汰；文本存在不代表语义充分或版式完整。提取文本绑定源文件和解析器哈希，避免复用旧正文。

2026-11-25 已实测三个历史失败链接的完整下载，并通过本地 HTTP 服务测试重定向、分段、空响应、截断及临时错误。PDF 容器解析尚未完成本轮实测。

### PDF OCR 与检索边界

默认配置在意图合成及信息图构建前开启真实交付物联网检索，要求配置 Responses 搜索接口。缺少接口会报错。明确关闭 external_retrieval 才运行纯本地资料实验。

03 只读取冻结来源，04 根据计划将原件复用、改编或合成到工作环境。后续审核、探针和教师只访问该环境，修复器在其中修复。来源目录仅挂载给 04，执行阶段强制关闭模型原生联网搜索，Docker 使用隔离网络。

PDF 逐页提取文字，低于 30 个字母或数字的页面调用本地 Tesseract OCR，支持英文和简体中文。诊断记录每页处理方式与字符数。OCR 超时或缺少依赖会明确失败，全篇仍无可读正文则拒绝。原 PDF 保持不变，OCR 正文仅供来源分析。

OCR 依赖已写入 docker/Dockerfile，更新代码后需重新构建所配置的运行镜像。单页渲染最长边 2400 像素，渲染限时 60 秒，OCR 限时 90 秒，单文档提取限时 1800 秒。复杂表格、手写文字和低清图片仍需质量检查，OCR 成功不代表内容准确。

### Harbor 环境与任务导出

新批次在探针通过及环境修复完成后、教师执行前，自动输出到 `attempt-XX/harbor/<task_id>/`。采用 Harbor schema 1.4 的任务配置。当前范围仅环境和任务，评分暂不接入，因此不生成 `tests/test.sh` 或 reward，`verifier_status` 为 `pending`，不能作为已完成评分适配的 benchmark 运行。

```text
<task_id>/
├── task.toml
├── instruction.md
├── environment/
│   ├── Dockerfile
│   └── workspace/
│       └── inputs/
└── export_manifest.json
```

`instruction.md` 是 Harbor 唯一任务说明入口，来自最终工作环境中的 REQUEST.txt，并补充工作路径与网络限制。导出环境不再复制 REQUEST.txt，原管线的文件保持不变。`inputs` 保留原始字节及多种文件格式。构建上下文只包含干净任务材料，不打包教师答案、信息图、提示词、API 密钥、生成日志或评分材料。模型在 `/task` 工作，输入文件只读，成果写入 `/task/outputs`，任务环境关闭联网。Dockerfile 包含仓库中的完整运行环境安装步骤，开发机无需预先拥有本机的 workfactory/runtime 镜像。

旧任务可手动导出，环境路径应指向 `status.json` 中的 `clean_environment`，有修复时选最终修复版本。导出不重新调用模型，不改旧运行记录。

```bash
python3 -m workfactory.exports.harbor_export \
  --task-id example-task \
  --environment /absolute/path/to/clean_environment \
  --output /absolute/path/to/harbor/example-task
```

已完成的历史批次不会自动重新运行。导出目录不能覆盖，恢复运行会校验源文件与导出文件哈希。教师轨迹和成果仍保留在任务包外的原运行目录。未来接入评分时，可通过 `--verifier /path/to/tests` 放入明确提供的验证器，单纯复制验证器仍不等于已完成 Harbor 运行验收。

格式依据 https://github.com/harbor-framework/harbor/blob/main/docs-mintlify/tasks/configuration.mdx 。本轮自动测试覆盖结构、文件完整性、答案隔离和恢复校验，未执行 Harbor 容器端到端运行。


## 四路输入与本地技能索引

候选输入按来源分成四路，由 `source_metadata.route` 标明。前三路对应论文的三种意图来源，mixed 是本仓库增加的组合路线。

| 路线 | 生成时的输入 | 运行时准备的来源 | 意图阶段 |
|---|---|---|---|
| occupation | 一个 O*NET 职业 | 无 | 01a |
| skill | 索引中的一个锚点技能 | 召回与锚点相关的技能，模型按输入输出能否衔接组合 | 01b |
| deliverable | 一个检索线索，或一个已知 URL | 取得一份真实交付物，作为唯一意图素材 | 01c |
| mixed | 一个 O*NET 职业 | 按职业召回技能并由模型判断，再检索一份真实交付物 | 01a |

缺少 route 的旧输入按阶段推断为前三路之一，不追加任何来源。skill 和 mixed 在技能索引缺失时直接报错，deliverable 取不到可读文件时停止该任务，各路之间不互相替代。

`sources build` 一次生成四路输入。

```bash
python3 -m workfactory sources build
python3 -m workfactory sources build --digitizable yes limited --skill-cases 500 --mixed-cases 200 --deliverable-cases 200
python3 -m workfactory sources build --deliverable-manifest /absolute/path/deliverables.json
```

数量参数取 -1 表示全部可用职业。当前每个职业或锚点在每一路只生成一条输入，更大批量需要同一来源生成多条不同输入，尚未实现。

### 各路之间的重叠

各路之间不做互斥限制。进入 mixed 路的职业同时保留在 occupation 路，同一职业或技能本来就会产出多条任务。两路素材不同，occupation 路只凭职业职责设定情境，mixed 路受召回技能的工作流约束。

skill 路的锚点独立抽样，不排除 mixed 路可能选中的技能。每条任务的 `source_metadata.skill_discovery.selected_ids` 记录实际使用的技能，可在批次结束后统计重叠并在意图层面去重。

deliverable 路用职业的名称、描述和几条典型任务作为检索线索，线索只保存在 `source_metadata`，不进入意图素材。

### 职业筛选表

`config/occupation-filter.csv` 为 1016 个 O*NET 职业给出两个互相独立的标记。

| 标记 | 取值 | 作用 |
|---|---|---|
| digitizable | yes、limited、no | 决定职业能否进入管线，occupation、mixed 和 deliverable 的检索线索都受它约束 |
| mixed_route | yes、no | 决定职业是否生成 mixed 路输入，只反映技能库有无足够相近技能 |

digitizable 依据 O*NET 工作活动重要度。体力、搬运、操控机器、驾驶、维修占主导的记为 no。医疗从业与医疗辅助类中直接照护病人的，以及数字与物理分数接近的，记为 limited。技能少的职业不会因此被剔除，它们保留在 occupation 路。mixed_route 取自 Qwen3-Embedding-8B 向量相似度，一半以上任务有相似度不低于 0.45 的技能记为 yes，另有 4 个经人工复核改为 no。supplemental_search 标出做过补充搜索的 14 个职业，便于单独查看其产出。

当前计数为 yes 459、limited 153、no 404，其中 mixed_route 为 yes 的有 523 个。阈值来自小样本抽查，属于粗筛，最终是否对口由运行时的模型判断决定。默认只取 digitizable 为 yes 的职业。

### 本地技能索引

skill 和 mixed 两路从预先建好的索引取技能，运行时不联网搜索，也不调用 embedding 模型。索引包含技能向量、每个职业的画像与任务向量，以及保存技能正文的 SQLite。编排进程需要 numpy。生成输入时抽取锚点只读 SQLite，不需要 numpy。

当前索引含 117194 条技能，由 SkillMD-138K、huzey/claude-skills、SkillGym 和 ClawHub 补充搜索合并而成，经正文去重、长度与字段过滤、0.97 近重复合并和模板技能移除。其中大部分面向软件开发。约半数技能正文引用了未随正文提供的配套文件，索引以 attachments_missing 标出。索引不进入 Git，放在 `skill_discovery.index_dir` 和 `skill_index_dir` 指向的目录，默认 `data/skill_index`。

```bash
python3 scripts/export_skill_index.py --skills skills_final.parquet \
  --skill-vectors skills_final.f16.npy --skill-ids skills_final.ids.json \
  --query-vectors occ_all.f16.npy --query-ids occ_all.ids.json \
  --embedding-model Qwen3-Embedding-8B --output data/skill_index
```

导出脚本需要 numpy 和 pyarrow，输出目录已存在时拒绝覆盖。更换技能池或向量后导出到新目录，并使用新的批次目录。

### skill 路

1. 生成输入时从索引抽取锚点技能。只取正文 200 至 4000 词、有名称和描述、不缺配套文件的技能，按仓库轮流抽取，避免少数大仓库占满。锚点正文直接写入输入。
2. 运行时取与锚点向量相似度在 `neighbor_min_similarity` 和 `neighbor_max_similarity` 之间的技能作为候选。上限用于排除锚点的变体，候选彼此之间也按同一上限去掉近似版本，避免候选全是同一功能的不同写法。
3. 模型分析锚点的用途、适用条件、前提和操作，提出工作情境，再判断哪些候选的产出能作为另一技能的输入。没有合适搭配时可以只用锚点。提示词为 `prompts/skills_compose.txt`。
4. 程序校验锚点在选中技能之内，其余校验与 mixed 路相同。

### mixed 路

1. 取该职业画像和每条任务的向量，各自找出最相近的技能，按查询轮流合并，首轮最多十五条候选。过短、超过 `max_skill_words` 或相似度低于 `min_similarity` 的不进入候选。
2. 模型读取候选完整正文，先逐条判断是否对口，再固定工作目标、列出三种以上互补能力、选择二至四个技能并给出正文证据、步骤依赖和所需资源。提示词为 `prompts/skills_judge.txt`。
3. 程序校验证据确实出现在正文、能力全部被覆盖、至少六个不同操作和四层有序依赖、没有不可得的必要资源。
4. 模型认为候选不足时，追加下一批不重复的候选再判断一次。仍不成立则拒绝该输入，批次继续处理其他任务。
5. 通过后按原有方式检索一份真实交付物。

两路的 `skill_discovery/` 目录保留输入、每轮候选、模型请求与响应、覆盖检查和接受或拒绝结果。成功检查点可复用，输入、模型、策略或索引变化会要求使用新运行目录。向量召回只负责提名，内容较泛的技能可能在许多职业中排名靠前，是否采用由模型判断。

### deliverable 路

对应论文的交付物驱动合成，用真实交付物作为线索，分析其用途、受众、内容和隐含的制作过程，反推制作、更新、审查或比较此类成果的意图。输入有两种来源。

| 来源 | 生成方式 | 运行时 |
|---|---|---|
| 检索线索 | `--deliverable-cases`，每个职业一条 | 用 Responses 原生 web_search 找一份公开成果，下载并解析，最多尝试 `candidate_attempts` 个候选 |
| 已知 URL | `--deliverable-manifest`，JSON 列表，每项含 url，可选 title 和 publisher | 直接下载并解析，不调用搜索 |

两种来源共用下载完整性检查、容器内正文提取和质量检查。取得的文件成为该任务唯一的意图素材，原文件保留给 03 规划和 04 构建，可以按原有的复用规则作为任务输入。检索线索需要配置 `retrieval.backend` 为 `responses_web_search` 并使用 Responses 接口，缺少时该任务报错。清单中的 URL 须为公开的 HTTPS 地址，下载器不绕过登录或访问限制。交付物目前按任务各自检索，没有跨任务共享缓存和许可证记录。

### 已验证与未验证

本地测试覆盖索引召回、锚点抽样、两种模型判断流程、四路分流、交付物两种来源和候选生成。真实索引的职业召回和邻近技能召回已在开发机实测。两个模型判断环节和 deliverable 路的检索尚未用真实模型运行，判断质量、通过率和交付物可得率未知。
