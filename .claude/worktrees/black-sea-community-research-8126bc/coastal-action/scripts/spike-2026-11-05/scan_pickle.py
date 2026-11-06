import sys,zipfile,pickletools,collections
for p in sys.argv[1:]:
    z=zipfile.ZipFile(p)
    names=z.namelist(); pk=[n for n in names if n.endswith('.pkl')]
    print(p.split('/')[-1], 'entries',len(names),'pkl',pk, 'nonstorage',[n for n in names if '/data/' not in n][:12])
    g=collections.Counter(); strs=[]
    for op,arg,pos in pickletools.genops(z.read(pk[0])):
        if op.name in('GLOBAL','INST'): g[arg]+=1
        elif op.name=='STACK_GLOBAL': g['STACK_GLOBAL:'+' '.join(strs[-2:])]+=1
        if op.name in('SHORT_BINUNICODE','BINUNICODE','UNICODE'): strs.append(arg)
        if op.name in('MEMOIZE','BINPUT','LONG_BINPUT'): pass
    for k,v in g.most_common(): print('  ',v,k)
