"""Paraphrase benchmark for natural-language handling, plus a prototype wrapper layer.

Measures how often the unmodified chat answers, abstains, or answers wrongly
across many wordings of the same facts, on three question sets (dev, held,
unseen), each with its own small corpus. It then applies a prototype layer that
wraps the engine without changing it (answer-type and relation gate, fallback
sentence selector, polar-question entailment, light rewrites, typo repair, and a
small seed equivalence pack) and reports the same counts. Design and results:
docs/design_natural_language_handling.md.

The layer is a sketch of the proposed logic, not engine code. The invariants
checked here are the design's ground rules: with the layer, no answerable
question is answered wrongly, unanswerable questions are declined, and correct
answers do not fall below the unmodified engine's.

Run with: python3 experiments/v1_327_paraphrase_benchmark_nl_layer.py
"""
from __future__ import annotations

import collections
import itertools
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import re, sys, os, subprocess, tempfile, shutil, threading, itertools
from crms_knowledge import _IRREGULAR_VERB_PARADIGMS as IRR  # noqa: E402
WORK=""  # scratch directory, set by main()
LEMMA={f:l for l,forms in IRR.items() for f in forms}
STOP=set("a an the of in on at to for by is are was were be been do does did has have had it its this that and or not as with from into than then there their his her he she i me you my please tell know like would could can name define whom who what which when where how why whose about much many".split())
GENERIC={"year","tall","high","long","temperature","point","city","country","person","range","mountain","time","times","get","come","out","first","one"}
MODS=set('longest largest biggest smallest tallest highest oldest youngest deepest fastest'.split())
NUMW=set("one two three four five six seven eight nine ten eleven twelve twenty thirty forty fifty hundred thousand million".split())
ABSTAIN_TEXT="I don't know this from the sources and facts I have."
ABST=re.compile(r"couldn't find|don't know|found relevant source text, but no accepted|don't have a direct source|Please name|Which thing do you mean|couldn't identify|no verified math|Teach |not enough|can't answer|does not confirm|does not state what you asked|won't guess",re.I)
SEEDS=[{"create","make","invent","design","develop","found","establish","start","build","author"},{"tall","height","high"},{"born","birth","birthplace"},{"release","come","appear","publish"},{"employ","people","worker","work"}]
_cache={}; _lock=threading.Lock()

def engine(docdir,q):
    key=(docdir,q)
    with _lock:
        if key in _cache: return _cache[key]
    d=tempfile.mkdtemp(prefix="e-",dir=WORK); shutil.copytree(docdir,d+"/docs")
    cmd=[sys.executable,str(PROJECT / "crms_chat.py")]+[x for n in ["knowledge","math","rules","dialogue-state","rule-session","candidate-session","math-session","translations","translation-session"] for x in ("--"+n,f"{d}/s_{n}.json")]+["--index",d+"/r.sqlite"]
    out=subprocess.run(cmd,input=f"/source-dir {d}/docs\n{q}\n/quit\n",text=True,capture_output=True,timeout=120).stdout
    parts=out.split("CRMS> "); a=parts[1] if len(parts)>1 else ""
    a=re.sub(r"\s*you>.*$","",a.strip(),flags=re.S); shutil.rmtree(d,ignore_errors=True)
    with _lock: _cache[key]=a
    return a

def stem(w,seeds=False):
    w=w.lower(); w=LEMMA.get(w,w)
    for suf in ("ing","ers","er","ed","es","s","ion","or"):
        if len(w)>len(suf)+3 and w.endswith(suf): w=w[:-len(suf)]; break
    return w[:5]
class Corpus:
    def __init__(s,docdir):
        txt=" ".join(open(os.path.join(docdir,f)).read() for f in sorted(os.listdir(docdir)))
        s.sents=[x.strip() for x in re.split(r"(?<=[.!?])\s+",txt) if x.strip()]
        s.vocab=set(re.findall(r"[a-z]+",txt.lower()))
        s.stems={stem(w) for w in s.vocab}
        s.ents=set(); 
        for x in s.sents: 
            for m in re.finditer(r"(?:(?<=\s)|^)([A-Z][\w-]*(?:\s+(?:van|of|de)?\s*[A-Z][\w-]*)*)",x): s.ents.add(m.group(1))
