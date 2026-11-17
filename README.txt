WorkFactory 管线本地复现

当前版本
代码按论文的意图、信息图、环境构建、探针修复和教师执行组织。
文件数量和格式由任务规划决定。旧版两份 XLSX 限制已经移除。
模型可运行 Python 等代码，通过专属 Docker 容器操作多种业务文件。
固定文件工具另提供 XLSX、PDF、DOCX、PPTX、CSV、TSV、JSON 和文本读写。

重要状态
当前完整说明见 README.md，逐项实现状态见 docs/IMPLEMENTATION_STATUS.md。
Docker 运行环境及 GPT 三条混合来源任务已完成实际执行，候选轨迹仍待完整人工验收和训练整理。
真实输入已接入 BLS、O*NET、skills CLI 和 GPT 原生联网检索。默认 source_cases 使用来源池生成的清单。
格式规划已加入业务理由与 format_fitness 审核，本次提示词修改通过本地测试，尚未用新批次验证效果。
长尾拒绝采样、训练 token 掩码、按职业在线技能发现、稳定高并发等待完成项见实现状态清单。

入口
batch_generate.py 执行单模型的一批任务。
run_models.py 同时运行 DeepSeek V4.1 Flash 1017 与 MiMo V2.6 Flash。
model_clients.py 提供 call_deepseek 和 call_mimo 两个接口函数。
config/pipeline.json 配置阶段模型、任务并发、API 并发、文件格式和运行环境。
docs/API_AND_PIPELINE.txt 列出每个模型 API 调用点、论文对应和实现差异。
docker/Dockerfile 定义独立环境，默认工作镜像为 workfactory/runtime:v2。

准备
在外部目录保存 credentials.env，参考 config/credentials.env.example。
复制 config/pipeline.json 为 config/local.json，填写本机工具路径。
使用 docker build -t workfactory/runtime:v2 docker 构建专属镜像。
使用 python3 -m unittest discover -s tests -v 运行本地检查。

运行示例
python3 run_models.py --config /absolute/path/credentials.env --pipeline-config config/local.json --output runs/multiformat-v2
python3 batch_report.py runs/multiformat-v2

并发与资源
两个模型分别限流，task_workers 和 api_max_concurrency 可独立调整。
同一任务内部保持阶段顺序，多个任务并行。
大批量任务数取决于 source_cases 清单，清单不再写死在代码里。
单机文件锁负责多个进程共享模型配额，不提供跨机器全局限流。
1024 个任务可以排队；本机 Docker 容器并发必须依据资源设置。

结果位置
runs/批次/模型/任务/attempt-NN/trajectory.json 保存教师候选轨迹。
同目录 materialization-NN 保存各次文件构建与审查。
repair-N 保存修复、保留检查和新探针。
teacher_workspace/outputs 保存最终交付物。
各阶段目录保存请求、响应、工具结果和来源信息。
旧版试跑结果保留在 runs/dual-model-20261116，不能用新配置直接续写。

发布
只上传代码、配置模板、测试和说明。
密钥、config/local.json、runs、tmp、node_modules 均不上传。
历史实现说明保留在 docs/LEGACY_README.txt，仅用于理解旧试跑。
