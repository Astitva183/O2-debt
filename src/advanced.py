"""Bounded machine-aware transformations for KIR."""
from collections import deque
from kirlib import SIGS, Instr, LATKEY

PURE = {'const','mov','add','sub','mul','and','or','xor','shl','shr','lt','eq','select','mac','addsh'}

def reads(i):
    return {v for k, (t,v) in zip(SIGS[i.op],i.args) if k == 's' and t == 'r'}

def dest(i):
    return i.args[0][1] if SIGS[i.op][0] == 'd' else None

def succ(block):
    i=block[-1]
    return [a[1] for a in i.args if a[0]=='l']

def hoist_loops(blocks, order, machine, params):
    if len(order)>250 or sum(map(len,blocks.values()))>4000: return
    preds={b:set() for b in order}
    for b in order:
        for t in succ(blocks[b]): preds[t].add(b)
    # Reachable blocks only; calculate dominators to reject irreducible entries.
    all_blocks=set(order); dom={b:set(all_blocks) for b in order}; dom[order[0]]={order[0]}
    changed=True
    while changed:
        changed=False
        for b in order[1:]:
            common=set(all_blocks)
            for p in preds[b]: common &= dom[p]
            new=common | {b}
            if new != dom[b]: dom[b]=new; changed=True
    loops={}
    for b in order:
        for h in succ(blocks[b]):
            if h not in dom[b]: continue
            body={h,b}; todo=[] if b==h else [b]
            while todo:
                node=todo.pop()
                for p in preds[node]:
                    if p not in body: body.add(p); todo.append(p)
            loops.setdefault(h,set()).update(body)
    used=set(params)
    for b in order:
        for i in blocks[b]: used.update(v for t,v in i.args if t=='r')
    next_reg=0
    count=sum(map(len,blocks.values()))
    if machine['icache_penalty'] and count >= machine['icache_size']: return
    # Process inner loops first. A pure calculation can be speculated; its old
    # destination is still assigned only at the original instruction location.
    for header, body in sorted(loops.items(),key=lambda x:(len(x[1]),order.index(x[0]))):
        outside=preds[header]-body
        if len(outside)!=1: continue
        pre=next(iter(outside))
        if blocks[pre][-1].op != 'jmp' or succ(blocks[pre]) != [header]: continue
        if any(p not in body for b in body if b!=header for p in preds[b]): continue
        definitions={}
        for node in body:
            for instruction in blocks[node]:
                d=dest(instruction)
                if d is not None: definitions[d]=definitions.get(d,0)+1
        writes=set(definitions)
        invariant={}
        budget=min(4, max(0, machine['icache_size']-count)) if machine['icache_penalty'] else 4
        for b in order:
            if b not in body: continue
            for idx,i in enumerate(blocks[b][:-1]):
                if not budget: break
                if i.op not in PURE or i.op in ('const','mov'): continue
                operands=list(i.args[1:]); safe=True
                for n,(kind,value) in enumerate(operands):
                    if kind!='r' or value not in writes: continue
                    prior=invariant.get(value)
                    # Only use an invariant definition that dominates this read.
                    if prior is None or not (prior[1]==b and prior[2]<idx or prior[1]!=b and prior[1] in dom[b]):
                        safe=False; break
                    operands[n]=('r',prior[0])
                if not safe: continue
                while next_reg in used and next_reg < 1000000: next_reg+=1
                if next_reg >= 1000000: return
                temp=next_reg; used.add(temp); next_reg+=1
                blocks[pre].insert(-1,Instr(i.op,[('r',temp)]+operands,0,''))
                blocks[b][idx]=Instr('mov',[i.args[0],('r',temp)],0,'')
                if definitions.get(dest(i))==1: invariant[dest(i)]=(temp,b,idx)
                budget-=1; count+=1

def schedule(block, machine):
    # Pure regions are independent of all stores, volatile operations and traps.
    def reorder(part):
        n=len(part)
        if n<3 or n>48: return part
        rd=[reads(i) for i in part]; wr=[dest(i) for i in part]
        edges=[[] for _ in part]; indeg=[0]*n
        for j in range(n):
            for k in range(j+1,n):
                if wr[j] in rd[k] or wr[k] in rd[j] or wr[j]==wr[k]:
                    edges[j].append(k); indeg[k]+=1
        latency=[machine[LATKEY[i.op]] for i in part]
        critical=latency[:]
        for j in range(n-1,-1,-1):
            if edges[j]: critical[j]+=max(critical[k] for k in edges[j])
        ready=[j for j in range(n) if not indeg[j]]; chosen=[]
        while ready:
            j=min(ready,key=lambda x:(-critical[x],x)); ready.remove(j); chosen.append(j)
            for k in edges[j]:
                indeg[k]-=1
                if not indeg[k]: ready.append(k)
        def score(seq):
            available={}; issue=0; slots=0; last=0
            for j in seq:
                earliest=max([issue]+[available.get(r,0) for r in rd[j]]+[available.get(wr[j],0)])
                if earliest != issue: issue=earliest; slots=0
                if slots >= machine['issue_width']: issue+=1; slots=0
                slots+=1; available[wr[j]]=issue+latency[j]; last=issue
            return max([last+1]+list(available.values()))
        return [part[j] for j in chosen] if score(chosen)<score(range(n)) else part
    out=[]; region=[]
    for i in block:
        if i.op in PURE: region.append(i)
        else:
            out.extend(reorder(region)); region=[]; out.append(i)
    out.extend(reorder(region))
    return out

def profile_layout(blocks, order, profile, machine):
    if not profile or not machine['taken_branch_penalty'] or len(order)>250: return order
    weight={}
    for a,b,n in profile:
        if a in blocks and b in succ(blocks[a]) and n>0: weight[a,b]=weight.get((a,b),0)+n
    if not weight: return order
    rank={b:i for i,b in enumerate(order)}; remaining=set(order); result=[]; cur=order[0]
    while remaining:
        if cur not in remaining:
            cur=min(remaining,key=lambda b:(-sum(weight.get((p,b),0) for p in remaining),rank[b]))
        result.append(cur); remaining.remove(cur)
        choices=[b for b in succ(blocks[cur]) if b in remaining and weight.get((cur,b),0)]
        cur=min(choices,key=lambda b:(-weight[cur,b],rank[b])) if choices else None
    def cost(seq):
        positions={b:i for i,b in enumerate(seq)}
        branch=sum(n for (a,b),n in weight.items() if positions[b]!=positions[a]+1)*machine['taken_branch_penalty']
        index=0; cache=0
        for b in seq:
            frequency=max([weight.get((p,b),0) for p in blocks]+[weight.get((b,t),0) for t in succ(blocks[b])]+[1 if b==seq[0] else 0])
            cache+=max(0,min(len(blocks[b]),index+len(blocks[b])-machine['icache_size']))*frequency*machine['icache_penalty']
            index+=len(blocks[b])
        return branch+cache
    return result if cost(result)<cost(order) else order
