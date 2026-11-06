import json,collections,sys,pickle
d=json.load(open('data/community_fish_detector_20261029.json'))
print(d.keys()); print(d.get('info')); print(d['categories'])
print(len(d['images']),len(d['annotations']))
print(d['images'][0]); print(d['annotations'][0])
c=collections.Counter(i.get('dataset') for i in d['images'])
for k,v in c.most_common(): print(v,k)
keep=[k for k in c if k and any(s in k.lower() for s in ('pebl','brackish','herring','kso','griffith','seagrass','puget','norfisk','fishtrack','pomer'))]
print(keep)
ids={i['id']:i for i in d['images'] if i.get('dataset') in keep}
ann=collections.defaultdict(list)
for a in d['annotations']:
    if a['image_id'] in ids: ann[a['image_id']].append(a)
pickle.dump({'images':ids,'ann':dict(ann),'cats':d['categories']},open('data/subset.pkl','wb'))
for k in keep:
    ims=[i for i in ids.values() if i['dataset']==k]
    print(k,len(ims),sum(len(ann.get(i['id'],[])) for i in ims),ims[0]['file_name'],{x:ims[0][x] for x in ims[0] if x not in('file_name',)})
