# WorkFactory Pipeline

专业任务环境与教师候选轨迹生成管线。

## 流程

真实来源池 → 意图生成与审查 → 信息支撑图与文件规划 → 文件构建与审查 → 独立探针与修复 → 独立教师求解 → 候选轨迹导出。

模型、任务并发、API 并发、阶段模型和容器资源通过配置控制。文件数量和格式由工作需要决定。环境可包含 PDF、DOCX、PPTX、XLSX、CSV、JSON 等实际可处理的文件。

当前实现、已验证范围及未完成项见 [实现状态清单](docs/IMPLEMENTATION_STATUS.md)。

## 03 纯 agentic 规划

03 默认由模型自主选择规划、检查和修订顺序，不固定运行 03A 至 03E。工具包括 save_plan、update_plan、check_plan、review_plan、submit_plan。审核使用同一阶段模型的新上下文。

提交要求当前版本通过结构检查与独立审核，所有实质问题都有关闭证据。计算口径、单位、时间窗和跨文件矛盾不能降为普通建议。合理的重复信息和业务冗余允许保留。修改后原审核失效。达到 plan_max_turns 上限仍未通过就停止并保留失败记录，不进入 04。默认上限为 20，可在管线策略中配置。

03 使用 stage_models 和 stage_credentials 中的 03_plan 配置，接口必须支持函数工具调用。纯文字接口不能承担此阶段，不会自动替换模型。03 不构建实际文件，沿用原有六块计划结构交给 04。

产物保存在任务的 03_plan 目录，包括各轮请求与响应、计划版本、审核证据、events.jsonl 和 validation.json。成功才写入 parsed.json 与 final_plan.json。已有成功任务仍可读取历史结果；需要用新方式重跑时使用新的任务运行目录。中断后的重新运行保留旧尝试目录，重新规划，不自动接续中断工具调用。

## 原素材入口

默认输入已改为 SOC、O*NET 和 skills.sh 来源生成的清单。config/cases.json 等手写情境仅保留为测试样例，不作为默认来源。

| 来源 | 用途 | 固定信息 |
|---|---|---|
| BLS 2018 SOC | 大类、细分职业、职责和层级 | 论文引用的 major_groups.htm |
| O*NET | 细分角色、实际任务、技能与工作活动 | 31.0 版本 |
| skills.sh | 技能文档正文及技能组合候选 | 固定本地抓取快照和哈希 |

BLS 官方地址为 https://www.bls.gov/soc/2018/major_groups.htm 。本机普通脚本收到 HTTP 403，返回页面说明自动采集受到限制。正常浏览器能够访问同一地址，因此通过 Chrome 保存了官方 HTML。resources/soc-2018 保存该页面和来源哈希，属于可核验的原素材快照。后续开发机默认读取这份固定快照，不依赖聊天或浏览器会话，也不切换其他来源。

需要更新 BLS 快照时，在浏览器打开同一官方地址并保存为仅 HTML，再显式导入。

```bash
python3 source_pools.py fetch-soc --import-html /absolute/path/major_groups.html
```

技能采集默认使用 skills CLI，在临时 HOME 和临时工作区下载配置中的仓库。原始 SKILL.md、配套文件、CLI 锁文件与内容哈希保存在 data/。文档仅作为合成意图的素材，不执行其中的指令或脚本，不修改用户现有 Agent 的技能配置。已有快照经哈希校验后可离线复用。

## 开发机准备

需要 Python 3.9 或更新版本、可用 Docker Engine 和模型接口。控制器使用 Python 标准库。技能采集额外需要 Node.js 和 skills CLI 1.8.1。Docker 中安装文档处理库和 LibreOffice，不依赖 Codex 或本机 Office。

```bash
git clone https://github.com/zorengao1/workfactory-pipeline.git
cd workfactory-pipeline
python3 source_pools.py fetch-soc
python3 source_pools.py fetch-onet
npm install -g skills@1.8.1
python3 source_pools.py fetch-skills
python3 source_pools.py build
docker build -t workfactory/runtime:v2 docker
python3 scripts/check_environment.py
python3 -m unittest discover -s tests -v
```

config/source-pools.json 控制 O*NET 版本、技能仓库、采集后端与抽样参数。CLI 默认采集所列仓库的全部技能，不使用网页后端的 96 个总量和每仓库 6 个限制。新增仓库需加入 skills_repositories。该配置覆盖指定仓库，并非全站遍历。下载文件保存 URL、获取时间和 SHA256，缓存改变会明确报错。职业候选按 SOC 大类轮流排列，技能候选先用 TF-IDF 找相关文档，再由模型检查实际输入输出关系。该抽样方式没有复刻论文的频率分布。

技能池更新采用显式命令。首次采集需要联网，缓存复用不需要搜索或模型 API。缺少 CLI、下载失败或缓存被改动时明确停止，不自动切换后端。更新来源后应创建新的批次，不覆盖正在运行的任务。

```bash
# 单个仓库试采集，结果单独保存
python3 source_pools.py fetch-skills --repository anthropics/skills --output tmp/skills-preview.json
# 使用已验证的本地缓存生成技能池
python3 source_pools.py fetch-skills
# 显式重新下载配置中的仓库，旧快照保留
python3 source_pools.py fetch-skills --refresh
# 再生成候选输入，之后以新批次运行
python3 source_pools.py build
```

原网页采集代码保留，可显式选择 fetch-skills --backend html。默认不会自动回退到网页采集。

data/source_pools/statistics.json 给出原素材和候选输入规模。当前快照统计见 docs/SOURCE_POOL_STATISTICS.json。候选输入数量不等于已生成环境或已验收轨迹数量。

