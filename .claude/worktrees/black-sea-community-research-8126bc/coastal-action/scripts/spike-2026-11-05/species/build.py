import json,time,urllib.request,urllib.parse,csv
UA={'User-Agent':'hubhacks-research/0.1'}
def get(u):
    return json.load(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=60))
# iNaturalist: all research-grade ray-finned fish + elasmobranchs in NS
inat={}
for tid,lab in [(47178,'Actinopterygii'),(47273,'Elasmobranchii')]:
    page=1
    while True:
        d=get(f'https://api.inaturalist.org/v1/observations/species_counts?place_id=6853&taxon_id={tid}&quality_grade=research&per_page=200&page={page}')
        for r in d['results']:
            t=r['taxon']; inat[t['name']]={'common':t.get('preferred_common_name',''),'inat_obs':r['count'],'class':lab,'native':t.get('native'),'introduced':t.get('introduced'),'threatened':t.get('threatened')}
        if page*200>=d['total_results']: break
        page+=1; time.sleep(1.1)
    time.sleep(1.1)
print('inat species',len(inat))
# OBIS: nearshore polygon around the South Shore / Atlantic NS coast, 0-50 m, since 2000
wkt='POLYGON((-66.3 43.3,-63.0 44.3,-61.0 45.0,-61.0 45.5,-63.5 44.9,-65.0 44.3,-66.0 44.1,-66.3 43.3))'
q=urllib.parse.urlencode({'taxonid':10194,'geometry':wkt,'startdepth':0,'enddepth':50,'startdate':'2000-01-01','size':1000})
try:
    d=get('https://api.obis.org/v3/checklist?'+q)
    obis={r.get('scientificName') or r.get('species'):r.get('records') for r in d['results'] if r.get('taxonRank')=='Species'}
    print('obis nearshore species',len(obis),'total',d.get('total'))
except Exception as e:
    print('obis err',e); obis={}
# OBIS: O'Connor 20-bay juvenile seine dataset
try:
    d=get('https://api.obis.org/v3/checklist?datasetid=759428c4-ee17-40aa-8e84-fff19bb4dfd2&size=500')
    seine={r.get('scientificName'):r.get('records') for r in d['results'] if r.get('taxonRank')=='Species'}
    print('seine',len(seine),'rows',d.get('total'))
    meta=get('https://api.obis.org/v3/dataset/759428c4-ee17-40aa-8e84-fff19bb4dfd2')
    r=meta['results'][0]; print(r.get('title')); print((r.get('abstract') or '')[:600]); print(r.get('intellectualrights'))
except Exception as e:
    print('seine err',e); seine={}
names=set(inat)|set(obis)|set(seine)
rows=[]
for n in sorted(names):
    i=inat.get(n,{})
    rows.append({'species':n,'common':i.get('common',''),'inat_obs':i.get('inat_obs',0),'obis_nearshore_records':obis.get(n,0),'seine_records':seine.get(n,0),'class':i.get('class',''),'inat_introduced':i.get('introduced'),'inat_threatened':i.get('threatened')})
rows.sort(key=lambda r:-(r['inat_obs']+r['seine_records']*5))
w=csv.DictWriter(open('ns_species.csv','w',newline=''),fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
print(len(rows))
for r in rows[:70]: print(r['inat_obs'],r['obis_nearshore_records'],r['seine_records'],r['species'],'/',r['common'])
