# WorkFactory Pipeline

独立运行的专业任务合成与教师轨迹生成管线。

## 当前可用范围

- 意图合成 → 信息支撑图 → 文件规划 → 环境构建与检查 → 探针与修复 → 教师执行 → 候选轨迹导出
- DeepSeek V4.1 Flash 1017 与 MiMo V2.6 Flash 分组运行，各组默认使用同一模型构造与求解
- 文件格式和数量由规划器选择，支持 PDF、DOCX、PPTX、XLSX 与文本类文件
- 任务并行和模型 API 并发分别配置，保存每个阶段的请求、响应、工具记录与失败尝试
- macOS 后台入口由 launchd 托管，文件访问权限满足后可独立于聊天执行

目前新版 Docker 端到端与高并发压测尚未通过。代码检查通过不代表十条新轨迹已经生成。

## 仓库与执行环境

GitHub 保存管线源码、提示词、JSON 契约、配置模板、测试、README 和 docker/Dockerfile。Docker 镜像、容器、运行结果与密钥保存在运行机器上，不提交 GitHub。

开发机克隆仓库后，执行 docker build。Docker 根据 Dockerfile 的 FROM 从 Docker Hub 拉取 Python 基础镜像，再安装文档处理依赖，构建本机 WorkFactory 镜像。Dockerfile 从 GitHub 获取，基础镜像从 Docker Hub 获取。

```bash
git clone https://github.com/zorengao1/workfactory-pipeline.git
cd workfactory-pipeline
docker build -t workfactory/runtime:v2 docker
python3 scripts/check_environment.py
```

多台开发机可以分别构建相同 Dockerfile。将来如需直接拉取预构建 WorkFactory 镜像，可单独发布到镜像仓库，并在 sandbox.image 指定版本。目前尚未发布该镜像。

该组织方式参考 Terminal-Bench 的代码、任务配置与环境构建文件分离。当前仓库保留自己的任务契约与编排入口，未实现 Terminal-Bench 格式兼容。

## 安装与准备

需要 Python 3.10 或更新版本、Docker Desktop 和可调用的模型接口。后台入口需要 macOS 登录会话。

```bash
cp config/pipeline.json config/local.json
mkdir -p "$HOME/.config/workfactory"
cp config/credentials.env.example "$HOME/.config/workfactory/credentials.env"
chmod 600 "$HOME/.config/workfactory/credentials.env"
docker build -t workfactory/runtime:v2 docker
python3 -m unittest discover -s tests -v
```

在外部 credentials.env 中填写接口地址和密钥。配置模板中 runtime 路径用于固定文件工具，需要按本机安装填写。Docker 内的 execute_command 可以使用镜像自带的文档处理库。固定 XLSX 与 PPTX 工具还依赖本机 Artifact Tool，当前没有打包可移植安装流程，不可将本机路径复制到其他机器直接使用。

不得提交密钥、config/local.json 或运行数据。缺失依赖会报错，不自动更换模型或执行环境。

## 后台启动与查看

在代码目录运行以下命令。后台使用启动命令所对应的 Python，请使用已验证的解释器。

```bash
python3 service.py start \
  --config "$HOME/.config/workfactory/credentials.env" \
  --pipeline-config config/local.json \
  --output runs/multiformat-v2
python3 service.py status --output runs/multiformat-v2
python3 batch_report.py runs/multiformat-v2
```

只运行一个模型时，在 start 命令中追加相应参数。

```bash
--models deepseek-v4.1-flash-1017
```

后台日志保存在批次目录的 service.stdout.log、service.stderr.log 和各模型的 .log 文件。status 同时显示 launchd 的进程状态和管线状态文件。状态文件中的 running 必须结合进程状态与最新日志判断。

```bash
tail -f runs/multiformat-v2/deepseek-v4.1-flash-1017.log
python3 service.py stop --output runs/multiformat-v2
```

关闭聊天和终端不停止后台任务。电脑睡眠会暂停计算，关机或退出系统登录会话会终止服务。本版本不自动开机启动，也不无限重启失败批次。

## 中断后恢复

修复接口或环境问题后，先执行 stop，再对同一输出目录执行原来的 start 命令。已经完成的候选任务会跳过，通过校验的阶段会复用。

