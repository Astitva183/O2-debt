#!/usr/bin/env python3
"""Run the external COMP10 validator and report sample cycle counts as JSON."""
import argparse
import glob
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from kirlib import load_program, load_machine, compile_program, load_input, execute, time_trace

def cycles(path, machine, sample):
    cp=compile_program(load_program(str(path)))
    result=execute(cp,sample.args,sample.segments,sample.vin,5000000,True)
    return None if result.status=='TIMEOUT' else time_trace(cp,result.trace,machine)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('kit',type=Path)
    p.add_argument('--random',type=int,default=100)
    p.add_argument('--max-steps',type=int,default=200000)
    p.add_argument('--baseline',type=Path)
    p.add_argument('--report',type=Path)
    args=p.parse_args(); rows=[]; failed=[]; begin=time.perf_counter()
    with tempfile.TemporaryDirectory() as temp:
        out=Path(temp)/'out.kir'
        for machine in sorted((args.kit/'machines').glob('*.cfg')):
            mc=load_machine(str(machine))
            for source in sorted((args.kit/'bench').glob('*.kir')):
                cmd=[str(ROOT/'kopt'),str(source),'--machine',str(machine),'-o',str(out)]
                profile=source.with_suffix('.prof')
                if profile.exists(): cmd+=['--profile',str(profile)]
                start=time.perf_counter()
                opt=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
                elapsed=time.perf_counter()-start
                if opt.returncode:
                    failed.append([machine.name,source.name,opt.stderr]); continue
                first=out.read_bytes()
                subprocess.run(cmd,capture_output=True,check=True,timeout=30)
                if first!=out.read_bytes(): failed.append([machine.name,source.name,'nondeterministic']); continue
                validation=subprocess.run([sys.executable,str(args.kit/'kvalidate'),str(out),'--against',str(source),
                    '--machine',str(machine),'--random',str(args.random),'--max-steps',str(args.max_steps)],capture_output=True,text=True)
                if validation.returncode:
                    failed.append([machine.name,source.name,validation.stdout+validation.stderr]); continue
                original=load_program(str(source)); sample=load_input(str(source.with_suffix('.in')),len(original.params))
                row={'machine':machine.name,'program':source.name,'optimizer_seconds':elapsed,
                     'original_cycles':cycles(source,mc,sample),'optimized_cycles':cycles(out,mc,sample)}
                if args.baseline:
                    old=args.baseline/(machine.name+'-'+source.name)
                    if old.exists(): row['baseline_cycles']=cycles(old,mc,sample)
                rows.append(row)
            print('finished '+machine.name,flush=True)
    summary={'cases':len(rows),'failures':failed,'seconds':time.perf_counter()-begin,
             'improved':sum(r['optimized_cycles']<r['original_cycles'] for r in rows if r['original_cycles'] is not None and r['optimized_cycles'] is not None),
             'regressed':sum(r['optimized_cycles']>r['original_cycles'] for r in rows if r['original_cycles'] is not None and r['optimized_cycles'] is not None),
             'max_optimizer_seconds':max((r['optimizer_seconds'] for r in rows),default=0)}
    print(json.dumps(summary,indent=2))
    if args.report: args.report.write_text(json.dumps({'summary':summary,'results':rows},indent=2)+'\n')
    return int(bool(failed))
if __name__=='__main__': sys.exit(main())
