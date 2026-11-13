"""Conservative KIR optimizer. Operands and parsing use the starter kit's kirlib."""
from collections import deque
from kirlib import SIGS, Instr, MASK
from advanced import hoist_loops, schedule, profile_layout

PURE = {'const','mov','add','sub','mul','and','or','xor','shl','shr','lt','eq','select','mac','addsh'}
COMM = {'add','mul','and','or','xor','eq'}

def ins(op, args):
    return Instr(op, args, 0, '')

def signed(x):
    return x if x < 0x80000000 else x - 0x100000000

def calculate(op, a):
    if op in ('const','mov'): return a[0]
    if op == 'add': return (a[0]+a[1]) & MASK
    if op == 'sub': return (a[0]-a[1]) & MASK
    if op == 'mul': return (a[0]*a[1]) & MASK
    if op == 'and': return a[0]&a[1]
    if op == 'or': return a[0]|a[1]
    if op == 'xor': return a[0]^a[1]
    if op == 'shl': return (a[0] << (a[1]&31)) & MASK
    if op == 'shr': return a[0] >> (a[1]&31)
    if op == 'lt': return int(signed(a[0]) < signed(a[1]))
    if op == 'eq': return int(a[0] == a[1])
    if op == 'select': return a[1] if a[0] else a[2]
    if op == 'mac': return (a[0]*a[1]+a[2]) & MASK
    if op == 'addsh': return (a[0]+(a[1]<<a[2])) & MASK
    if op in ('div','mod') and a[1]:
        x,y = signed(a[0]),signed(a[1])
        q = (abs(x)//abs(y)) * (-1 if (x<0) != (y<0) else 1)
        return (q if op == 'div' else x-q*y) & MASK
    return None

def uses(i):
    return {v for k,(t,v) in zip(SIGS[i.op],i.args) if k == 's' and t == 'r'}

def dest(i):
    return i.args[0][1] if SIGS[i.op][0] == 'd' else None

def local(block, machine=None):
    # Copies refer to a version of a register; changes invalidate them lazily.
    versions = {}
    values = {}
    expressions = {}
    loads = {}
    out = []
    def resolve(x):
        if x[0] != 'r': return x
        val = values.get(x[1])
        if val is None: return x
        operand, ver = val
        if operand[0] == 'i' or versions.get(operand[1], 0) == ver: return operand
        return x
    for old in block:
        op = old.op
        args = list(old.args)
        for n,k in enumerate(SIGS[op]):
            if k == 's': args[n] = resolve(args[n])
        d = dest(old)
        load_key = None
        if op == 'store': loads.clear()
        if op == 'load':
            addr = args[1]
            load_key = (addr, versions.get(addr[1], 0) if addr[0] == 'r' else 0)
            prior = loads.get(load_key)
            if prior is not None and versions.get(prior[0], 0) == prior[1]:
                op, args = 'mov', [args[0], ('r', prior[0])]
                load_key = None
        if op in PURE or op in ('div','mod'):
            src = args[1:]
            if all(x[0] in ('i','k') for x in src):
                v = calculate(op, [x[1] for x in src])
                if v is not None: op, args = 'const', [args[0], ('i',v)]
            if op in ('add','sub','mul','and','or','xor','shl','shr'):
                a,b = args[1:]
                replacement = None
                if op in ('add','or','xor') and b == ('i',0): replacement = a
                elif op == 'add' and a == ('i',0): replacement = b
                elif op == 'sub' and b == ('i',0): replacement = a
                elif op in ('shl','shr') and b[0] == 'i' and b[1] % 32 == 0: replacement = a
                elif op == 'mul' and b == ('i',1): replacement = a
                elif op == 'mul' and a == ('i',1): replacement = b
                elif op == 'and' and b == ('i',MASK): replacement = a
                elif op in ('sub','xor') and a == b: replacement = ('i',0)
                elif op in ('mul','and') and (a == ('i',0) or b == ('i',0)): replacement = ('i',0)
                if replacement is not None: op, args = 'mov', [args[0],replacement]
            if op == 'select' and args[1][0] == 'i':
                op, args = 'mov', [args[0], args[2] if args[1][1] else args[3]]
            elif op == 'select' and args[2] == args[3]: op, args = 'mov', [args[0],args[2]]
            if op in ('eq','lt') and args[1] == args[2]:
                op, args = 'const', [args[0], ('i', int(op == 'eq'))]
            if op == 'mul' and machine and machine['lat_alu'] <= machine['lat_mul']:
                a,b=args[1:]
                if a[0] == 'i': a,b=b,a
                if b[0] == 'i' and b[1] and not (b[1] & (b[1]-1)):
                    op,args='shl',[args[0],a,('i',b[1].bit_length()-1)]
        if op == 'br':
            if args[0][0] == 'i': op, args = 'jmp', [args[1] if args[0][1] else args[2]]
            elif args[1] == args[2]: op, args = 'jmp', [args[1]]
        # Local value numbering: expression references use register versions.
        key = None
        if op in PURE and op not in ('const','mov'):
            terms = [(t,v,versions.get(v,0) if t == 'r' else 0) for t,v in args[1:]]
            if op in COMM: terms.sort()
            key = (op, tuple(terms))
            prior = expressions.get(key)
            if prior is not None and versions.get(prior[0],0) == prior[1] and prior[0] != d:
                op, args = 'mov', [args[0],('r',prior[0])]
                key = None
        if d is not None:
            versions[d] = versions.get(d,0)+1
            values.pop(d,None)
            if op in ('mov','const'):
                src = args[1]
                if src[0] == 'i': values[d] = (src,0)
                elif src[1] != d: values[d] = (src,versions.get(src[1],0))
            if key is not None: expressions[key] = (d, versions[d])
            if load_key is not None and not (args[1][0] == 'r' and args[1][1] == d):
                loads[load_key] = (d, versions[d])
        if op == 'mov' and args[1] == args[0]: continue
        out.append(ins(op,args))
    return out

def memory_cleanup(block):
    """Forward stores only at proven valid constant addresses; respect trap barriers."""
    versions={}; stored={}; pending={}; out=[]
    for i in block:
        op=i.op; d=dest(i)
        if op=='store':
            address,value=i.args
            if address[0]=='i' and address[1]<4096:
                a=address[1]
                if a in pending: out[pending[a]]=None
                pending[a]=len(out)
                stored[a]=(value, versions.get(value[1],0) if value[0]=='r' else 0)
            else:
                pending.clear(); stored.clear()
        elif op=='load':
            pending.clear()
            address=i.args[1]
            record=stored.get(address[1]) if address[0]=='i' and address[1]<4096 else None
            if record is not None:
                value,version=record
                if value[0]=='i' or versions.get(value[1],0)==version:
                    i=ins('mov',[i.args[0],value])
        elif op not in PURE:
            # Any possible trap or observable operation prevents deleting earlier stores.
            pending.clear()
        out.append(i)
        if d is not None: versions[d]=versions.get(d,0)+1
    return [i for i in out if i is not None]

def successors(block):
    i=block[-1]
    if i.op == 'jmp': return [i.args[0][1]]
    if i.op == 'br': return [i.args[1][1],i.args[2][1]]
    return []

def reachable(blocks, entry):
    seen=set(); todo=[entry]
    while todo:
        b=todo.pop()
        if b in seen: continue
        seen.add(b); todo.extend(successors(blocks[b]))
    return seen

def simplify_cfg(blocks, order):
    # Bypass jump-only blocks, but retain cycles with no reachable exit.
    resolved={}
    def target(label):
        path=[]; positions={}; cur=label
        while cur not in resolved and cur not in positions and len(blocks[cur]) == 1 and blocks[cur][0].op == 'jmp':
            positions[cur]=len(path); path.append(cur); cur=blocks[cur][0].args[0][1]
        if cur in positions:
            for p in path[positions[cur]:]: resolved[p]=p
            path=path[:positions[cur]]
        final=resolved.get(cur,cur)
        for p in path: resolved[p]=final
        return resolved.get(label, final)
    for b in order:
        i=blocks[b][-1]
        if i.op == 'jmp': i.args[0]=('l',target(i.args[0][1]))
        elif i.op == 'br':
            i.args[1]=('l',target(i.args[1][1])); i.args[2]=('l',target(i.args[2][1]))
            if i.args[1] == i.args[2]: blocks[b][-1]=ins('jmp',[i.args[1]])
    seen=reachable(blocks,order[0]); order=[b for b in order if b in seen]
    blocks={b:blocks[b] for b in order}
    # Combine only uniquely targeted blocks, preserving the entry block.
    pred={b:set() for b in order}
    for b in order:
        for t in successors(blocks[b]): pred[t].add(b)
    removed=set()
    for b in order:
        if b in removed: continue
        while blocks[b][-1].op == 'jmp':
            t=blocks[b][-1].args[0][1]
            if t == b or t == order[0] or t in removed or pred[t] != {b}: break
            blocks[b][-1:] = blocks[t]
            removed.add(t)
            for successor in successors(blocks[b]):
                pred[successor].discard(t); pred[successor].add(b)
    order=[b for b in order if b not in removed]
    return {b:blocks[b] for b in order}, order

def dead_code(blocks, order):
    # Avoid quadratic dataflow costs on very large graphs.
    if len(order) == 1 and not successors(blocks[order[0]]):
        live=set(); kept=[]
        for i in reversed(blocks[order[0]]):
            d=dest(i)
            if d is not None and d not in live and i.op in PURE: continue
            if d is not None: live.discard(d)
            live |= uses(i); kept.append(i)
        blocks[order[0]]=list(reversed(kept))
        return
    if len(order) > 2000 or sum(map(len, blocks.values())) > 30000: return
    defs={}; use={}; pred={b:[] for b in order}
    for b in order:
        defined=set(); needed=set()
        for i in blocks[b]:
            needed |= uses(i)-defined
            d=dest(i)
            if d is not None: defined.add(d)
        defs[b]=defined; use[b]=needed
        for s in successors(blocks[b]): pred[s].append(b)
    livein={b:set() for b in order}; liveout={b:set() for b in order}
    q=deque(reversed(order)); queued=set(order); iterations=0; set_work=0
    while q:
        b=q.popleft(); queued.discard(b); iterations+=1
        if iterations > 100000: return
        out=set()
        for s in successors(blocks[b]):
            set_work+=len(livein[s])
            if set_work>2000000: return
            out |= livein[s]
        new=use[b] | (out-defs[b]); liveout[b]=out
        if new != livein[b]:
            livein[b]=new
            for p in pred[b]:
                if p not in queued: q.append(p); queued.add(p)
    for b in order:
        live=liveout[b].copy(); result=[]
        for i in reversed(blocks[b]):
            d=dest(i)
            if d is not None and d not in live and i.op in PURE: continue
            if d is not None: live.discard(d)
            live |= uses(i); result.append(i)
        blocks[b]=list(reversed(result))

def fuse(block, machine, use_counts):
    # Adjacent producer/consumer only; producer must not be needed afterwards.
    out=[]; j=0
    while j < len(block):
        a=block[j]
        if j+1 < len(block):
            b=block[j+1]; d=dest(a)
            if d is not None and use_counts.get(d, 0) == 1 and b.op == 'add' and sum(x == ('r',d) for x in b.args[1:]) == 1:
                other=b.args[2] if b.args[1] == ('r',d) else b.args[1]
                if other != ('r',d) and a.op == 'mul' and machine['fused_mac'] and machine['lat_mac'] <= machine['lat_mul']+machine['lat_alu']:
                    out.append(ins('mac',[b.args[0],a.args[1],a.args[2],other])); j+=2; continue
                if other != ('r',d) and a.op == 'shl' and a.args[2][0] == 'i' and machine['fused_addsh'] and machine['lat_addsh'] <= 2*machine['lat_alu']:
                    out.append(ins('addsh',[b.args[0],other,a.args[1],('k',a.args[2][1]&31)])); j+=2; continue
        out.append(a); j+=1
    return out


def allocate_registers(blocks, order, params, machine):
    # Graph coloring is bounded to keep large inputs predictable.
    instructions = sum(map(len, blocks.values()))
    regs = set(params)
    for b in order:
        for i in blocks[b]:
            regs.update(v for t, v in i.args if t == 'r')
    if len(regs) <= machine['registers'] or not machine['reg_spill_penalty'] or len(regs) > 256 or instructions > 5000 or len(order) > 500:
        return params
    use={}; defs={}; pred={b:[] for b in order}
    for b in order:
        u=set(); d=set()
        for i in blocks[b]:
            u |= uses(i)-d
            dst=dest(i)
            if dst is not None: d.add(dst)
        use[b]=u; defs[b]=d
        for target in successors(blocks[b]): pred[target].append(b)
    livein={b:set() for b in order}; liveout={b:set() for b in order}
    q=deque(reversed(order)); queued=set(order); steps=0
    while q:
        b=q.popleft(); queued.discard(b); steps+=1
        if steps > 50000: return params
        out=set()
        for target in successors(blocks[b]): out |= livein[target]
        new=use[b] | (out-defs[b]); liveout[b]=out
        if new != livein[b]:
            livein[b]=new
            for p in pred[b]:
                if p not in queued: q.append(p); queued.add(p)
    graph={r:set() for r in regs}
    def edge(a,b):
        if a != b: graph[a].add(b); graph[b].add(a)
    initial=sorted(livein[order[0]] | set(params))
    for n,a in enumerate(initial):
        for b in initial[n+1:]: edge(a,b)
    for b in order:
        live=liveout[b].copy()
        for i in reversed(blocks[b]):
            d=dest(i)
            if d is not None:
                for r in live: edge(d,r)
                live.discard(d)
            live |= uses(i)
    colors={r:n for n,r in enumerate(params)}
    for r in sorted(regs-set(params), key=lambda x:(-len(graph[x]), x)):
        forbidden={colors[n] for n in graph[r] if n in colors}
        color=0
        while color in forbidden: color+=1
        colors[r]=color
    if len(set(colors.values())) >= len(regs): return params
    for b in order:
        for i in blocks[b]:
            i.args=[(t,colors[v]) if t == 'r' else (t,v) for t,v in i.args]
    return [colors[p] for p in params]

def global_constants(blocks, order, params, machine):
    """Forward constant dataflow; unvisited edges are distinct from unknown values."""
    if len(order)>250 or sum(map(len,blocks.values()))>4000: return
    regs=set(params)
    for b in order:
        for i in blocks[b]: regs.update(v for t,v in i.args if t=='r')
    if len(regs)>256: return
    seed={r:(None if r in params else 0) for r in regs}
    pred={b:set() for b in order}
    for b in order:
        for t in successors(blocks[b]): pred[t].add(b)
    incoming={}; outgoing={}; q=deque([order[0]]); queued={order[0]}; work=0
    def transfer(block, env, rewrite=False):
        env=env.copy(); result=[]
        for i in block:
            args=[('i',env[v]) if k=='s' and t=='r' and env[v] is not None else (t,v)
                  for k,(t,v) in zip(SIGS[i.op],i.args)]
            d=dest(i)
            if d is not None:
                vals=[v if t in ('i','k') else env[v] for t,v in args[1:]]
                env[d]=calculate(i.op,vals) if (i.op in PURE or i.op in ('div','mod')) and all(v is not None for v in vals) else None
            if rewrite: result.append(ins(i.op,args))
        return result if rewrite else env
    while q:
        b=q.popleft(); queued.discard(b); work+=len(blocks[b])
        if work>1000000: return
        sources=[outgoing[p] for p in sorted(pred[b]) if p in outgoing]
        if b==order[0]: sources.append(seed)
        if not sources: continue
        env=sources[0].copy()
        for source in sources[1:]:
            for r in regs:
                if env[r] != source[r]: env[r]=None
        incoming[b]=env; new=transfer(blocks[b],env)
        if new != outgoing.get(b):
            outgoing[b]=new
            for t in successors(blocks[b]):
                if t not in queued: q.append(t); queued.add(t)
    for b in order: blocks[b]=local(transfer(blocks[b],incoming[b],True),machine)

def optimize(prog, machine, profile=None, *, hoist=True, fusion=True, strength=True, global_value=True):
    order=list(prog.block_labels)
    blocks={b:[] for b in order}
    for b,i in zip(prog.block_of,prog.instrs): blocks[b].append(i)
    # A fresh temporary preserves operands even when the destination aliases them.
    used = set(prog.params)
    for inst in prog.instrs:
        used.update(v for t, v in inst.args if t == 'r')
    temporary = next((r for r in range(1000000) if r not in used), None)
    for b in order:
        lowered=[]
        for i in blocks[b]:
            if i.op == 'mac' and not machine['fused_mac']:
                if temporary is None: return None
                t = ('r', temporary)
                lowered.extend([ins('mul', [t, i.args[1], i.args[2]]), ins('add', [i.args[0], t, i.args[3]])])
            elif i.op == 'addsh' and not machine['fused_addsh']:
                if temporary is None: return None
                t = ('r', temporary)
                lowered.extend([ins('shl', [t, i.args[2], ('i', i.args[3][1])]), ins('add', [i.args[0], i.args[1], t])])
            else: lowered.append(i)
        blocks[b]=memory_cleanup(local(lowered,machine if strength else None))
    blocks, order = simplify_cfg(blocks, order)
    if global_value: global_constants(blocks, order, prog.params, machine)
    blocks, order = simplify_cfg(blocks, order)
    dead_code(blocks,order)
    if hoist: hoist_loops(blocks, order, machine, prog.params)
    for b in order: blocks[b]=memory_cleanup(local(blocks[b],machine if strength else None))
    dead_code(blocks,order)
    # A fused-away register must have just one use anywhere in the function.
    use_counts={}
    for b in order:
        for i in blocks[b]:
            for r in uses(i): use_counts[r]=use_counts.get(r,0)+1
    if fusion:
        for b in order: blocks[b]=fuse(blocks[b],machine,use_counts)
    order=profile_layout(blocks, order, profile, machine)
    params=allocate_registers(blocks, order, prog.params, machine)
    for b in order:
        blocks[b]=[i for i in blocks[b] if not (i.op=='mov' and i.args[0]==i.args[1])]
    # Reordering can worsen the simulator's LRU spills. Schedule only when all
    # virtual registers fit in the machine's register file.
    registers=set(params)
    for b in order:
        for i in blocks[b]: registers.update(v for t,v in i.args if t == 'r')
    if len(registers) <= machine['registers'] and sum(map(len,blocks.values())) <= 5000:
        for b in order: blocks[b]=schedule(blocks[b], machine)
    lines=['func %s(%s)' % (prog.name, ', '.join('v%d'%p for p in params))]
    for b in order:
        lines.append(b+':')
        for i in blocks[b]:
            def fmt(x): return ('v%d'%x[1]) if x[0]=='r' else str(x[1])
            lines.append('  '+i.op+' '+', '.join(fmt(x) for x in i.args))
    return '\n'.join(lines)+'\n'
