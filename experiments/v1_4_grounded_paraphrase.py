"""Ground an unseen phrase from input/output examples using CRMS primitives."""
from v1_3_crms import Memory, Session, infer_transform

def learn_phrase(memory, instruction, examples):
    """Bind a new phrase to a known transform only when examples identify one rule."""
    candidates=infer_transform(examples)
    if len(candidates)!=1:
        return False, candidates
    transform,params=candidates[0]
    x,y=examples[-1]
    memory.add_case(instruction,x,y,transform,params)
    return True,candidates

def main():
    phrase='invert these entries'
    examples=[([2,7,1],[1,7,2]),([5,3,9,0],[0,9,3,5])]
    test=[6,1,4]
    memory=Memory(seed=42)
    # Existing familiar case does not bridge a zero-overlap phrase by itself.
    memory.add_case('reverse the list',[1,2,3],[3,2,1],'reverse',{})
    zero_shot=Session(memory,alpha=1.0).process(phrase,test)
    learned,candidates=learn_phrase(memory,phrase,examples)
    output=Session(memory,alpha=1.0).process(phrase,test)
    print('zero-shot output:',zero_shot)
    print('inferred rule:',candidates)
    print('accepted demonstrations:',learned)
    print('after grounding:',output)
    print('expected:',test[::-1])

if __name__=='__main__':main()
