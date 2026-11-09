import copy, functools
from sexp import parse, find, find1, Sym
from paths import SYMDIR
@functools.lru_cache(None)
def load_lib(lib):
    return parse(open(f"{SYMDIR}/{lib}.kicad_sym").read())[0]
def get_symbol(lib,name):
    L=load_lib(lib)
    for s in find(L,"symbol"):
        if s[1]==name: break
    else: raise KeyError(lib+":"+name)
    s=copy.deepcopy(s)
    ext=find1(s,"extends")
    if ext:
        parent=get_symbol(lib,ext[1])
        # child props override parent props
        props={p[1]:p for p in find(s,"property")}
        out=[Sym("symbol"),name]
        for e in parent[2:]:
            if isinstance(e,list) and e and e[0]=="property" and e[1] in props:
                out.append(props.pop(e[1]))
            elif isinstance(e,list) and e and e[0]=="symbol":
                sub=copy.deepcopy(e); sub[1]=sub[1].replace(ext[1],name,1); out.append(sub)
            else: out.append(e)
        for p in props.values(): out.insert(len(out)-0,p)
        s=out
    return s
def pins(sym):
    """return list of dict(number,name,x,y,angle,type,hidden,unit)"""
    res=[]
    for sub in find(sym,"symbol"):
        unit=int(sub[1].rsplit("_",2)[-2])
        for p in find(sub,"pin"):
            at=find1(p,"at"); nm=find1(p,"name"); num=find1(p,"number")
            res.append(dict(number=num[1],name=nm[1],x=float(at[1]),y=float(at[2]),angle=int(float(at[3])),type=str(p[1]),hidden=("hide" in p),unit=unit))
    return res
if __name__=="__main__":
    import sys
    for spec in sys.argv[1:]:
        lib,n=spec.split(":")
        s=get_symbol(lib,n)
        print("==",spec)
        for p in sorted(pins(s),key=lambda p:(p['unit'],p['number'])):
            print("  ",p)
