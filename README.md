# MathKernel

为 agent 提供数学计算方案的评价工具、优化 skill 和证明工作流。agent 提出候选，Lean 检查数学等价、硬件可行性及指定成本模型下的耗时改进。

第一版支持三个实数矩阵的结合顺序与分块选择，使用单设备、两级存储的 Roofline 理想耗时模型。候选可以增加某项资源消耗，只要满足约束且目标耗时降低。

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

安装脚本需要 `curl`、`git` 和 C 编译器。它下载并核对 Lean 工具链，安装到本地缓存，拉取固定版本 Mathlib 及所需模块的预编译缓存，然后构建模型。缓存默认放在项目的 `.cache/mathkernel` 中，也可以通过 `--cache-dir` 或环境变量 `TMPDIR` 指定位置。工具链下载约 440 MiB，Mathlib 还需要额外存储。

如果已有相同版本的 Lean 环境，可用 `MATHKERNEL_LAKE` 指定 `lake` 可执行文件，然后在 `lean/` 中更新依赖、获取缓存并构建。安装脚本适用于本机 Linux；其他平台需要自行准备匹配的 Lean 环境。

从项目根目录运行：

```bash
python3 tools/mathkernel.py inspect examples/matmul-chain/task.json
python3 tools/mathkernel.py evaluate examples/matmul-chain/task.json examples/matmul-chain/candidate.json
python3 tools/mathkernel.py verify examples/matmul-chain/task.json examples/matmul-chain/candidate.json
```

`evaluate` 仅提供快速评价。`verify` 会调用 Lean，并把具体输入、实例证明、日志和结果保存到 `runs/`。只有退出码为 0 且 `verification_status` 为 `verified`，才能报告已经证明改进。

使用输出中的真实运行目录生成报告：

```bash
python3 tools/mathkernel.py report runs/RUN_ID/result.json
```

报告命令展示已有结果，不重新检查证明。使用运行目录中的 `task.json` 和 `candidate.json` 可以重新运行验证。

## 让 agent 工作

给 agent 项目工作目录、任务文件和以下指令即可：

> 阅读 `skills/optimize-mathkernel/SKILL.md`，按 `workflows/prove-improvement.md` 优化 `examples/matmul-chain/task.json`。提出并评价候选，提交至少一个通过 Lean 验证的改进方案；交付成本比较和证明产物。保持任务规格、硬件模型与基线不变。

agent 决定候选和迭代策略，命令行接口负责评价与检查。已有结合律的证明由工具自动实例化；扩展支持的数学变换时，补充 Lean 定理和成本规则。

## 输入、输出与评价目标

任务 JSON 包含三个矩阵形状、硬件参数、固定模型名称和基线。候选 JSON 只包含结合顺序与分块：

```json
{"order": "right", "tile": {"m": 64, "n": 64, "k": 64}}
```

`left` 表示 `(AB)C`，`right` 表示 `A(BC)`。三个块共享快速存储；每次 GEMM 的维度都必须被对应块大小整除。模型及计数规则见 [docs/model.md](docs/model.md)。

优化目标是各次顺序 GEMM 的理想耗时之和：

$$
\widehat T(P;H)=\sum_g\max\left(\frac{F_g}{P_{\max}},\frac{Q_g}{B_{\max}}\right).
$$

工具分别记录计算量、显存搬运量、快速存储峰值和估计时间，使用精确整数及有理数比较。示例采用合成硬件参数。

| 示例指标 | 基线 `(AB)C` | 候选 `A(BC)` |
| --- | ---: | ---: |
| 计算量（FLOP） | 268,435,456 | 16,777,216 |
| 显存搬运（字节） | 21,233,664 | 1,327,104 |
| 快速存储峰值（字节） | 49,152 | 49,152 |
| 模型耗时 | 21.233664 µs | 1.327104 µs |

示例模型耗时比为 16。

## Roofline 图

![示例的 Roofline 位置与模型耗时](docs/figures/matmul-chain-roofline.png)

当前示例的硬件拐点为 100 FLOP/Byte。两个方案整体都位于约 12.642 FLOP/Byte、12.642 TFLOP/s，处于带宽受限区。图中同时标出每次 GEMM 与完整方案；相同坐标用蓝色圆环和橙色叉号重叠显示。

这次重新结合将计算量和显存搬运量同时降为基线的 1/16，因此算术强度和模型吞吐率保持相同，而完成任务的模型耗时从 21.233664 µs 降至 1.327104 µs。右侧耗时图展示这个差别。

绘图依赖单独安装到项目虚拟环境：

```bash
export TMPDIR="$PWD/.cache"
mkdir -p "$TMPDIR"
export UV_CACHE_DIR="$TMPDIR/uv-cache"
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements-plot.txt
.venv/bin/python tools/mathkernel.py roofline examples/matmul-chain/task.json examples/matmul-chain/candidate.json --output docs/figures/matmul-chain-roofline
```

命令导出 [PNG](docs/figures/matmul-chain-roofline.png) 和[坐标数据](docs/figures/matmul-chain-roofline.json)。横坐标为 FLOP/Byte，纵坐标为各方案自身运算量除以模型耗时。完整方案的耗时是各次 GEMM 耗时之和。

## 形式化验证

Lean 检查候选和基线对所有对应形状的实数矩阵输出相同、两个方案满足资源约束、模型耗时严格下降，以及 Python 报告计数与 Lean 成本解释器一致。证明只允许基础逻辑公理，拒绝 `sorry` 或额外假设代替结论。

数学原语、硬件参数和资源计数的定义集中在 [模型规格](docs/model.md)。

验证状态包括 `verified`、`proof_failed`、`timeout`、`unavailable`、`untrusted_proof`；输入错误返回 `invalid_input`。实现与整体设计的关系见 [逻辑图](docs/logic-map.md)。

## 开发检查

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖输入边界、成本、硬件容量、成功证明和错误证明。在绘图环境中执行相同命令，还会检查 PNG 导出。没有对应依赖时，相关集成检查会显式跳过。

## 许可证

[MIT](LICENSE)