def toks(x): return re.findall(r"[\w'-]+",x)
def mentions(q):
    ws=toks(q); out=[]; cur=[]
    for i,w in enumerate(ws):
        if w[0].isupper() and w.lower() not in STOP and not (i==0): cur.append(w)
        elif cur and w.lower() in {"van","of","de"}: cur.append(w)
        else:
            if cur: out.append(cur); cur=[]
    if cur: out.append(cur)
    return [[t for t in c] for c in out]

# ---------- idea: rewrites / alias / typo ----------
def edits1(w):
    sp=[(w[:i],w[i:]) for i in range(len(w)+1)]
    r={a+b[1:] for a,b in sp if b}|{a+b[1]+b[0]+b[2:] for a,b in sp if len(b)>1}
    r|={a+c+b[1:] for a,b in sp if b for c in "abcdefghijklmnopqrstuvwxyz"}|{a+c+b for a,b in sp for c in "abcdefghijklmnopqrstuvwxyz"}
    return r
def fix_typos(q,C):
    known=C.vocab|STOP|GENERIC|NUMW|{"tall","year","longest","highest","tell","founded","released","written","invented","winner","prize","made","named","people","employees","employ","define","function","birthplace","melting","boiling"}
    out=[];log=[]
    for w in q.split():
        core=re.sub(r"[^\w'-]","",w); low=core.lower()
        if len(low)>=4 and low not in known and low.isalpha():
            c=[v for v in edits1(low) if v in C.vocab or v in STOP]
            if len(c)==1:
                rep=c[0]; rep=rep.capitalize() if core[0].isupper() else rep
                w=w.replace(core,rep); log.append((core,rep))
        out.append(w)
    return " ".join(out),log
def rewrite(q,C):
    q=q.strip()
    q=re.sub(r"(\w+)'s\s+(capital(?: city)?|birthplace|height|founder|creator|author)\b",r"the \2 of \1",q)
    q=re.sub(r"^(?:in )?what year (was|did|is|were)\b",r"When \1",q,flags=re.I)
    q=re.sub(r"^In what year (was|did)\b",r"When \1",q,flags=re.I)
    m=re.match(r"^By whom (was|were) (.+?) (\w+)\??$",q,flags=re.I)
    if m: q=f"{m.group(2)} {m.group(1)} {m.group(3)} by whom?"
    m=re.match(r"^(?:Name|Identify) (the .+?)\.?$",q,flags=re.I)
    if m: q=f"What is {m.group(1)}?"
    m=re.match(r"^Define (.+?)\.?$",q,flags=re.I)
    if m: q=f"What is {m.group(1)}?"
    # alias: expand short mention to the unique full corpus entity containing it
    for men in mentions(q):
        s=" ".join(men); 
        if s in C.ents: continue
        c={e for e in C.ents if set(men)<=set(e.split()) and e!=s}
        # drop entities that are sentence-initial junk
        if len(c)==1: q=q.replace(s,c.pop())
    return q
# ---------- question parse ----------
def parse(q):
    ql=q.lower().strip().rstrip("?.! ")
    pt=None
    if re.match(r"^(is|are|was|were|did|does|do|has|have)\b",ql): pt="POLAR"
    elif re.search(r"\b(who|whom)\b",ql): pt="WHO"
    elif re.search(r"\b(when|what year|in what year)\b",ql): pt="WHEN"
    elif re.search(r"\bwhere\b|\bwhich (country|city|continent|range|mountain range|river|region|state)\b",ql): pt="WHERE"
    elif re.search(r"\bhow (tall|high|long|big|old)\b|\bheight\b|\btemperature\b|\bboiling point\b|\bmelting point\b",ql): pt="MEASURE"
    elif re.search(r"\bhow (many|much)\b",ql): pt="COUNT"
    elif not (set(re.findall(r"[a-z]+",ql))&MODS) and re.match(r"^(what|define)\s+(is|are)\s+(?!the (capital|longest|height|birthplace|function|boiling|melting))",ql): pt="DEF"
    elif re.match(r"^what (does|do) .+ do$",ql) or "function of" in ql: pt="DEF"
    elif re.search(r"\b(what|which)\b",ql): pt="NAME"
    return pt
def content(q,men):
    mt={t.lower() for m in men for t in m}
    return [w for w in (x.lower() for x in toks(q)) if w not in STOP and w not in GENERIC and w not in mt and not w.isdigit()]
