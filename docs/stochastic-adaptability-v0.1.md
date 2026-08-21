# Stochastic Adaptability v0.1

This file is intentionally frozen after the stochastic-adaptability and adaptive-execution evidence pass.

See the preceding commit history and `native/adaptive_execution_bench.c` for the full measured packet. The central result remains:

- epoch/order guards preserve capability correctness under delayed, duplicated, stale and out-of-order evidence;
- static branch versus LUT performance changes with trajectory predictability;
- an online selector that measures a 512-transition prefix beat both branch-only and LUT-only on the two hosted runners in the long-regime mixed workload;
- the selector cost was included in the timed path;
- the stochastic epoch is still side metadata and is not claimed to fit in the current 16-bit temporal-capability word.

Next falsification target:

```text
tau_environment / tau_adaptation
```

Sweep regime duration and observation-window size to find the break-even point where the adaptive selector can no longer amortize its observation and switching cost.
