import MathKernel.Cost

namespace MathKernel

structure Verified (t : Task) (baseline candidate : Plan) : Prop where
  equivalent : Equivalent t baseline candidate
  baselineFeasible : feasible t baseline = true
  candidateFeasible : feasible t candidate = true
  lowerEstimatedTime : estimatedSeconds t candidate < estimatedSeconds t baseline

structure ReportMatches (t : Task) (p : Plan) (f q peak ticks : Nat) : Prop where
  flops : (totalResources t p).flops = f
  hbmBytes : (totalResources t p).hbmBytes = q
  peakBytes : (totalResources t p).peakBytes = peak
  time : timeTicks t p = ticks

end MathKernel