def same(a,b,seeds):
    if a==b: return True
    if seeds:
        for g in SEEDS:
            if a in {stem(x) for x in g} and b in {stem(x) for x in g}: return True
    return False
def has_type(pt,s,men):
    mt={t for m in men for t in m}
    if pt=="WHEN": return bool(re.search(r"\b\d{4}\b",s))
    if pt in("MEASURE",): return bool(re.search(r"\d[\d,.]*\s*(metres|meters|m|km|kilometres|kilometers|miles|feet|ft|degrees|kg|kilograms|tonnes|years|cm|mm)\b",s,flags=re.I))
    if pt=="COUNT": return bool(re.search(r"\d",s) or NUMW&set(re.findall(r"[a-z]+",s.lower())))
    if pt in("WHO","NAME","WHERE"):
        caps=[w for i,w in enumerate(toks(s)) if w[0].isupper() and w not in mt and w not in {"The","A","An"}]
        return bool(caps) or pt=="NAME"
    return True
def fits(q,s,seeds=False,C=None,strict=True):
    pt=parse(q)
    if pt in (None,"POLAR"): return True
    men=mentions(q); mt=[t.lower() for m in men for t in m]
    sl={t.lower() for t in toks(s)}
    for m in men:
        if not all(t.lower() in sl for t in m): return False
    if not has_type(pt,s,men): return False
    cw=content(q,men)
    if " and " in q.lower(): return True
    if pt=="DEF":
        ss={stem(t) for t in toks(s)[:6]}
        subj=[t for m in men for t in m]+[w for w in cw if w not in {"do","function"}]
        return bool(subj) and all(stem(w) in ss for w in subj)
    mods=[w for w in (x.lower() for x in toks(q)) if w in MODS]
    if mods and not all(m in sl for m in mods): return False
    if cw and not strict and C is not None and not any(stem(w) in C.stems for w in cw): return True
    if cw:
        ss={stem(t) for t in toks(s)}
        return any(same(stem(w),x,seeds) for w in cw for x in ss)
    return True
# ---------- fallback retriever ----------
def retrieve(q,C,seeds=False):
    pt=parse(q)
    if pt in (None,"POLAR"): return None
    best=[]
    for s in C.sents:
        if fits(q,s,seeds,C): best.append(s)
    if len(best)==1: return best[0]
    if len(best)>1:
        # prefer the sentence with most content-stem overlap; require unique winner
        men=mentions(q); cw=[stem(w) for w in content(q,men)]
        def sc(s): ss={stem(t) for t in toks(s)}; return sum(any(same(w,x,seeds) for x in ss) for w in cw)
        best.sort(key=sc,reverse=True)
        if sc(best[0])>sc(best[1]): return best[0]
    return None
# ---------- polar entailment ----------
def polar(q,C,seeds=False):
    ql=q.strip().rstrip("?.! ")
    if parse(q)!="POLAR": return None
    men=mentions(q)
    if not men: return None
    cw=[stem(w) for w in content(re.sub(r"^\w+\s+","",ql),men)]
    passive=re.search(r"\bby\s+",ql) and re.search(r"\b(was|were|is|are)\b",ql)
    agent=patient=None
    if len(men)>=2:
        if passive: agent,patient=men[-1],men[0]
        else: agent,patient=men[0],men[-1]
    cop=bool(re.match(r"^(is|are|was|were)\s+",ql,flags=re.I)) and not passive and not re.search(r"\b(born|located|in|on|at)\b",ql)
    sub=[];contra=None
    for s in C.sents:
        st=toks(s); sl=[t.lower() for t in st]
        if not all(all(t.lower() in sl for t in m) for m in men): continue
        ss={stem(t) for t in st}
        if not all(any(same(w,x,seeds) for x in ss) for w in cw): continue
        # contrast: mention appears after 'not'
        neg=any(re.search(r"\bnot\s+"+re.escape(" ".join(m)),s,flags=re.I) for m in men)
        if neg: return ("no",s)
        if agent and patient and cw and not cop:
            def pos(m): 
                for i in range(len(sl)):
                    if sl[i:i+len(m)]==[t.lower() for t in m]: return i
                return None
            vi=[i for i,t in enumerate(st) if any(same(w,stem(t),seeds) for w in cw)]
            pa,pp=pos(agent),pos(patient)
            if pa is None or pp is None or not vi or not (pa<min(vi)<pp or pp<min(vi)<pa and False): 
                continue
        sub.append(s)
    if sub: return ("yes",sub[0])
    # same subject + relation, different object -> informative non-confirmation
    for s in C.sents:
        sl={t.lower() for t in toks(s)}
        if all(t.lower() in sl for t in men[0]):
            ss={stem(t) for t in toks(s)}
            if cw and all(any(same(w,x,seeds) for x in ss) for w in cw): return ("contrast",s)
    return None
