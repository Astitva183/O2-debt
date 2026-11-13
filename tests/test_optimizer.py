import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from kirlib import parse_program, compile_program, execute, first_difference, check_machine_features
from optimizer import optimize

MACHINE = dict(registers=4, reg_spill_penalty=5, fused_mac=1, fused_addsh=1,
               lat_mac=3, lat_addsh=1, lat_mul=3, lat_alu=1,
               issue_width=2, icache_size=64, icache_penalty=2, taken_branch_penalty=2)

class OptimizerTests(unittest.TestCase):
    def check_program(self, source, inputs, machine=MACHINE):
        original = parse_program(source)
        output = optimize(original, machine)
        optimized = parse_program(output)
        check_machine_features(optimized, machine)
        a, b = compile_program(original), compile_program(optimized)
        for args in inputs:
            before = execute(a, args, [(0, [17, 31, 73])], {0: [3, 5]}, 10000)
            after = execute(b, args, [(0, [17, 31, 73])], {0: [3, 5]}, 10000)
            self.assertIsNone(first_difference(before, after), (source, output, args))
        return output

    def test_signed_and_shift_semantics(self):
        self.check_program('''func f(v0, v1)
entry:
  div v2, v0, v1
  mod v3, v0, v1
  shl v4, v2, v1
  lt v5, v3, v0
  add v6, v4, v5
  ret v6
''', [[x,y] for x in (0, 1, 0xffffffff, 0x80000000) for y in (0,1,2,32,0xffffffff)])

    def test_traps_stores_and_volatile_reads(self):
        self.check_program('''func f(v0)
entry:
  vload v1, 0
  store 1, v1
  vload v2, 0
  div v3, 9, v0
  vstore 0, v3
  ret v2
''', [[0], [1], [0xffffffff]])

    def test_alias_and_load_trap(self):
        self.check_program('''func f(v0, v1)
entry:
  load v2, v0
  store v1, 44
  load v3, v0
  add v4, v2, v3
  ret v4
''', [[x,y] for x in (0,1,4095,4096) for y in (0,1,4096)])

    def test_fused_lowering_destination_alias(self):
        machine = dict(MACHINE, fused_mac=0, fused_addsh=0)
        result = self.check_program('''func f(v0, v1)
entry:
  mac v0, v0, v1, v0
  addsh v1, v1, v0, 3
  ret v1
''', [[0,1], [2,3], [0xffffffff, 0x80000000]], machine)
        self.assertNotIn('  mac ', result)
        self.assertNotIn('  addsh ', result)

    def test_loop_carried_and_initial_zero_registers(self):
        self.check_program('''func f(v0, v1)
entry:
  mov v2, v0
  jmp loop
loop:
  add v3, v3, v2
  sub v2, v2, 1
  eq v4, v2, 0
  br v4, exit, loop
exit:
  add v5, v3, v1
  ret v5
''', [[1,3], [2,7], [10, 0xffffffff]])

    def test_repeated_load_and_reassignment(self):
        result = self.check_program('''func f(v0)
entry:
  load v1, v0
  load v2, v0
  add v3, v1, v2
  ret v3
''', [[0], [4095], [4096]])
        self.assertEqual(result.count('  load '), 1)

    def test_loop_invariant_is_hoisted_and_zero_trip_is_safe(self):
        source = """func f(v0, v1, v2)
entry:
  jmp header
header:
  br v0, body, done
body:
  mul v3, v1, v2
  vstore 0, v3
  sub v0, v0, 1
  jmp header
done:
  ret v3
"""
        result = self.check_program(source, [[0,7,8], [1,7,8], [4,0xffffffff,3]])
        self.assertIn('mul ', result.split('header:')[0])

    def test_loop_varying_values_are_not_hoisted(self):
        source = """func f(v0, v1)
entry:
  jmp header
header:
  br v0, body, done
body:
  mul v2, v0, v1
  vstore 0, v2
  sub v0, v0, 1
  jmp header
done:
  ret v2
"""
        result = self.check_program(source, [[0,3], [1,3], [3,7]])
        self.assertNotIn('mul ', result.split('header:')[0])

    def test_profile_layout_respects_entry_and_equivalence(self):
        from advanced import profile_layout
        from kirlib import Instr
        blocks = {'entry':[Instr('br',[('r',0),('l','cold'),('l','hot')],0,'')],
                  'cold':[Instr('ret',[('i',1)],0,'')],
                  'hot':[Instr('ret',[('i',2)],0,'')]}
        order=['entry','cold','hot']
        self.assertEqual(profile_layout(blocks,order,[('entry','hot',100),('entry','cold',1)],MACHINE),
                         ['entry','hot','cold'])
        source = """func f(v0)
entry:
  br v0, cold, hot
cold:
  ret 1
hot:
  ret 2
"""
        original=parse_program(source)
        optimized=parse_program(optimize(original,MACHINE,[('entry','hot',100)]))
        for arg in (0,1):
            a=execute(compile_program(original),[arg],[],{},100)
            b=execute(compile_program(optimized),[arg],[],{},100)
            self.assertIsNone(first_difference(a,b))

    def test_scheduler_preserves_dependencies_and_improves_latency(self):
        from advanced import schedule
        p=parse_program("""func f(v0, v1)
entry:
  mul v2, v0, v1
  add v3, v2, 1
  mul v4, v0, v0
  add v5, v3, v4
  ret v5
""")
        scheduled=schedule(p.instrs,MACHINE)
        self.assertEqual([i.op for i in scheduled], ['mul','mul','add','add','ret'])

    def test_global_constants_preserve_loop_initial_values(self):
        source="""func f(v0)
entry:
  const v1, 7
  jmp header
header:
  br v0, body, done
body:
  add v2, v1, 3
  vstore 0, v2
  sub v0, v0, 1
  jmp header
done:
  ret v2
"""
        self.check_program(source,[[0],[1],[5]])

    def test_global_join_keeps_different_values(self):
        self.check_program("""func f(v0)
entry:
  br v0, left, right
left:
  const v1, 7
  jmp join
right:
  const v1, 9
  jmp join
join:
  ret v1
""",[[0],[1],[0xffffffff]])

    def test_randomized_arithmetic_differential(self):
        import random
        rng=random.Random(731)
        for _ in range(100):
            lines=['func f(v0, v1)','entry:']
            for _ in range(30):
                op=rng.choice(['add','sub','mul','and','or','xor','shl','shr','lt','eq','div','mod'])
                a='v%d'%rng.randrange(8)
                b=rng.choice(['v%d'%rng.randrange(8), str(rng.choice([0,1,2,32,0xffffffff]))])
                lines.append('  %s v%d, %s, %s'%(op,rng.randrange(8),a,b))
            lines.append('  ret v%d'%rng.randrange(8))
            self.check_program('\n'.join(lines),[[rng.getrandbits(32),rng.getrandbits(32)] for _ in range(10)])

    def test_cli_from_another_directory(self):
        import subprocess
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            machine=dict(MACHINE, mem_ports=1, lat_load=4, lat_div=12)
            (folder/'m.cfg').write_text('\n'.join('%s = %s'%item for item in machine.items()))
            (folder/'in.kir').write_text('func f(v0)\nentry:\n  add v1, v0, 0\n  ret v1\n')
            executable=str(Path(__file__).resolve().parents[1]/'kopt')
            command=[executable,'in.kir','--machine','m.cfg','-o','out.kir']
            subprocess.run(command,cwd=temp,check=True,capture_output=True)
            first=(folder/'out.kir').read_bytes()
            subprocess.run(command,cwd=temp,check=True,capture_output=True)
            self.assertEqual(first,(folder/'out.kir').read_bytes())
            self.assertEqual({f.name for f in folder.iterdir()},{'m.cfg','in.kir','out.kir'})
            self.assertEqual(parse_program(first.decode()).instrs[-1].op,'ret')

    def test_store_forwarding_and_overwritten_stores(self):
        result=self.check_program("""func f(v0)
entry:
  store 3, 7
  store 3, v0
  load v1, 3
  ret v1
""",[[0],[123],[0xffffffff]])
        self.assertEqual(result.count('  store '),1)
        self.assertNotIn('  load ',result)

    def test_store_deletion_respects_traps(self):
        result=self.check_program("""func f(v0)
entry:
  store 3, 7
  div v1, 1, v0
  store 3, 9
  ret v1
""",[[0],[1]])
        self.assertEqual(result.count('  store '),2)

    def test_store_forwarding_invalidates_modified_value(self):
        self.check_program("""func f(v0)
entry:
  store 3, v0
  add v0, v0, 1
  load v1, 3
  add v2, v0, v1
  ret v2
""",[[0],[17],[0xffffffff]])

    def test_selection_preserves_trapping_program(self):
        from selection import select
        source="""func f(v0)
entry:
  store 3, 7
  div v1, 31, v0
  ret v1
"""
        # Selection needs a full target configuration for its exact timing model.
        machine=dict(MACHINE,mem_ports=1,lat_load=4,lat_div=12)
        original=parse_program(source)
        candidate=parse_program(select(original,machine,[],source))
        for value in (0,1,3,0xffffffff):
            a=execute(compile_program(original),[value],[],{},100)
            b=execute(compile_program(candidate),[value],[],{},100)
            self.assertIsNone(first_difference(a,b))

if __name__ == '__main__': unittest.main()
