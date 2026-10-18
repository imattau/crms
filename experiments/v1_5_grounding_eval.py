"""Evaluate example-grounded CRMS rule induction across its primitive library."""
import numpy as np
from v1_3_crms import (TRANSFORMS, Memory, Session, infer_transform,
                       apply_transform)

TRIALS=100
DEMO_COUNTS=(1,2,3)
OPS=list(TRANSFORMS)

def examples_for(name,params,n,rng):
    pairs=[]
    for _ in range(n):
        x=[int(z) for z in rng.randint(-10,20,size=int(rng.randint(3,7)))]
        y=TRANSFORMS[name](x,**params)
        pairs.append((x,y))
    return pairs

def target_candidate(name,params,cand):
    return cand[0]==name and cand[1]==params

def run():
    rng=np.random.RandomState(2027)
    totals={n:{'unique':0,'ambiguous':0,'none':0,'wrong_unique':0,
               'generalize':0,'bind':0,'partial_para':0,'zero_overlap':0}
            for n in DEMO_COUNTS}
    denominators={n:0 for n in DEMO_COUNTS}
    per_op={name:{n:{'unique':0,'ambiguous':0,'none':0,'correct_unique':0}
                  for n in DEMO_COUNTS} for name in OPS}
    for name in OPS:
      for trial in range(TRIALS):
        k=int(rng.choice([-5,-4,-3,-2,-1,1,2,3,4,5])) if name=='add_k' else None
        params={'k':k} if name=='add_k' else {}
        all_examples=examples_for(name,params,3,rng)
        for n in DEMO_COUNTS:
          ex=all_examples[:n]
          cands=infer_transform(ex)
          denominators[n]+=1
          row=per_op[name][n]
          if len(cands)==1:
            totals[n]['unique']+=1; row['unique']+=1
            correct=target_candidate(name,params,cands[0])
            if correct:
              row['correct_unique']+=1
              # Holdout generalization through the inferred transform.
              testx=[int(z) for z in rng.randint(-10,20,size=int(rng.randint(3,7)))]
              pred=apply_transform(*cands[0],testx)
              expected=TRANSFORMS[name](testx,**params)
              if pred==expected:
                totals[n]['generalize']+=1
              # Bind a completely new phrase, then query on a new input.
              phrase='invert these entries'
              mem=Memory(seed=42)
              mem.add_case(phrase,ex[-1][0],ex[-1][1],cands[0][0],cands[0][1])
              if Session(mem,alpha=1.0).process(phrase,testx)==expected:
                totals[n]['bind']+=1
              # A paraphrase sharing one content token can retrieve the binding.
              partial='invert this sequence'
              if Session(mem,alpha=1.0).process(partial,testx)==expected:
                totals[n]['partial_para']+=1
              # No-overlap phrasing remains unknown until separately demonstrated.
              no_overlap='rotate velvet objects'
              if Session(mem,alpha=1.0).process(no_overlap,testx) is None:
                totals[n]['zero_overlap']+=1
            else:
              totals[n]['wrong_unique']+=1
          elif len(cands)>1:
            totals[n]['ambiguous']+=1; row['ambiguous']+=1
          else:
            totals[n]['none']+=1; row['none']+=1
    print('Example-grounded rule induction; 100 trials per primitive; fixed synthetic list domain')
    print(f"{'operation':<12} {'1 demo unique':>14} {'2 demos unique':>15} {'3 demos unique':>15} {'2 demo ambiguous':>17}")
    for name in OPS:
      vals=[per_op[name][n]['unique']/TRIALS for n in DEMO_COUNTS]
      amb=per_op[name][2]['ambiguous']/TRIALS
      print(f'{name:<12} {vals[0]:14.2f} {vals[1]:15.2f} {vals[2]:15.2f} {amb:17.2f}')
    print('\nAggregate outcomes (300 cases per demo count):')
    print(f"{'demos':>5} {'unique rule':>12} {'ambiguous':>11} {'no fit':>8} {'wrong unique':>13} {'accepted rule → new input':>26} {'phrase bind':>13} {'partial paraphrase':>19} {'no-overlap abstains':>20}")
    for n in DEMO_COUNTS:
      t=totals[n]; d=denominators[n]
      accepted=per_op
      # Count only rules whose held-out output matched exactly.
      corr=t['generalize']
      print(f"{n:5d} {t['unique']/d:12.2f} {t['ambiguous']/d:11.2f} {t['none']/d:8.2f} {t['wrong_unique']/d:13.2f} {corr/d:26.2f} {t['bind']/d:13.2f} {t['partial_para']/d:19.2f} {t['zero_overlap']/d:20.2f}")
    print('\nNote: the phrase-binding columns are conditional on unique, correct induction; reported as fractions of all cases.')

if __name__=='__main__': run()