# ---------- pipeline ----------
def clean(a): 
    a=re.sub(r"\[Source:[^\]]*\]","",a); a=re.sub(r"Source text:\s*","",a); a=re.sub(r"\n?Source: .*?(?=\n|$)","",a)
    a=re.sub(r"\d+ source claims? .*$","",a,flags=re.S)
    return a.strip()
def answer(docdir,q,cfg):
    C=Corpus(docdir); log=[]
    q0=q
    if "typo" in cfg: q,l=fix_typos(q,C); log+=l
    if "rewrite" in cfg: q=rewrite(q,C)
    seeds="seeds" in cfg
    if "polar" in cfg and parse(q)=="POLAR":
        r=polar(q,C,seeds)
        if r:
            k,s=r
            if k=="yes": return f"The source states yes: “{s}”"
            if k=="no": return f"The source states no: “{s}”"
            return f"The source does not confirm this; it states: “{s}”"
    a=engine(docdir,q)
    isabst=bool(ABST.search(a)) and not re.search(r"states (yes|no)",a)
    if "gate" in cfg and not isabst:
        if parse(q)=="POLAR":
            if not re.search(r"states (yes|no)",a): a=f"The source does not confirm this; it states: “{clean(a)}”"
        else:
            sents=[x.strip() for x in re.split(r"\s*\|\s*|\n",clean(a)) if x.strip()]
            if not re.search(r"states (yes|no)",a) and not any(fits(q,s,seeds,C,strict=("strictgate" in cfg)) for s in sents):
                a="I found source text, but it does not state what you asked; I won't guess."; isabst=True
    if "fallback" in cfg and (isabst or ABST.search(a)):
        s=retrieve(q,C,seeds)
        if s: a=f"{s} [fallback match: quoted evidence, not an accepted fact]"
    return a


DEV_CORPUS = """Marie Curie won two Nobel Prizes. Marie Curie was born in Warsaw in 1867. Albert Einstein won the Nobel Prize in Physics in 1921. Einstein developed the theory of relativity.
Canberra is the capital of Australia, not Sydney. Paris is the capital of France. Mount Everest is located in the Himalayas. Mount Everest is 8849 metres tall.
Guido van Rossum created Python. Python was released in 1991. Linus Torvalds developed Linux in 1991. Alan Turing worked at Bletchley Park during the war.
The Nile is the longest river in Africa. The Amazon River flows through Brazil. Tokyo is the largest city in Japan. Photosynthesis converts sunlight into chemical energy in plants.
Bree Hollis founded Quarn Beacon in 2019. Quarn Beacon employs forty people. Cara is a parent of Dan. Dan is a parent of Eve.
Water boils at 100 degrees Celsius at sea level. The heart pumps blood around the body. Shakespeare wrote Hamlet in about 1600.
"""

HELD_CORPUS = """Ada Lovelace wrote the first computer program in 1843. Ada Lovelace was born in London in 1815. Nikola Tesla was born in Smiljan. Tesla invented the induction motor.
Rome is the capital of Italy, not Milan. Mount Kilimanjaro is 5895 metres tall. Mount Kilimanjaro is located in Tanzania.
Kiichiro Toyoda founded Toyota in 1937. Toyota employs three hundred thousand people. Neil Armstrong walked on the Moon in 1969.
The Thames flows through London. The Danube is the longest river in the European Union. The Moon orbits the Earth.
Insulin lowers blood sugar. Chlorophyll absorbs light in plants. Gold melts at 1064 degrees Celsius. Jane Austen wrote Emma in 1815.
Grace Hopper developed the first compiler. Hopper worked at Harvard University. Brazil won the World Cup five times.
"""

