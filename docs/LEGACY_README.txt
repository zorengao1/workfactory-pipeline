WorkFactory 精简 prompt 包，首轮迭代版

本目录是依据论文设计的复现模板。字段、程序接口和合成试跑案例由本项目编写。
论文未提供这套完整模板，当前已接入限定文件能力的工具运行器，尚未完成端到端训练。

入口
prompts 包含十二份五区块模板
contracts.py 定义输出结构、格式检查和部分跨字段检查
schemas 包含由 contracts.py 导出的 JSON Schema
pilot.py 运行三路意图、意图审查和规划的小样本 API 试跑
fixtures/pilot_cases.json 包含三个明确标注来源的合成测试输入
runs 保存请求快照、原始回复、解析结果、检查结果、模型标识和用量
REPORT.txt 记录当前验证状态及未完成项
CHANGELOG.json 记录每项规则修改的依据，包含撤回的过度约束

阶段连接
01a / 01b / 01c → 02 → 03 → 04 → 05 → 06
06 存在阻断 → 07 → 05 与 08 → 新的 06
06 无阻断 → 独立 09 → 程序过滤 → 选中长轨迹时进行 10

输入约定
每阶段输入只允许 contracts.py 的 STAGES 中列出的字段和 task_id。
意图和计划传递成功响应中的 result，外层状态保留在运行记录中。
原始输入资料、参考文件及工具输出都按数据处理。
规划节点的 value 与 construction_spec 分别表示既定值和待生成材料规格。
supplied 节点二者恰好提供一项，derived 与 internal 节点两项均为空。
construction_spec 必须在构建阶段生成实际数据后，才能作为求解输入。
environment 只包含 user_request、reference_files、resources。
workspace 由未来执行框架提供隔离目录和工具能力，文本过滤不能代替实际文件权限隔离。
probe 和 teacher 的工作区不得挂载内部计划、诊断、前次答案和评审反馈。
修复者能访问初始规划用于保留工作，初始规划保持不可变。

输出约定
所有阶段只返回一个 JSON 对象。
status 使用 ok、blocked、rejected。
ok 表示当前步骤完成，审查是否通过由 result.verdict 决定。
blocked 和 rejected 的 result 为 null，issues 至少包含一个具体原因。
审查结果与探测结果不能用作整个任务完全正确的证明。
规划的语义有效性仍需独立审查与实际执行。

模型与密钥
运行时配置保存在仓库外，权限为仅文件所有者读写。
运行记录保存模型名称及响应，不保存密钥。
首轮使用用户指定模型，不做自动模型切换，不修补非法 JSON，不隐藏首次失败。

论文控制规则
初次环境构建最多额外重试三次。
环境修复最多三轮，修复后的检查失败即丢弃。
探测只因 blocker 触发修复，其他严重程度保留在报告中。
教师轻量过滤与最长百分之五拒绝采样由程序决定。
拒绝采样固定基准交付物，最多四次教师尝试，每次使用干净沙箱。
训练序列过滤和失败工具调用 loss mask 属于数据预处理。
文本试跑程序仅覆盖意图与规划。文件构建与审查的实际执行由 environment_pilot.py 接入，完整循环仍在逐步验证。

长度策略
人工模板只保留五块，不重复堆叠质量形容词。
机器输出结构单独维护，发送请求时装配到输出格式区块中。
复杂规划的完整字段定义比简单评审更长，实际发送长度保存在检查报告中。
首轮不加通用 few-shot 示例，针对真实出现的错误再添加。
曾测试的严格意图漏项门槛已撤回，详见 CHANGELOG.json 中 DESIGN-001。
意图阶段允许规划继续补充实例细节，审查明确违反资源或合成权限的任务。

验证边界
静态检查仅验证模板和程序约束。
三个合成案例只测试意图到规划的接口，不替代真实来源收集。
API 试跑通过仅代表观察到格式和部分结构约束通过。
文件生成、探测执行、修复有效性、教师独立求解需后续工具运行验证。

证据来源
WorkFactory 附录 A、B、C、D.3、E.2
本地原文位于 /Users/zoren_gao/Documents/research/【26-11】Workfactory.pdf
EnvScaler 的分阶段生成、固定格式和示例写法
Terminal-Universe 公开模板的输出约束、证据及拒绝分支

运行
python3 contracts.py
python3 -m unittest discover -s tests -v
python3 pilot.py --config ~/.config/workfactory/runtime.env --output runs/pilot-v0

后续复测入口
python3 final_pilot.py --config ~/.config/workfactory/runtime.env --output runs/final-pilot-next
输出目录必须使用新名称。接口已恢复，最近完成记录见 runs/final-pilot-v2。

实际文件试跑
environment_pilot.py 串接已保存规划、文件构建、只读构建审查和独立探针。
tool_runtime.py 为每阶段建立新的对话，通过固定文件工具限制可见目录和可写路径。
workbook_tool.mjs 使用本机捆绑的 Artifact Tool 创建、检查和渲染 XLSX。
模型没有宿主机 shell 或任意代码执行工具，未向模型提供 Docker 执行。
当前实现属于文件能力隔离，Docker 可用性检查不代表已执行容器隔离测试。
探针使用独立目录副本，只有 outputs 可写，原始计划与调用日志保存在外部。
模型凭据只由控制器读取，不进入工作目录或模型工具消息。
每轮保存输入哈希、请求、原始响应、工具结果、文件哈希及格式检查结果。
具体完成状态见 REPORT.txt 和 runs/environment-pilot-v1/summary.json。

工具阶段通过 submit_result 提交原有 JSON 结果结构。首次失败保留，不从说明文字或围栏中提取 JSON。
当前已通过十九项本地检查，覆盖结构化提交、目录越界和只读输入。

PROMPT_RULES.txt 汇总本轮错误驱动的写作规则。
continue_environment.py 执行最多三轮修复、双重审查、重新探测与独立教师试跑。
repair_negative_pilot.py 通过副本中删除权限表验证探针和修复分支。
结构化提交中的非法字段由执行器返回错误，模型显式修正，原始调用不会被覆盖。
教师成功提交需验证交付物在最近一次写入后实际重读。数字格式采用明确取值，禁止把 wrap 或 bold 当作数字格式。

export_trace.py 导出包含实际工具交互的原始教师候选轨迹，同时标记失败调用。未做 tokenizer 编码和 SFT loss mask，不标记为可直接训练。
