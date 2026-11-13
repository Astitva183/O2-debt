# kopt

`kopt` optimizes programs written in Kiln IR (KIR). It requires Python 3.10 or newer and uses only the Python standard library.

```sh
./build.sh
./kopt input.kir --machine machine.cfg -o output.kir
./kopt input.kir --machine machine.cfg --profile input.prof -o output.kir
```

An optional profile guides block layout and never changes program semantics. The input, machine and profile paths are interpreted relative to the current directory. The tool may be invoked from any directory. It writes the output file specified by `-o`; errors go to standard error.

Run the standalone regression tests with:

```sh
python3 -m unittest discover -s tests -v
```

Use the separately obtained COMP10 starter kit's `kvalidate` and `ksim` to test additional programs and measure cycles. The starter kit's benchmarks, examples and machines are not included in this repository.

To reproduce the full practice-suite validation and sample-cycle benchmark with a separately downloaded starter kit:

```sh
python3 tests/benchmark.py /path/to/COMP10 --report /tmp/kopt-results.json
```

This checks all supplied program/machine combinations, repeats each optimizer invocation to check determinism, runs the external validator, and records sample cycle counts and optimizer runtime. The validator uses its configured step limit and may skip nonterminating or long-running original inputs.

Stress hidden-test variation with register renaming, shuffled blocks, novel machine parameters, and misleading profiles:

```sh
python3 tests/stress.py /path/to/COMP10
```

Small functions also use bounded deterministic synthetic execution to choose between safe optimization combinations. This reads no additional input files and writes only the requested output.