UNSEEN_CORPUS = """Rosalind Franklin photographed DNA in 1952. Rosalind Franklin was born in London in 1920. Charles Darwin published On the Origin of Species in 1859.
Madrid is the capital of Spain, not Barcelona. The Rhine flows through Germany. The Nile flows through Egypt. Mount Fuji is 3776 metres tall. Mount Fuji is located in Japan.
Sony was founded by Masaru Ibuka in 1946. Sony employs about one hundred thousand people. Yuri Gagarin orbited the Earth in 1961.
Mercury is the smallest planet in the Solar System. Jupiter is the largest planet in the Solar System. Copper conducts electricity. Mitochondria produce energy in cells.
Frida Kahlo painted The Two Fridas in 1939. Alexander Fleming discovered penicillin in 1928. Fleming worked at St Mary's Hospital. Iron melts at 1538 degrees Celsius.
Italy won the World Cup four times. Barcelona is a city in Spain. Beethoven composed nine symphonies.
"""

def dev_items():
    F = []  # (fact, family, question, kind, expected)
    def add(fact,fam,qs,kind,exp):
        for q in qs: F.append((fact,fam,q,kind,exp))
    # fact: python creator
    f="creator"
    add(f,"canonical",["Who created Python?"],"ans","Guido van Rossum")
    add(f,"case/punct",["who created python","WHO CREATED PYTHON???"],"ans","Guido van Rossum")
    add(f,"polite/wrapper",["Can you tell me who created Python?","Tell me who created Python.","I'd like to know who created Python."],"ans","Guido van Rossum")
    add(f,"passive",["Python was created by whom?","By whom was Python created?"],"ans","Guido van Rossum")
    add(f,"synonym verb",["Who made Python?","Who invented Python?","Who designed Python?"],"ans","Guido van Rossum")
    add(f,"nominal",["Who is the creator of Python?","Name the creator of Python.","Which person is the creator of Python?"],"ans","Guido van Rossum")
    add(f,"typo",["Who craeted Python?","Who created Pyhton?"],"ans","Guido van Rossum")
    add(f,"polar yes",["Did Guido van Rossum create Python?","Was Python created by Guido van Rossum?"],"yes","")
    add(f,"polar wrong",["Did Linus Torvalds create Python?"],"no_or_abstain","")
    f="release"
    add(f,"canonical",["When was Python released?"],"ans","1991")
    add(f,"wh variant",["In what year was Python released?","In what year did Python come out?","What year was Python first released?","What year did Python appear?"],"ans","1991")
    add(f,"nominal",["What is the release year of Python?","Python's release date is when?"],"ans","1991")
    f="location"
    add(f,"canonical",["Where is Mount Everest?","Where is Mount Everest located?"],"ans","Himalayas")
    add(f,"alias",["Where is Everest?","Where is Everest located?"],"ans","Himalayas")
    add(f,"cleft",["Which mountain range contains Everest?","Which range is Mount Everest in?"],"ans","Himalayas")
    add(f,"polar",["Is Mount Everest in the Himalayas?","Is Mount Everest located in the Himalayas?"],"yes","")
    f="height"
    add(f,"canonical",["How tall is Mount Everest?","What is the height of Mount Everest?","How high is Mount Everest?"],"ans","8849")
    add(f,"alias",["How tall is Everest?"],"ans","8849")
    f="capital"
    add(f,"canonical",["What is the capital of Australia?"],"ans","Canberra")
    add(f,"possessive",["What is Australia's capital?","Australia's capital city is which?"],"ans","Canberra")
    add(f,"cleft",["Which city is the capital of Australia?","Which city is Australia's capital?"],"ans","Canberra")
    add(f,"polar no",["Is Sydney the capital of Australia?","Is Sydney Australia's capital?"],"no","")
    add(f,"polar yes",["Is Canberra the capital of Australia?"],"yes","")
    f="nobel"
    add(f,"canonical",["Who won the Nobel Prize in Physics in 1921?"],"ans","Einstein")
    add(f,"passive",["Who was awarded the Nobel Prize in Physics in 1921?"],"ans","Einstein")
    add(f,"inverse",["What did Albert Einstein win?","What did Einstein win?"],"ans","Nobel Prize")
    add(f,"count",["How many Nobel Prizes did Marie Curie win?","How many Nobel Prizes has Marie Curie won?"],"ans","two")
    f="birth"
    add(f,"place",["Where was Marie Curie born?","What is Marie Curie's birthplace?"],"ans","Warsaw")
    add(f,"year",["When was Marie Curie born?","In what year was Marie Curie born?"],"ans","1867")
    add(f,"polar yes",["Was Marie Curie born in Warsaw?"],"yes","")
    add(f,"polar wrong",["Was Marie Curie born in Paris?"],"no_or_abstain","")
    f="founder"
    add(f,"canonical",["Who founded Quarn Beacon?","Who is the founder of Quarn Beacon?","Who started Quarn Beacon?"],"ans","Bree Hollis")
    add(f,"year",["When was Quarn Beacon founded?"],"ans","2019")
    add(f,"count",["How many people work at Quarn Beacon?","How many employees does Quarn Beacon have?"],"ans","forty")
    f="definition"
    add(f,"what is",["What is photosynthesis?","Define photosynthesis."],"ans","sunlight")
    add(f,"does",["What does the heart do?","What is the function of the heart?"],"ans","blood")
    add(f,"property",["At what temperature does water boil?","What is the boiling point of water?"],"ans","100")
    f="river"
    add(f,"superlative",["Which river is the longest in Africa?","What is the longest river in Africa?"],"ans","Nile")
    add(f,"flows",["Which country does the Amazon River flow through?"],"ans","Brazil")
    add(f,"polar wrong",["Does the Amazon River flow through Peru?"],"no_or_abstain","")
    f="author"
    add(f,"canonical",["Who wrote Hamlet?","Who is the author of Hamlet?","Hamlet was written by whom?"],"ans","Shakespeare")
    f="linux"
    add(f,"canonical",["Who developed Linux?","Who is the developer of Linux?"],"ans","Torvalds")
    f="turing"
    add(f,"canonical",["Where did Alan Turing work?","Where did Turing work?"],"ans","Bletchley")
    # negatives: nothing in corpus; must abstain
    add("none","unanswerable",["Who created Java?","When was Marie Curie's death?","How tall is Mount Kilimanjaro?","What is the capital of Brazil?","Who founded Acme Rocket Company?","Where was Albert Einstein born?","How many people work at Python?","Who won the Nobel Prize in Chemistry in 1921?"],"abstain","")
    return F


