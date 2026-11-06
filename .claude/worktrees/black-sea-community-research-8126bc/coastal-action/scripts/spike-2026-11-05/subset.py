import json,collections,random,pickle
random.seed(7)
d=json.load(open('data/community_fish_detector_20261029.json'))
want={'pebl_farm_fauna':None,'kso_mussel_bruv':None,'griffith_seagrass':300,'fjordfish':300,'brackish_dataset':'clips'}
clips=['2019-03-06_22-03-36to2019-03-06_22-04-08_1','2019-02-21_06-56-08to2019-02-21_06-56-28_1','2019-03-19_11-42-56to2019-03-19_11-43-14_1']
by=collections.defaultdict(list)
for i in d['images']:
    if i.get('dataset') in want: by[i['dataset']].append(i)
sel=[]
for k,v in want.items():
    ims=by[k]
    if v is None: sel+=ims
    elif v=='clips': sel+=[i for i in ims if any(c in i['file_name'] for c in clips)]
    else: sel+=random.sample(ims,v)
ids={i['id'] for i in sel}
ann=[a for a in d['annotations'] if a['image_id'] in ids]
print(len(sel),len(ann),collections.Counter((a['category_id']) for a in ann))
for k in want:
    s=[i['id'] for i in sel if i['dataset']==k]; ss=set(s)
    an=[a for a in ann if a['image_id'] in ss]
    print(k,len(s),collections.Counter(a['category_id'] for a in an),'empty',len(ss-{a['image_id'] for a in an}))
json.dump({'images':sel,'annotations':ann,'categories':d['categories']},open('data/sel.json','w'))
open('data/urls.txt','w').write('\n'.join('https://storage.googleapis.com/public-datasets-lila/community-fish-detection-dataset-2026/images/'+i['file_name'] for i in sel))
