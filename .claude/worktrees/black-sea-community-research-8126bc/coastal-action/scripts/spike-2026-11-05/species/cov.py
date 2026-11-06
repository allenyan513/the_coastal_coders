import json,csv,re
raw=open('labels.json').read()
try:
    d=json.loads(raw)
except Exception as e:
    print('bad json',e); raise SystemExit
def flat(x):
    if isinstance(x,dict):
        for k,v in x.items():
            yield str(k); yield from flat(v)
    elif isinstance(x,list):
        for v in x: yield from flat(v)
    else: yield str(x)
L={s.lower() for s in flat(d)}
print('label strings',len(L))
rows=list(csv.DictReader(open('ns_species.csv')))
top=[r for r in rows if int(r['inat_obs'])+int(r['seine_records'])*5>=40]
hit=[r['species'] for r in top if r['species'].lower() in L]
miss=[r['species'] for r in top if r['species'].lower() not in L]
print(len(top),'top NS species; covered',len(hit)); print('covered',hit); print('missing',miss)
allhit=sum(r['species'].lower() in L for r in rows); print('all',allhit,len(rows))
