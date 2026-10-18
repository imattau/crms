"""Composition retrieval coverage ablation for CRMS v1.2."""
import numpy as np
from v1_2_crms import Memory, Session, INSTRUCTION_TEMPLATES, TRANSFORMS, rand_input

OPS=['reverse','sort_asc','sort_desc','double','first','last']
ALL_OPS=[t for t in INSTRUCTION_TEMPLATES if t!='add_k']

def make_trials(n=200,seed=42):
    rng=np.random.RandomState(seed); trials=[]
    for _ in range(n):
        chosen={t:int(rng.randint(len(INSTRUCTION_TEMPLATES[t]))) for t in ALL_OPS}
        parts=rng.choice(OPS,2,replace=False).tolist()
        x=rand_input(rng.randint(3,5),rng)
        trials.append((chosen,parts,x))
    return trials

def score(trials,alpha,coverage):
    correct=0; first_ok=0; second_given_first=0; n1=0
    for ix,(chosen,parts,x) in enumerate(trials):
        mem=Memory(seed=42)
        for t,templates in INSTRUCTION_TEMPLATES.items():
            if t=='add_k': continue
            xs=templates if coverage else [templates[chosen[t]]]
            base=[1,2,3]
            for phrase in xs:
                mem.add_case(phrase,base,TRANSFORMS[t](base),t,{})
        sess=Session(mem,alpha=alpha)
        i1=INSTRUCTION_TEMPLATES[parts[0]][0]
        i2=INSTRUCTION_TEMPLATES[parts[1]][0]
        mid=TRANSFORMS[parts[0]](x); expected=TRANSFORMS[parts[1]](mid)
        first=sess._predict(i1,x)
        if first==mid:
            first_ok+=1; n1+=1
            second=sess._predict(i2,mid)
            if second==expected: second_given_first+=1
        result=sess.process(f'{i1}, then {i2}',x)
        correct+=result==expected
    return correct/len(trials),first_ok/len(trials),second_given_first/max(1,n1)

if __name__=='__main__':
    trials=make_trials()
    print('200 paired composition trials; control: one random phrase per transform; fix: all phrase templates stored')
    print(f"{'alpha':>5} {'case coverage':>16} {'process acc':>12} {'step1 acc':>10} {'step2|step1':>13}")
    for a in (0.,.5,1.):
        for coverage,label in ((False,'one template'),(True,'all templates')):
            x,p1,p2=score(trials,a,coverage)
            print(f'{a:5.1f} {label:>16} {x:12.3f} {p1:10.3f} {p2:13.3f}')
