# Competition readiness audit

## Addressed in this review

- Exact machine costs now inform bounded candidate selection, including LRU spills, cache placement, issue width, memory ports, and branch fences. The optimizer compares safe variants using deterministic synthetic execution and can retain the original program.
- Candidate choice can omit hoisting, fusion, strength reduction, or global propagation, and can disregard profile layout. These choices address transformations whose local savings increase register pressure or perform poorly on other paths.
- Constant-address store forwarding removes provably redundant loads. Overwritten-store removal preserves memory at every possible intervening trap or observable operation.
- Liveness analysis now has a bound on aggregate set-processing work as well as iteration count. Large straight-line programs use a linear backward scan.
- Tests cover zero-initialized registers, signed corner cases, mutable registers, volatile ordering, trap-visible stores, alias invalidation, loop-carried values, zero-trip loops, deterministic selection, and invocation from another directory.
- The reproducible stress runner tests register renaming, block shuffling, novel machine costs and fused-feature flags, absent and misleading profiles, and different Python hash seeds.
- Runtime optimization uses only named command-line inputs and project source files. Synthetic probes are generated in memory; no benchmark answers, fingerprints, adjacent input files, network access, third-party optimizer frameworks, or solvers are used.

## Remaining limits that can affect ranking

- Candidate probes are a performance estimate. Hidden input paths can differ, and an individual run may regress even when the candidate is faster on the probes. All transformations must be correct independently of the probes.
- Register allocation colors whole virtual registers. Splitting live ranges, stronger copy coalescing and manual spill placement could improve programs with sustained register pressure.
- Global copy propagation, general alias analysis, partial redundancy elimination, loop unrolling and more extensive loop transformations are not implemented.
- Scheduling keeps memory and possible traps as barriers. It misses profitable load-latency hiding opportunities.
- Bounded passes intentionally skip large or complex programs. Runtime safety is prioritized over expensive optimization there.
- Passing sampled validation is not a formal proof. The transformed-program suite broadens the evidence but cannot cover every input.
- Linux CI is configured on Ubuntu 22.04. It has not been run from this macOS workspace; a clean Linux run remains a submission check.
- Publication and organizer access have not been configured. The final submission must be a repository containing the required top-level files and executable modes, committed before the deadline.

The measurements in BENCHMARKS.md describe supplied sample inputs. They are evidence of improvements, not a promise of a winning score.
