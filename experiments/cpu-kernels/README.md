# CPU kernel 实验

实验分支 `experiments/cpu-kernels` 基于已发布的 [v0.3.0](https://github.com/lw-liuwang/mathkernel/releases/tag/v0.3.0)。主分支保持通用工作流；这里保存具体任务、实现和结果。

当前已准备逐元素融合与矩阵乘分块的数学定义、规则、基线证明、C 基线、硬件标定和数值检查。完整输入、成本假设、目标、预算和测量方法见 [SPECIFICATION.md](SPECIFICATION.md)，等待用户确认后才开始候选优化。

## 已保留的材料

- `fusion/`、`matmul/`：任务 JSON、任务局部的 Lean 模型和基线证明。
- `baselines.c`、`check_baselines.py`：直接 C 基线及独立数值检查。
- `calibrate.c`、`calibrate.py`、`environment.json`：硬件标定程序、环境与原始样本。
- `preparation.json`：基线检查与规则加载结果；当前没有候选、性能比较或验收结论。

## 复现准备检查

从仓库根目录执行，沿用项目的 Lean 与绘图环境：

任务模型还需要固定 Mathlib 的 `Mathlib.Data.Rat.Defs` 模块缓存；缺失时，在 `lean/` 中运行 `.toolchain/bin/lake exe cache get Mathlib.Data.Rat.Defs`。

```bash
export TMPDIR=/home/wuti/github/tmp/mathkernel
export MPLCONFIGDIR="$TMPDIR/matplotlib"
mkdir -p "$TMPDIR/cpu-build"
.venv/bin/python experiments/cpu-kernels/calibrate.py --build-dir "$TMPDIR/cpu-build"
.venv/bin/python experiments/cpu-kernels/check_baselines.py --build-dir "$TMPDIR/cpu-build"
.venv/bin/python tools/mathkernel.py task check experiments/cpu-kernels/fusion
.venv/bin/python tools/mathkernel.py task check experiments/cpu-kernels/matmul
.venv/bin/python tools/mathkernel.py task rules experiments/cpu-kernels/fusion
.venv/bin/python tools/mathkernel.py task rules experiments/cpu-kernels/matmul
```

未确认时 `task check` 返回 `needs_confirmation`，退出码为 1，这是预期状态。重新标定只打印新记录，不覆盖已保存的任务参数；使用新参数需要更新规格并重新确认。
