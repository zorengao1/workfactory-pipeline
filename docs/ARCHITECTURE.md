# 代码地图

## 从哪里开始读

1. workfactory/__main__.py 解析用户选择的命令
2. workfactory/pipeline/batch_generate.py 调度一个批次的各阶段
3. workfactory/sources/ 准备来源、搜索技能和真实交付物
4. workfactory/clients/pilot.py 执行文字阶段及模型请求
5. workfactory/pipeline/planning_agent.py 规划信息图与参考文件
6. workfactory/runtime/tool_runtime.py 驱动构建、探针、修复与教师工具循环
7. workfactory/exports/ 整理环境、轨迹与报告

## 模块职责

| 模块 | 输入 | 输出与职责 |
|---|---|---|
| sources/source_pools.py | 来源配置、官方资料与职业筛选表 | 按四路标明路线的候选输入 |
| sources/skill_index.py | 本地技能索引、职业代码或锚点技能 | 锚点抽样、向量召回的候选技能及正文 |
| sources/skills_discovery.py | skill 与 mixed 路输入、候选技能 | 模型判断、技能组合、覆盖校验与审计记录 |
| sources/source_retrieval.py | 检索线索、已知 URL 或职业素材 | deliverable 与 mixed 路的真实交付物、正文和来源目录 |
| sources/download_transport.py | 下载 URL | 带完整性检查和重试的下载文件 |
| sources/pdf_extraction.py | PDF 原文件 | 原生正文或 OCR 正文 |
| sources/source_artifacts.py | 原文件目录与构建计划 | 全文读取、文件复用与一致性检查 |
| pipeline/contracts.py | 模块输入与模型结果 | 提示词渲染、结构校验与契约 |
| pipeline/planning_agent.py | 意图、素材与完整正文访问工具 | 通过检查和审核的信息图及文件规划 |
| pipeline/batch_generate.py | 来源清单、模型配置与并发策略 | 分阶段任务记录、环境与候选轨迹 |
| pipeline/pipeline_config.py | 策略和凭据配置 | 每阶段的模型、接口与运行参数 |
| clients/pilot.py | 模型请求 | 文本与工具调用响应、重试及流式收集 |
| clients/api_gate.py | 并发策略 | API 请求并发控制 |
| runtime/tool_runtime.py | 阶段提示词、文件和工具定义 | Agent 工具轨迹与结构化提交 |
| runtime/docker_runtime.py | 工作区与容器配置 | 隔离执行、只读输入和输出文件 |
| runtime/document_tool.py | 文档操作参数 | 文档创建和读回 |
| exports/harbor_export.py | 已构建的任务环境 | Harbor 指令、环境目录及构建文件 |
| exports/export_trace.py | 教师执行日志 | 教师候选轨迹 |
| exports/batch_report.py | 批次目录 | 状态汇总 |
| operations/ | 批次与模型列表 | 多模型运行和 macOS 后台任务 |
| experiments/ | 历史样例与实验目录 | 小样本回归，部分入口依赖历史运行资料 |

以上模块路径均相对于 workfactory/。

## 新旧命令对应

在仓库根目录运行。旧版根目录脚本已移动到包内，代码中使用包导入。

| 原命令 | 当前命令 |
|---|---|
| python3 batch_generate.py | python3 -m workfactory batch |
| python3 source_pools.py | python3 -m workfactory sources |
| python3 run_models.py | python3 -m workfactory models |
| python3 batch_report.py | python3 -m workfactory report |
| python3 harbor_export.py | python3 -m workfactory harbor |
| python3 export_trace.py | python3 -m workfactory trace |
| python3 service.py | python3 -m workfactory service |

参数保持原样。也可使用完整模块名，例如 python3 -m workfactory.sources.source_pools。

已有 launchd 后台任务保存了旧启动路径，更新仓库后应在原批次停止时重新注册。正在运行的批次应继续使用原检出目录，新代码使用新批次目录。

配置、提示词、Schemas、固定素材和输出仍以仓库根目录定位，由 workfactory/paths.py 统一处理。docs/archive/ 中的旧发布清单仅作历史记录，路径不代表当前布局。