请求已保存但响应尚未保存时，可以从请求中的对话恢复。响应已保存而工具执行状态不明时，管线会停止并要求检查原始记录，避免重复执行写入。当前不保证任意工具执行中断都可无人值守恢复。

配置和任务清单发生变化时使用新的输出目录。失败尝试保留在原目录，不覆盖旧结果。不要在任务运行期间修改代码、配置或来源文件。

## 并发配置

config/local.json 中的 task_workers 控制每个模型同时执行的任务数，api_max_concurrency 控制同一密钥下每个模型的在途请求数。api_limit_scope 设为 model 时两个模型独立限流。

任务清单支持排队大量任务。64 或 1024 的 API 并发需要平台配额与实际压测支持，不代表本机可以同时启动相同数量的 Docker 容器。每个容器默认限制为 2 GB 内存与 1 CPU，先按可用内存设置任务并发。

限流通过单机文件锁实现，跨机器的统一队列、限流与资源调度尚未实现。同一输出目录有进程锁，重复启动不会复制同一模型批次。调整 API 并发前应先停止共享同一模型配额的进程。

## 输入与输出

config/cases.json 提供任务入口。目前五条仍是合成职业情境，需要真实职业、技能和交付物来源池才能开展论文级规模实验。

每个模型与任务单独保存。

```text
runs/<batch>/<model>/<task>/
  seed.json
  status.json
  attempt-01/
    materialization-00/
    repair-1/
    teacher_workspace/outputs/
    trajectory.json
```

trajectory.json 是教师候选轨迹。自动检查、人工验收与训练数据合格分别记录。长尾拒绝采样与训练 token 掩码尚未完成，不能直接宣称训练数据已验收。

## API 调用位置

- pilot.py 的 complete 负责模型请求、流式响应与有限重试
- model_clients.py 提供两个明确模型入口
- api_gate.py 控制跨进程的模型请求并发
- batch_generate.py 编排各阶段，并支持 stage_models 配置覆盖
- tool_runtime.py 驱动探针与教师的工具循环
- docs/API_AND_PIPELINE.txt 列出各阶段 API 输入输出与论文对应

真实检索服务尚未接入。external_retrieval 为 true 时明确报错。当前不使用 SerpAPI 替代未确定的 WorkFactory 检索实现。

## 验证边界

单元测试覆盖编排、工具访问边界、并发锁与后台任务配置。多格式文件已做本机生成与读回检查。后台独立进程验证不调用付费模型。本机首次验证被 macOS 拒绝访问 Documents。部署到 ~/workfactory-pipeline 后，launchd 在启动命令退出后独立完成测试脚本，退出码为 0。这验证了后台进程启动与文件访问，不代表付费模型全链路或高并发已通过。

新版 Docker 全链路、MiMo Flash 成功轨迹、多模型高并发吞吐、自动故障恢复仍需实际验证。旧 runs 中的 XLSX 试跑结果不能作为这些能力的验收证据。

## Linux 开发机独立批量运行

控制器使用 Python 标准库。Docker 模式下，文件处理全部通过容器中的 execute_command 完成，不依赖 Codex、macOS、本机 Artifact Tool 或本机 Office。

```bash
python3 run_models.py --config /absolute/path/credentials.env --pipeline-config config/pipeline.json --output runs/batch-001
```

可在开发机已有的 tmux 或作业调度器中启动该命令。service.py 仅用于 macOS。Linux 的后台进程管理由开发机的作业系统负责。

修改 task_workers 和 api_max_concurrency 设置每个模型的任务并发与请求并发。两组模型同时启动，组内按阶段顺序执行。先验证小批量，再依据平台限额和容器资源逐步增大。

## 三条多格式 DeepSeek 样例

config/multiformat-three.json 包含采购、项目管理、客服分析三个合成职业任务，分别要求 PDF、DOCX、PPTX、CSV、JSON 等资料和交付物。该配置用于验证多格式能力，不限制默认管线的格式选择。

```bash
python3 batch_generate.py --config /absolute/path/credentials.env --pipeline-config config/multiformat-three-policy.json --output runs/deepseek-multiformat-three --model deepseek-v4.1-flash-1017
```

该样例每个模型最多同时运行两个任务和两个模型请求。HTTP 429 与临时网关错误会有限重试，耗尽后保存错误。