def held_items():
    H = []
    def A(fam,q,exp): H.append(("held",fam,q,"ans",exp))
    def Y(fam,q): H.append(("held",fam,q,"yes",""))
    def N(fam,q): H.append(("held",fam,q,"no_or_abstain",""))
    def X(fam,q): H.append(("held",fam,q,"abstain",""))
    A("canonical","Who wrote the first computer program?","Lovelace")
    A("canonical","Who founded Toyota?","Toyoda")
    A("canonical","Who invented the induction motor?","Tesla")
    A("canonical","Who developed the first compiler?","Hopper")
    A("canonical","Who wrote Emma?","Austen")
    A("canonical","When was Neil Armstrong on the Moon?","1969")
    A("canonical","Where was Nikola Tesla born?","Smiljan")
    A("canonical","What is the capital of Italy?","Rome")
    A("polite/wrapper","Could you tell me who founded Toyota?","Toyoda")
    A("polite/wrapper","Please tell me where Tesla was born.","Smiljan")
    A("case/punct","who wrote emma","Austen")
    A("case/punct","WHAT IS THE CAPITAL OF ITALY??","Rome")
    A("passive","Toyota was founded by whom?","Toyoda")
    A("passive","By whom was Emma written?","Austen")
    A("wh variant","In what year did Toyota get founded?","1937")
    A("wh variant","In what year was Ada Lovelace born?","1815")
    A("wh variant","What year did Jane Austen write Emma?","1815")
    A("nominal","Name the founder of Toyota.","Toyoda")
    A("nominal","What is the birthplace of Nikola Tesla?","Smiljan")
    A("synonym verb","Who made the induction motor?","Tesla")
    A("synonym verb","Who established Toyota?","Toyoda")
    A("possessive","What is Italy's capital?","Rome")
    A("possessive","Which city is Italy's capital?","Rome")
    A("cleft","Which city is the capital of Italy?","Rome")
    A("cleft","Which country is Mount Kilimanjaro in?","Tanzania")
    A("alias","Where is Kilimanjaro?","Tanzania")
    A("alias","What did Lovelace write?","program")
    A("alias","Where did Hopper work?","Harvard")
    A("height","How tall is Mount Kilimanjaro?","5895")
    A("height","How tall is Kilimanjaro?","5895")
    A("count","How many people work at Toyota?","three hundred thousand")
    A("count","How many times did Brazil win the World Cup?","five")
    A("superlative","What is the longest river in the European Union?","Danube")
    A("flows","Which city does the Thames flow through?","London")
    A("definition","What does insulin do?","blood sugar")
    A("definition","What does chlorophyll do?","light")
    A("definition","What orbits the Earth?","Moon")
    A("property","At what temperature does gold melt?","1064")
    A("property","What is the melting point of gold?","1064")
    A("typo","Who foudned Toyota?","Toyoda")
    A("typo","Where was Nikola Tesla bron?","Smiljan")
    Y("polar yes","Was Ada Lovelace born in London?")
    Y("polar yes","Is Rome the capital of Italy?")
    Y("polar yes","Did Kiichiro Toyoda found Toyota?")
    Y("polar yes","Does the Thames flow through London?")
    N("polar wrong","Is Milan the capital of Italy?")
    N("polar wrong","Was Nikola Tesla born in Paris?")
    N("polar wrong","Does the Thames flow through Paris?")
    N("polar wrong","Did Jane Austen write Hamlet?")
    X("unanswerable","Who founded Honda?")
    X("unanswerable","How tall is Mount Fuji?")
    X("unanswerable","When was Jane Austen born?")
    X("unanswerable","What is the capital of Spain?")
    X("unanswerable","How many people work at Honda?")
    X("unanswerable","Where was Grace Hopper born?")
    X("unanswerable","Who wrote Persuasion?")
    X("unanswerable","How tall is Toyota?")
    return H


