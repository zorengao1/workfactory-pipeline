<div align="center">

# WorkFactory Pipeline

**从真实职业、技能和交付物，生成可执行任务环境与教师轨迹**

依据 WorkFactory 论文构建的独立实现

[快速启动](#快速启动) · [目录导航](#目录导航) · [运行手册](docs/guide/RUNNING.md) · [代码地图](docs/ARCHITECTURE.md) · [实现状态](docs/IMPLEMENTATION_STATUS.md)

</div>

---

## 管线概览

~~~mermaid
flowchart LR
    A["SOC · O*NET<br/>本地技能索引 · 真实交付物"] --> B["01–02<br/>意图合成与审查"]
    B --> C["03<br/>信息图规划与审核"]
    C --> D["04–05<br/>文件构建与检查"]
    D --> E["06<br/>独立探针"]
    E -->|阻断问题| F["07–08<br/>修复与工作保留审查"]
    F --> E
    E -->|通过| G["09<br/>独立教师求解"]
    D --> H["Harbor 任务环境"]
    G --> I["教师交付物 · 候选轨迹"]
~~~

- **真实来源**　保留下载原文件、完整提取正文、来源链接与哈希
- **按任务选择格式**　支持 PDF、DOCX、PPTX、XLSX、CSV、JSON 等，不设格式或数量配额
- **独立执行环境**　探针与教师在专属 Docker 工作区内执行，构造资料与求解材料分开
- **可追踪运行**　保存模型请求、工具调用、审核结果和失败尝试，支持配置并发与恢复
- **标准化交付**　导出 Harbor 任务环境，当前范围暂不包含最终评分器

## 目录导航

| 目录 | 内容 |
|---|---|
| [workfactory/pipeline](workfactory/pipeline) | 阶段编排、信息图规划、构建检查和输出契约 |
| [workfactory/sources](workfactory/sources) | SOC、O*NET、技能搜索、真实交付物下载与解析 |
| [workfactory/clients](workfactory/clients) | 模型接口、Responses 适配和 API 并发控制 |
| [workfactory/runtime](workfactory/runtime) | Agent 工具循环、Docker 隔离和文件读写工具 |
| [workfactory/exports](workfactory/exports) | Harbor、教师轨迹和批次报告导出 |
| [workfactory/operations](workfactory/operations) | 多模型批次与后台运行 |
| [workfactory/experiments](workfactory/experiments) | 历史小样本实验和回归入口 |
| [config](config) | 管线策略、来源配置和凭据模板 |
| [prompts](prompts) · [schemas](schemas) | 各阶段提示词与 JSON 输出结构 |
| [scripts](scripts) · [tests](tests) | 检查、审计脚本与自动化测试 |
| [docker](docker) | 可复建的运行环境 Dockerfile |
| [resources](resources) · [fixtures](fixtures) | 固定来源快照与测试样例 |
| [docs](docs) | 运行手册、代码地图和历史记录 |

下载资料保存到本地 <code>data/</code>，生成结果保存到 <code>runs/</code>。两者均不提交到 GitHub。

## 快速启动

在仓库根目录执行。需要 Python 3.9+、numpy、Docker Engine，以及可用的模型接口。

~~~bash
git clone https://github.com/zorengao1/workfactory-pipeline.git
cd workfactory-pipeline

# 准备来源与运行环境
python3 -m workfactory sources fetch-soc
python3 -m workfactory sources fetch-onet
# 把本地技能索引放到 data/skill_index，见运行手册的四路输入一节
python3 -m workfactory sources build
docker build -t workfactory/runtime:v2 docker

# 检查安装与代码
python3 scripts/check_environment.py
python3 -m unittest discover -s tests

# 配置模型与并发，凭据保存在仓库之外
cp config/pipeline.json config/local.json
python3 -m workfactory batch \
  --config /absolute/path/credentials.env \
  --pipeline-config config/local.json \
  --output runs/batch-001 \
  --model deepseek-v4.1-flash-1017
~~~

凭据格式见 [credentials.env.example](config/credentials.env.example)。运行前按实际接口修改策略中的阶段模型、凭据路径、检索和并发参数。mixed 和 deliverable 两路的真实交付物检索需要支持 Responses web_search 的接口，工具执行阶段需要工具调用能力。

更多命令可通过 <code>python3 -m workfactory --help</code> 查看。

## 从哪里看结果

| 想看什么 | 查看位置 |
|---|---|
| 当前批次运行状态 | 批次及任务目录中的 status.json 与日志 |
| 各模块输入输出 | 阶段目录中的请求、响应、parsed.json 和审核记录 |
| 实际交付文件 | teacher_workspace/outputs/ |
| 教师候选轨迹 | trajectory.json |
| Harbor 任务包 | 按 [Harbor 导出说明](docs/guide/RUNNING.md#harbor-环境与任务导出) 生成 |
| 失败后的恢复方法 | [运行手册](docs/guide/RUNNING.md#输出与恢复) |

## 开发与阅读

从 [代码地图](docs/ARCHITECTURE.md) 了解模块调用关系，从 [运行手册](docs/guide/RUNNING.md) 查看来源采集、阶段模型、下载解析、技能筛选与恢复细节。

当前实现及实验记录见 [实现状态](docs/IMPLEMENTATION_STATUS.md)。旧版发布清单和说明归档在 [docs/archive](docs/archive)，新运行请使用上述模块命令。

目录组织参考 [Terminal-Bench](https://github.com/harbor-framework/terminal-bench) 与 [EnvScaler](https://github.com/RUC-NLPIR/EnvScaler)，按本管线职责划分代码、脚本、配置与文档。
