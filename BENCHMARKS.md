# Benchmark results

Measured locally on macOS ARM64 using the external COMP10 validator and the starter kit's exact timing implementation. These figures describe supplied sample inputs, not hidden-test performance.

- All 500 program/machine combinations passed external validation, requesting 100 generated inputs with a 50,000-step limit. The validator may skip original runs beyond that limit.
- Every optimizer invocation was repeated with identical output.
- 469 sample cases improved over their original programs, 31 were unchanged, and none regressed.
- Geometric-mean speedup across the 500 sample cases: 2.55x versus original programs, 1.008x versus the optimizer before this audit.
- Slowest measured optimizer invocation in the final sweep: 0.077 seconds locally.
- All 200 transformed cases passed validation on novel machines, with register renaming, shuffled blocks, absent/misleading profiles, and different Python hash seeds.
- All 18 targeted regression tests passed, including differential arithmetic checks across 100 generated programs.
- A synthetic 100,000-instruction arithmetic program reduced to two instructions in about 0.64 seconds locally. A synthetic 1,900-block graph optimized in about 0.11 seconds and passed validation.

| Machine | Improved over original | Unchanged |
|---|---:|---:|
| machine_default.cfg | 94 | 6 |
| machine_few_registers.cfg | 97 | 3 |
| machine_no_fused.cfg | 94 | 6 |
| machine_slow_memory.cfg | 94 | 6 |
| machine_wide_fast.cfg | 90 | 10 |

Candidate selection improves aggregate performance, but cannot guarantee every individual input. These sample cases regressed against the optimizer immediately before this audit:

| Machine | Program | Before audit | After audit |
|---|---|---:|---:|
| machine_few_registers.cfg | count_divisors.kir | 1153 | 1178 |

Reproduce with a separately downloaded starter kit:

```sh
python3 tests/benchmark.py /path/to/COMP10 --random 100 --max-steps 50000 --report /tmp/kopt-results.json
python3 tests/stress.py /path/to/COMP10
python3 -m unittest discover -s tests -v
```

No starter benchmarks are included in the submission. Linux CI is configured, but has not run from this macOS workspace. See AUDIT.md for remaining ranking and submission risks.
