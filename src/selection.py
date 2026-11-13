"""Deterministic, bounded selection among independently safe transformations."""
import math
from kirlib import (parse_program, compile_program, execute, time_trace,
                    generate_inputs, first_difference, check_machine_features, KirError)
from optimizer import optimize


def select(prog, machine, profile, original):
    primary=optimize(prog,machine,profile)
    # Large inputs keep a single linear/bounded optimization pipeline.
    if len(prog.instrs)>1000 or len(prog.block_labels)>100: return primary
    candidates=[primary]
    for settings in ({'hoist':False}, {'fusion':False},
                     {'hoist':False,'fusion':False,'strength':False,'global_value':False}):
        candidate=optimize(prog,machine,profile,**settings)
        if candidate is not None and candidate not in candidates: candidates.append(candidate)
    try:
        check_machine_features(prog,machine)
        if original not in candidates: candidates.append(original)
    except KirError:
        pass
    if len(candidates)==1: return primary
    if profile:
        unprofiled=optimize(prog,machine,None)
        if unprofiled is not None and unprofiled not in candidates: candidates.append(unprofiled)
    reference=compile_program(prog)
    inputs=generate_inputs(len(prog.params),48,730201)
    probes=[]
    for index in (0,1,3,8,15,20,35,43):
        inp=inputs[index]
        result=execute(reference,inp.args,inp.segments,inp.vin,4000,True)
        if result.status!='TIMEOUT':
            probes.append((inp,result,time_trace(reference,result.trace,machine)))
    if not probes: return primary
    best=primary; best_score=None
    for candidate in candidates:
        if candidate is None: continue
        parsed=parse_program(candidate)
        check_machine_features(parsed,machine)
        compiled=compile_program(parsed); score=0.0; valid=True
        for inp,expected,baseline in probes:
            actual=execute(compiled,inp.args,inp.segments,inp.vin,min(8000,expected.steps*4+100),True)
            if actual.status=='TIMEOUT' or first_difference(expected,actual) is not None:
                valid=False; break
            score+=expected.steps*math.log(time_trace(compiled,actual.trace,machine)/baseline)
        if valid and (best_score is None or score<best_score-1e-12):
            best=candidate; best_score=score
    return best
