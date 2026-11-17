# 命令迁移

根目录的 Python 入口已归入 `workfactory/`。旧脚本名不再作为根目录文件保留，参数沿用原有定义。统一入口在仓库根目录执行，无需安装 Python 依赖。

| 原命令 | 新命令 |
|---|---|
| `python3 source_pools.py` | `python3 -m workfactory sources` |
| `python3 batch_generate.py` | `python3 -m workfactory generate` |
| `python3 run_models.py` | `python3 -m workfactory run-models` |
| `python3 service.py` | `python3 -m workfactory service` |
| `python3 batch_report.py` | `python3 -m workfactory report` |
| `python3 export_trace.py` | `python3 -m workfactory export` |
| `python3 scripts/audit_run.py` | `python3 -m workfactory audit` |
| `python3 scripts/watch_run_report.py` | `python3 -m workfactory watch` |
| `python3 scripts/resume_failed_case.py` | `python3 -m workfactory resume` |
| `python3 scripts/prepare_mixed_inputs.py` | `python3 -m workfactory prepare-mixed` |
| `python3 scripts/check_environment.py` | `python3 -m workfactory check-environment` |
| `python3 scripts/check_source_inputs.py` | `python3 -m workfactory check-sources` |

已有调度器或自定义脚本应同步更新命令。后台服务使用当前分支显式启动后才会使用新入口，已启动的服务不会自动迁移。

原 `pilot.py` 的试验入口可通过 `python3 -m workfactory.models.client` 使用。其他历史试验归入 `workfactory.experiments`，不属于正式批次入口。

此次保留文件状态格式、模型参数和生成策略。源代码路径及其哈希发生变化，新批次应使用新输出目录。

历史 `finalize_pilot.py` 还依赖未随仓库发布的 `audit_invoice_case` 和指定试验输出，保留于 `workfactory/experiments/finalize.py`。该历史脚本未纳入本次正式入口验证。
