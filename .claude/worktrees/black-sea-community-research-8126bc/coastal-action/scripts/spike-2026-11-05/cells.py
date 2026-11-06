"""Simulate counting only some grid cells on crowded frames, using labelled fish centres.
Cells are chosen at random, and the total is estimated by scaling up the sampled cells."""
import collections, json, random
import numpy as np
random.seed(9)
sel=json.load(open('data/sel3.json'))
img={i['id']:i for i in sel['images']}
pts=collections.defaultdict(list)
for a in sel['annotations']:
    if a['category_id']==1:
        x,y,w,h=a['bbox']; pts[a['image_id']].append((x+w/2,y+h/2))
R,C=4,6
for k in (6,8,12,24):
    errs=[];share=[]
    for iid,p in pts.items():
        i=img[iid]; g=np.zeros((R,C))
        for x,y in p:
            g[min(R-1,int(y/i['height']*R)),min(C-1,int(x/i['width']*C))]+=1
        n=g.sum()
        for _ in range(50):
            idx=random.sample(range(R*C),k)
            s=sum(g[j//C,j%C] for j in idx)
            est=s*(R*C)/k
            errs.append(abs(est-n)/n); share.append(s/n)
    e=np.array(errs)
    print(f"{k}/{R*C} cells: median error {np.median(e):.2f}, p90 error {np.percentile(e,90):.2f}, fish dotted {np.mean(share):.2f} of total, frames {len(pts)}")
