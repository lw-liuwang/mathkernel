# MathKernel

为 agent 提供数学变换工作流：收集用户的计算需求与资源信息，检查任务是否完整，多轮评价和证明候选，并交付可重新验收的优化计算方案。

工作流面向已有或新的 kernel，也适用于合并与切分。用户确认数学规格、执行与成本模型、基线、目标和预算；agent 按这些依据提出候选。缺少信息时先协助用户补充，只有得到授权才能代为补充定义或假设。Lean 检查确认模型内的数学正确性、资源可行性和目标改进。

主分支提供通用实验工作流与验收工具。每个实验在自己的任务目录提供数学定义、执行与成本规则以及证明；agent 只能在用户授权后协助补充这些内容。产出包包含结构化方案、前后公式、执行伪代码、Roofline PNG、成本对比及证明材料。

## 开始使用

Python 工具使用标准库，需要 Python 3.11 或更新版本。形式化验证使用固定版本 Lean 4.24.0 和匹配的 Mathlib。

```bash
git clone https://github.com/lw-liuwang/mathkernel.git
cd mathkernel
```

在 Linux x86_64 上，使用 Python 3.14 执行本地安装：

```bash
python3 tools/setup_lean.py
```

安装脚本需要 `curl`、`git` 和 C 编译器。它下载并核对 Lean 工具链，安装到本地缓存，准备固定版本 Mathlib 源码及依赖，然后构建通用证明契约。缓存默认放在项目的 `.cache/mathkernel` 中，也可以通过 `--cache-dir` 或环境变量 `TMPDIR` 指定位置。工具链下载约 440 MiB，Mathlib 还需要额外存储。

如果已有相同版本的 Lean 环境，可用 `MATHKERNEL_LAKE` 指定 `lake` 可执行文件，然后在 `lean/` 中准备固定依赖并构建通用证明契约。安装脚本适用于本机 Linux；其他平台需要自行准备匹配的 Lean 环境。

实验需要额外的 Mathlib 模块时，在 `lean/` 中用 `lake exe cache get MODULE` 获取相应预编译缓存，模块由实验定义确定。

绘图使用 Matplotlib，安装到项目环境后，用该环境的 Python 执行工作流：

```bash
export TMPDIR="$PWD/.cache"
mkdir -p "$TMPDIR"
export UV_CACHE_DIR="$TMPDIR/uv-cache"
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements-plot.txt
.venv/bin/python tools/mathkernel.py doctor
```

`doctor` 检查 Python、固定版本 Lean、证明契约构建和 PNG 导出，返回缺失项和处理建议。Lean 安装所需的 Python 3.14 与运行 CLI 的 Python 可以不同。

## 让 agent 工作

给 agent 仓库位置和计算需求：

> 阅读 `skills/optimize-mathkernel/SKILL.md`，按 `workflows/prove-improvement.md` 完成数学变换。先帮助我整理输入条件、计算资源、基线、目标与预算；缺少信息时询问我，代为补充前取得授权，补充完成后交我确认。多轮迭代后交付通过验收的优化计算方案。

主要命令从仓库根目录运行，任务目录可以放在项目以外：

```bash
.venv/bin/python tools/mathkernel.py task init /path/to/task
.venv/bin/python tools/mathkernel.py task check /path/to/task
```

Agent 按检查结果补齐 `task.json` 和任务目录中的 Lean 定义。用户确认后记录其实际决定，再提出候选：

```bash
.venv/bin/python tools/mathkernel.py task confirm /path/to/task --by '<确认人>' --note '<用户实际确认内容>'
.venv/bin/python tools/mathkernel.py task evaluate /path/to/task /path/to/candidate.json
.venv/bin/python tools/mathkernel.py task verify /path/to/task ITERATION_ID
.venv/bin/python tools/mathkernel.py task status /path/to/task
```

使用评价返回的真实迭代 ID。`evaluate` 保存尝试和模型评价，`verify` 检查完整 Lean 证明；失败可以根据日志修改候选或证明。任务依据改变后，旧确认和证据不能继续用于新任务验收。

选定符合目标的候选后：

```bash
.venv/bin/python tools/mathkernel.py task accept /path/to/task ITERATION_ID
.venv/bin/python tools/mathkernel.py task export /path/to/task ITERATION_ID --output /path/to/new-bundle
.venv/bin/python tools/mathkernel.py task accept /path/to/new-bundle
```

验收重新运行评价与证明，并生成图和报告；导出还会在独立产出目录再次验收。只有 `acceptance_status: accepted` 且退出码为 0，才能交付为已验收成果。预算内没有合格候选时，交付工作目录、已探索范围及未解决项。

输入格式、新模型接入、授权记录和验收状态见 [任务协议](docs/tasks.md)。本地与远端 CI 使用同一组命令。

## 验收依据

Lean 检查基线和候选符合确认后的数学规格、满足资源约束、报告计数匹配，以及任务指定的目标改进成立。规格与成本规则由实验提供，用户确认其含义和假设。证明只允许基础逻辑公理，拒绝 `sorry` 或额外假设代替结论。

公共 Roofline 工具根据实验报告的 FLOP、搬运字节、快速存储峰值和硬件参数生成 PNG 与坐标数据。图与方案、证明、成本报告一起通过 `task accept` 检查。具体计算的计数规则需要在实验定义中说明。

## 从 v0.1.0 升级

v0.2.0 统一使用 `doctor` 和 `task ...`，移除原顶层 `inspect`、`evaluate`、`verify`、`report`、`roofline` 命令，以及随仓库提供的 kernel 模型和示例。已有脚本需改用任务工作目录，提供自己的模型与证明，并经过任务确认和验收。

## 开发检查

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖任务补充与确认、版本变更、迭代预算、成本与容量、成功和失败证明，以及任务自带定义的产出包导出和独立验收。在绘图环境中执行相同命令，还会检查 PNG 导出。没有对应依赖时，相关集成检查会显式跳过。

## 许可证

[MIT](LICENSE)
