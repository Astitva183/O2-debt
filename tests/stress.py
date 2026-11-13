#!/usr/bin/env python3
"""Test renamed/shuffled programs, novel machines, and misleading profiles."""
import argparse
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from kirlib import load_program, load_machine, SIGS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kit',type=Path)
    parser.add_argument('--variants',type=int,default=2)
    args=parser.parse_args(); rng=random.Random(93027); cases=0
    with tempfile.TemporaryDirectory() as temp:
        folder=Path(temp)
        for source in sorted((args.kit/'bench').glob('*.kir')):
            program=load_program(str(source))
            registers=set(program.params)
            for i in program.instrs: registers.update(v for t,v in i.args if t=='r')
            for variant in range(args.variants):
                mapping=dict(zip(sorted(registers),rng.sample(range(1000,999999),len(registers))))
                order=list(program.block_labels)
                tail=order[1:]; rng.shuffle(tail); order=order[:1]+tail
                blocks={b:[] for b in order}
                for b,i in zip(program.block_of,program.instrs): blocks[b].append(i)
                lines=['func transformed(%s)'%', '.join('v%d'%mapping[p] for p in program.params)]
                for b in order:
                    lines.append(b+':')
                    for i in blocks[b]:
                        operands=['v%d'%mapping[v] if t=='r' else str(v) for t,v in i.args]
                        lines.append('  '+i.op+' '+', '.join(operands))
                inp=folder/'input.kir'; out=folder/'out.kir'; machine=folder/'novel.cfg'; prof=folder/'wrong.prof'
                inp.write_text('\n'.join(lines)+'\n')
                mc=load_machine(str(args.kit/'machines'/'machine_default.cfg'))
                mc.update(registers=rng.choice([4,5,7,12,20]), issue_width=rng.choice([1,2,3,4]),
                          mem_ports=rng.choice([1,2]), reg_spill_penalty=rng.choice([0,1,7,20]),
                          taken_branch_penalty=rng.choice([0,1,5,12]), icache_size=rng.choice([8,32,128,1024]),
                          icache_penalty=rng.choice([0,1,4]), fused_mac=rng.randrange(2),fused_addsh=rng.randrange(2))
                for key in ('lat_alu','lat_mul','lat_div','lat_load','lat_mac','lat_addsh'): mc[key]=rng.randint(1,20)
                machine.write_text('\n'.join('%s = %d'%item for item in mc.items())+'\n')
                prof.write_text('\n'.join('edge %s %s %d'%(b,t,rng.choice([0,1,1000000]))
                    for b in order for i in blocks[b] for kind,t in i.args if kind=='l')+'\n')
                command=[str(ROOT/'kopt'),str(inp),'--machine',str(machine),'-o',str(out)]
                if variant%2: command+=['--profile',str(prof)]
                subprocess.run(command,check=True,capture_output=True,timeout=5)
                expected=out.read_bytes()
                # Hash randomization must not affect optimization decisions.
                env=dict(os.environ,PYTHONHASHSEED=str(variant+37))
                subprocess.run(command,check=True,capture_output=True,timeout=5,env=env)
                if expected!=out.read_bytes(): raise AssertionError('nondeterministic: '+source.name)
                checked=subprocess.run([sys.executable,str(args.kit/'kvalidate'),str(out),'--against',str(inp),
                    '--machine',str(machine),'--random','64','--seed',str(variant+977),'--max-steps','20000'],capture_output=True,text=True)
                if checked.returncode: raise AssertionError(source.name+'\n'+checked.stdout+checked.stderr)
                cases+=1
            if cases%20==0: print('passed %d transformed cases'%cases,flush=True)
    print('PASS: %d transformed cases on novel machines'%cases)
if __name__=='__main__': main()
