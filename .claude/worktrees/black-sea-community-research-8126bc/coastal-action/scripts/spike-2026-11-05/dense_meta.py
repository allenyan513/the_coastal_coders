import collections,json,random
random.seed(5)
d=json.load(open('data/community_fish_detector_20261029.json'))
c=collections.Counter(a['image_id'] for a in d['annotations'] if a['category_id']==1)
ds={i['id']:i for i in d['images']}
by=collections.defaultdict(list)
for k,v in c.items():
    if v>=30: by[ds[k]['dataset']].append((v,k))
for k,v in sorted(by.items(),key=lambda x:-len(x[1])):
    s=sorted(x[0] for x in v); print(k,len(v),'median',s[len(s)//2],'max',s[-1],ds[v[0][1]]['width'],ds[v[0][1]]['height'])
sel=[]
for k,v in by.items():
    sel+=[ds[i] for _,i in random.sample(v,min(60,len(v)))]
ids={i['id'] for i in sel}
ann=[a for a in d['annotations'] if a['image_id'] in ids]
json.dump({'images':sel,'annotations':ann},open('data/sel3.json','w'))
open('data/urls3.txt','w').write('\n'.join('https://storage.googleapis.com/public-datasets-lila/community-fish-detection-dataset-2026/images/'+i['file_name'] for i in sel))
print(len(sel))
