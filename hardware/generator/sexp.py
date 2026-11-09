import re
class Sym(str):
    """bare atom"""
    pass
_tok = re.compile(r'\s*(?:(\()|(\))|("(?:[^"\\]|\\.)*")|([^\s()"]+))')
def parse(text):
    pos=0; stack=[[]]
    n=len(text)
    while pos<n:
        m=_tok.match(text,pos)
        if not m:
            if text[pos:].strip()=="" : break
            raise ValueError("parse error at %d: %r"%(pos,text[pos:pos+40]))
        pos=m.end()
        if m.group(1): stack.append([])
        elif m.group(2):
            l=stack.pop(); stack[-1].append(l)
        elif m.group(3) is not None:
            s=m.group(3)[1:-1]
            stack[-1].append(s.replace('\\"','"').replace('\\\\','\\'))
        elif m.group(4) is not None:
            stack[-1].append(Sym(m.group(4)))
    return stack[0]
def q(s):
    return '"'+s.replace('\\','\\\\').replace('"','\\"')+'"'
def dump(x, indent=0):
    if isinstance(x,list):
        if not x: return "()"
        parts=[dump(e,indent+1) for e in x]
        one="("+" ".join(parts)+")"
        if len(one)<100 and "\n" not in one: return one
        head=[]; rest=[]
        for i,e in enumerate(x):
            if not isinstance(e,list) and not rest: head.append(parts[i])
            else: rest.append(parts[i])
        pad="\n"+"  "*(indent+1)
        return "("+" ".join(head)+pad+pad.join(rest)+")"
    if isinstance(x,Sym): return str(x)
    if isinstance(x,bool): return "yes" if x else "no"
    if isinstance(x,(int,float)):
        if isinstance(x,float):
            s=("%.4f"%x).rstrip("0").rstrip(".")
            return s if s not in ("-0","") else "0"
        return str(x)
    return q(x)
def find(l,key):
    return [e for e in l if isinstance(e,list) and e and e[0]==key]
def find1(l,key):
    r=find(l,key); return r[0] if r else None