build 默认每个 O*NET 职业产生一个候选输入，并创建 24 个技能组合候选。小批量验证可以显式减少数量。

```bash
python3 source_pools.py build --occupations 23 --skill-cases 4
```

每个职业不强制包含全部职责，只要求模型从来源支持的工作中选择一个可数字化执行的目标。业务情境和具体企业数据的合成须标注。

## 密钥与运行

密钥保存在仓库外部的 env 文件，模板为 config/credentials.env.example。不要提交密钥、本机配置或 runs/。默认模型入口支持 deepseek-v4.1-flash-1017、mimo-v2.6-flash、gpt-6.1-sol。

```bash
cp config/pipeline.json config/local.json
python3 batch_generate.py --config /absolute/path/credentials.env --pipeline-config config/local.json --output runs/batch-001 --model deepseek-v4.1-flash-1017
```

两个模型批次可以同时启动，模型分别用于本组构造和教师求解。

```bash
python3 run_models.py --config /absolute/path/credentials.env --pipeline-config config/local.json --output runs/batch-001 --models deepseek-v4.1-flash-1017 mimo-v2.6-flash
```

config/local.json 的 task_workers 控制每组完整任务并发，api_max_concurrency 控制每个模型的在途请求数。每个容器默认限制 2 GB 内存、1 CPU。接口配额与容器资源必须分别验证，64 并发尚未压测。

Linux 可以在已有的 tmux 或开发机作业调度器中运行上述命令。macOS 可使用 launchd 后台入口。

```bash
python3 service.py start --config /absolute/path/credentials.env --pipeline-config config/local.json --output runs/batch-001 --models deepseek-v4.1-flash-1017
python3 service.py status --output runs/batch-001
python3 service.py stop --output runs/batch-001
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

按职业在线发现与缓存技能、覆盖采样控制、程序证据包加单轮审核、独立成果验收、长轨迹拒绝采样、训练 token 掩码、细粒度恢复、跨机器调度和高并发压力测试仍待完成。逐项状态见 [实现状态清单](docs/IMPLEMENTATION_STATUS.md)。

GitHub 保存源码、配置、提示词、测试、说明、Dockerfile 和小型固定来源资源，不保存 Docker 镜像或容器。开发机从 Docker Hub 拉取基础镜像并按 Dockerfile 构建独立环境。

## Responses 接口

在外部凭据文件设置 `OPENAI_API_MODE=responses` 可使用 Responses 接口。适配器保留推理项、函数调用与工具结果，按完整历史恢复执行。可选 `REASONING_EFFORT` 指定服务支持的推理强度，不默认关闭推理。DeepSeek 和 MiMo 仍使用原 Chat Completions 接口。Responses 当前使用非流式响应，完整响应落盘后进入工具执行。

## 混合来源并发试跑

scripts/prepare_mixed_inputs.py 从当前技能池为指定职业匹配候选技能。候选的词面相关性由检索提名，模型仍需判断真实适用性。

启用 external_retrieval 时显式配置 retrieval.backend 为 responses_web_search，并在外部凭据文件配置 OPENAI_API_MODE=responses。联网只发生在来源准备阶段，探针和教师只使用冻结后的可见任务材料。原生 web_search 请求强制执行检索并保存来源列表；候选真实交付物经下载和解析验证，失败候选逐个保留，不以搜索摘要代替已下载文件。最多检索三份候选，仍无可读文件则停止该任务。下载检查 Content-Length，截断文件保留后从同一 URL 重新获取。

python3 scripts/prepare_mixed_inputs.py --occupations 13-1151.00 17-2081.00 27-3031.00 --output data/source_pools/gpt-mixed-three-timed.json

config/gpt-mixed-three-timed-policy.json 是三并发示例配置。先完成来源采集，再运行 service.py 或 run_models.py。scripts/audit_run.py 根据已保存响应 ID 去重统计模型用量、原生联网调用、阶段用量和任务墙钟时间，可传入明确的单价文件计算模型费用估计。缺少单价不填写费用。scripts/watch_run_report.py 仅观察指定批次，更新报告并在批次结束后退出，不启动模型任务或安排后续批次。

## 原文件复用

03 接收冻结原文件目录，并可用 read_source_text 分段查阅下载文件的完整提取正文，返回读取范围和总长度。文字提取不等于已检查图表版式。适合任务的原文件可直接作为输入，围绕它做更新、审查或比较；仅作意图线索的来源继续留在构造侧。

reference_files 的 reuse 和 adapt 项须填写 source_ids，绑定 source_materials 中带 snapshot 的真实文件。reuse 必须保持单份原文件及其格式，04 前由控制器直接复制，04 完成后校验 SHA256 不变。adapt 由构建者读取原件并按计划改编，记录位置及内容损失。缺失或哈希不符的原文件会报错，不自动转成合成文件。

无需强制所有任务复用真实文件，也不要求模型一次读完整个文件。本次测试覆盖截断范围以后的正文读取、原文件复制、篡改拒绝、来源绑定及路径检查。真实模型自主选择 reuse 的端到端比例尚待批量验证。

来源准备完整保存提取正文并记录哈希。首次输入仅提供12000字符预览，用content_is_preview明确标记；extraction_truncated表示全文是否丢失，不再用于标记预览。03可通过search_source_text检索全文中的关键词位置，再用read_source_text读取相关范围，包含预览之后的内容。优先评估业务适用的reuse，其次adapt，最后合成缺少的材料；允许核验相关章节后复用完整文件，不要求一次读取全文。历史来源快照不自动重写，已存在的artifact.txt仍可按完整正文访问。
