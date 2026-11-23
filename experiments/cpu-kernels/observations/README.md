# 准备阶段观察

`NoncomputableModel.lean` 是一个预期编译失败的最小复现，不是待验收的 kernel 任务。
它用实数平方定义 `Model`，随后通过当前 CLI 相同的 `#eval` 路径读取资源报告。
Lean 会拒绝编译评价表达式，因为它依赖 `noncomputable` 模型。

在固定 Lean 4.24.0、Mathlib 环境中，准备 `Mathlib.Data.Real.Basic` 模块缓存后，从 `lean/` 运行：

```bash
.toolchain/bin/lake env lean ../experiments/cpu-kernels/observations/NoncomputableModel.lean
```

观察到退出码 1，主要错误为：

```text
error(lean.dependsOnNoncomputable): failed to compile definition, consider marking it as 'noncomputable' because it depends on 'realModel', which is 'noncomputable'
```

这说明当前工作流不能直接采用这种实数模型定义。首轮任务改用可计算的精确有理数语义，并独立检查 FP64 实现。若后续需要支持这类实数模型，应另行设计资源评价与非可计算语义之间的接口；本轮不修改已发布的通用工具。
