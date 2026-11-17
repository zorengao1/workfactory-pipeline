# WorkFactory Pipeline

专业任务环境与教师候选轨迹生成管线。

## 流程

真实来源池 → 意图生成与审查 → 信息支撑图与文件规划 → 文件构建与审查 → 独立探针与修复 → 独立教师求解 → 候选轨迹导出。

模型、任务并发、API 并发、阶段模型和容器资源通过配置控制。文件数量和格式由工作需要决定。环境可包含 PDF、DOCX、PPTX、XLSX、CSV、JSON 等实际可处理的文件。

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

采集器只读取技能文档，不安装技能、不执行其中的指令和脚本。网页抓取内容保存在本地 data/，不会上传运行数据或密钥。

## 开发机准备

需要 Python 3.9 或更新版本、可用 Docker Engine 和模型接口。控制器与来源采集器使用 Python 标准库。Docker 中安装文档处理库和 LibreOffice，不依赖 Codex 或本机 Office。

```bash
git clone https://github.com/zorengao1/workfactory-pipeline.git
cd workfactory-pipeline
python3 source_pools.py fetch-soc
python3 source_pools.py fetch-onet
python3 source_pools.py fetch-skills
python3 source_pools.py build
docker build -t workfactory/runtime:v2 docker
python3 scripts/check_environment.py
python3 -m unittest discover -s tests -v
```

config/source-pools.json 控制 O*NET 版本、技能目录、采集数量与抽样参数。下载文件保存 URL、获取时间和 SHA256，缓存改变会明确报错。职业候选按 SOC 大类轮流排列，技能候选先用 TF-IDF 找相关文档，再由模型检查实际输入输出关系。该抽样方式没有复刻论文的频率分布。

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

Dockerfile 已成功构建，容器内四种文档格式的生成、读回与输入只读检查通过。已有三条 DeepSeek 多格式任务完成环境与教师候选轨迹生成，尚未统一完成人工验收。

真实职业与技能来源已经接入。职业上下文的动态网页搜索、真实专业交付物来源池、长轨迹拒绝采样、训练 token 掩码、跨机器调度和高并发压力测试仍待完成。external_retrieval=true 时当前会明确报错，不自动替换检索服务。

GitHub 保存源码、配置、提示词、测试、说明、Dockerfile 和小型固定来源资源，不保存 Docker 镜像或容器。开发机从 Docker Hub 拉取基础镜像并按 Dockerfile 构建独立环境。

## Responses 接口

在外部凭据文件设置 `OPENAI_API_MODE=responses` 可使用 Responses 接口。适配器保留推理项、函数调用与工具结果，按完整历史恢复执行。可选 `REASONING_EFFORT` 指定服务支持的推理强度，不默认关闭推理。DeepSeek 和 MiMo 仍使用原 Chat Completions 接口。Responses 当前使用非流式响应，完整响应落盘后进入工具执行。