def unseen_items():
    H = []
    def A(fam,q,exp): H.append(("h2",fam,q,"ans",exp))
    def Y(fam,q): H.append(("h2",fam,q,"yes",""))
    def N(fam,q): H.append(("h2",fam,q,"no_or_abstain",""))
    def X(fam,q): H.append(("h2",fam,q,"abstain",""))
    A("canonical","Who discovered penicillin?","Fleming")
    A("canonical","Who photographed DNA?","Franklin")
    A("canonical","Who composed nine symphonies?","Beethoven")
    A("canonical","Who painted The Two Fridas?","Kahlo")
    A("canonical","Where was Rosalind Franklin born?","London")
    A("canonical","What is the capital of Spain?","Madrid")
    A("canonical","When did Yuri Gagarin orbit the Earth?","1961")
    A("canonical","When was penicillin discovered?","1928")
    A("polite/wrapper","Could you tell me who founded Sony?","Ibuka")
    A("polite/wrapper","I would like to know when Darwin published On the Origin of Species.","1859")
    A("case/punct","who discovered penicillin??","Fleming")
    A("passive","Penicillin was discovered by whom?","Fleming")
    A("passive","By whom was Sony founded?","Ibuka")
    A("passive","Which person founded Sony?","Ibuka")
    A("wh variant","In what year was Sony founded?","1946")
    A("wh variant","What year did Frida Kahlo paint The Two Fridas?","1939")
    A("nominal","Name the founder of Sony.","Ibuka")
    A("nominal","What is the birthplace of Rosalind Franklin?","London")
    A("synonym verb","Who set up Sony?","Ibuka")
    A("synonym verb","Who found penicillin?","Fleming")
    A("possessive","What is Spain's capital?","Madrid")
    A("possessive","What is Fleming's workplace?","Hospital")
    A("cleft","Which country does the Rhine flow through?","Germany")
    A("cleft","Which city is the capital of Spain?","Madrid")
    A("cleft","Which planet is the largest in the Solar System?","Jupiter")
    A("alias","Where is Fuji?","Japan")
    A("alias","Where did Fleming work?","Hospital")
    A("height","How tall is Mount Fuji?","3776")
    A("height","What is the height of Fuji?","3776")
    A("count","How many people work at Sony?","hundred thousand")
    A("count","How many times did Italy win the World Cup?","four")
    A("count","How many symphonies did Beethoven compose?","nine")
    A("superlative","What is the smallest planet in the Solar System?","Mercury")
    A("definition","What do mitochondria do?","energy")
    A("definition","What does copper do?","electricity")
    A("property","At what temperature does iron melt?","1538")
    A("property","What is the melting point of iron?","1538")
    A("typo","Who discovred penicillin?","Fleming")
    A("typo","Who founded Sonny?","Ibuka")
    Y("polar yes","Was Rosalind Franklin born in London?")
    Y("polar yes","Is Madrid the capital of Spain?")
    Y("polar yes","Did Alexander Fleming discover penicillin?")
    Y("polar yes","Does the Rhine flow through Germany?")
    Y("polar yes","Was Sony founded by Masaru Ibuka?")
    N("polar wrong","Is Barcelona the capital of Spain?")
    N("polar wrong","Was Rosalind Franklin born in Paris?")
    N("polar wrong","Does the Rhine flow through Egypt?")
    N("polar wrong","Did Penicillin discover Alexander Fleming?")
    N("polar wrong","Did Beethoven paint The Two Fridas?")
    X("unanswerable","Who founded Panasonic?")
    X("unanswerable","How tall is Mount Etna?")
    X("unanswerable","When was Beethoven born?")
    X("unanswerable","What is the capital of Portugal?")
    X("unanswerable","How many people work at Nokia?")
    X("unanswerable","Where was Frida Kahlo born?")
    X("unanswerable","Who wrote Middlemarch?")
    X("unanswerable","How tall is Sony?")
    X("unanswerable","When did Darwin die?")
    return H



