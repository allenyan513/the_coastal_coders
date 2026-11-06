import pickle,re,collections
d=pickle.load(open('data/subset.pkl','rb'))
ims=list(d['images'].values())
for ds in ['pebl_farm_fauna','brackish_dataset','griffith_seagrass','kso_mussel_bruv','viame_fishtrack']:
    c=collections.Counter()
    for i in ims:
        if i['dataset']!=ds: continue
        n=i['file_name'][len(ds)+1:]
        k=re.split(r'_frame_|-\d{4}_jpg|_\d{6}\.|_5fps',n)[0]
        c[k]+=1
    print(ds,len(c),c.most_common(12))