def grade(kind, exp, a):
    low = a.lower()
    abst = bool(ABST.search(a)) and not re.search(r"states (yes|no)", a)
    if kind == "ans":
        return "correct" if exp.lower() in low and not abst else ("abstain" if abst else "wrong")
    if kind == "yes":
        return "correct" if "states yes" in low else ("abstain" if abst else "wrong")
    if kind == "no":
        return "correct" if "states no" in low else ("abstain" if abst else "wrong")
    if kind == "no_or_abstain":
        return "correct" if ("states no" in low or abst) and "states yes" not in low else "wrong"
    return "correct" if abst else "wrong"


def run(items, docdir, cfg):
    def one(it):
        fact, fam, q, kind, exp = it
        a = answer(docdir, q, cfg)
        return (fam, q, kind, grade(kind, exp, a), a.replace("\n", " | ")[:170])
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(one, items))


def summ(res):
    ans = [r for r in res if r[2] not in ("abstain", "no_or_abstain")]
    neg = [r for r in res if r[2] in ("abstain", "no_or_abstain")]
    c = lambda L, k: sum(r[3] == k for r in L)
    return dict(na=len(ans), nn=len(neg), correct=c(ans, "correct"),
                abstain=c(ans, "abstain"), wrong=c(ans, "wrong"),
                neg_ok=c(neg, "correct"))


def main():
    global WORK
    FINAL = {"gate", "fallback", "rewrite", "typo", "polar", "strictgate", "seeds"}
    failures = []
    with tempfile.TemporaryDirectory(prefix="crms-v1-327-") as folder:
        root = Path(folder)
        WORK = str(root / "work")
        os.makedirs(WORK)
        sets = []
        for name, corpus, items in (("dev", DEV_CORPUS, dev_items()),
                                    ("held", HELD_CORPUS, held_items()),
                                    ("unseen", UNSEEN_CORPUS, unseen_items())):
            d = root / name
            d.mkdir()
            (d / "corpus.txt").write_text(corpus)
            sets.append((name, items, str(d)))
        print(f"{'set':7s} {'config':9s} {'correct':>9s} {'abstain':>8s} {'wrong':>6s} {'refuse-ok':>10s}")
        for name, items, d in sets:
            rows = {}
            for label, cfg in (("baseline", set()), ("layer", FINAL)):
                s = summ(run(items, d, cfg))
                rows[label] = s
                print(f"{name:7s} {label:9s} {s['correct']:4d}/{s['na']:<4d} {s['abstain']:8d} "
                      f"{s['wrong']:6d} {s['neg_ok']:6d}/{s['nn']:<3d}")
            b, l = rows["baseline"], rows["layer"]
            if l["wrong"] != 0:
                failures.append(f"{name}: layer answered {l['wrong']} answerable question(s) wrongly")
            if l["neg_ok"] != l["nn"]:
                failures.append(f"{name}: layer failed to decline {l['nn'] - l['neg_ok']} unanswerable question(s)")
            if l["correct"] < b["correct"]:
                failures.append(f"{name}: layer correct {l['correct']} < baseline {b['correct']}")
    if failures:
        print("FAILED:")
        for f in failures:
            print("  " + f)
        raise SystemExit(1)
    print("OK: layer keeps wrong answers at zero and does not reduce correct answers.")


if __name__ == "__main__":
    main()
