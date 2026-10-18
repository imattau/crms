"""Teacher-guided CRMS training: examples ground new phrases to known rules."""
from v1_3_crms import Memory, Session, TRANSFORMS, infer_transform

# Curated teacher demonstrations. Labels below are used only to generate and
# score examples; the learner receives phrase + input/output pairs only.
TEACHING = {
 'reverse': ('invert these entries', [
     ([1,2,3],[3,2,1]),                 # ambiguous with descending sort
     ([2,8,1],[1,8,2]),
 ]),
 'sort_asc': ('line up from least to greatest', [
     ([3,-1,5],[-1,3,5]), ([8,2,0,6],[0,2,6,8])]),
 'sort_desc': ('line up from greatest to least', [
     ([3,-1,5],[5,3,-1]), ([8,2,0,6],[8,6,2,0])]),
 'double': ('scale every value by a factor of two', [
     ([3,-2,5],[6,-4,10]), ([0,7,-1],[0,14,-2])]),
 'evens': ('retain values divisible by two', [
     ([3,4,8,-1],[4,8]), ([0,5,7,2],[0,2])]),
 'odds': ('retain values leaving remainder one after division by two', [
     ([3,4,8,-1],[3,-1]), ([0,5,7,2],[5,7])]),
 'add_k': ('shift every value upward by three', [
     ([1,2,5],[4,5,8]), ([-2,0,4],[1,3,7])]),
 'first': ('keep the initial entry', [
     ([2,8,1],[2]), ([9,-3,6,4],[9])]),
 'last': ('keep the final entry', [
     ([2,8,1],[1]), ([9,-3,6,4],[4])]),
}

class GroundedSession(Session):
    # Require a strong best match and margin for non-exact paraphrase retrieval.
    # Exact learned phrase associations use direct case retrieval.
    MIN_SCORE=0.60
    MIN_MARGIN=0.08
    def _predict(self,instruction,input_list):
        retrieved=self.memory.retrieve(instruction,k=len(self.memory.cases),alpha=self.alpha)
        if not retrieved: return None
        exact=[c for _,c in retrieved if c['instruction'].lower()==instruction.lower()]
        if exact:
            case=exact[-1]
            if case['transform'] is None: return case['output'] if case['input']==list(input_list) else None
            from v1_3_crms import apply_transform
            return apply_transform(case['transform'],case['params'],input_list)
        best_score,best=retrieved[0]
        if best_score < self.MIN_SCORE: return None
        next_rule_score=max((score for score,case in retrieved[1:]
                             if (case['transform'],case['params']) != (best['transform'],best['params'])),default=-1.0)
        if best_score-next_rule_score < self.MIN_MARGIN: return None
        if best['transform'] is None: return None
        from v1_3_crms import apply_transform
        return apply_transform(best['transform'],best['params'],input_list)

    def teach_from_examples(self, phrase, examples, min_examples=2):
        """Commit only after at least min_examples imply one known rule."""
        for n in range(min_examples, len(examples)+1):
            candidates=infer_transform(examples[:n])
            if len(candidates)==1:
                name,params=candidates[0]
                x,y=examples[n-1]
                self.memory.add_case(phrase,x,y,name,params)
                return {'status':'learned','rule':name,'params':params,'n_examples':n,
                        'alternatives':candidates}
        candidates=infer_transform(examples)
        return {'status':'ambiguous' if candidates else 'no_fit',
                'candidates':candidates,'n_examples':len(examples)}

def main():
    sess=GroundedSession(Memory(seed=42),alpha=0.5)
    print('=== CRMS teacher-guided phrase learning ===')
    print('Rule inference sees demonstrations only; transform labels are not passed to learner.\n')
    learned=0; checked=0; correct=0
    for intended,(phrase,demos) in TEACHING.items():
        # Check whether the phrase resolves before the teacher supplies examples.
        probe=[11,3,7]
        before=sess.process(phrase,probe)
        result=sess.teach_from_examples(phrase,demos,min_examples=2)
        test=[-4,2,9,1,6]
        expected=TRANSFORMS[intended](test,k=3) if intended=='add_k' else TRANSFORMS[intended](test)
        after=sess.process(phrase,test)
        passed=after==expected
        learned+=result['status']=='learned'; checked+=1; correct+=passed
        print(f"{intended:9s} prior={str(before):>8s} demos={result['n_examples'] if result['status']=='learned' else len(demos)} "
              f"inferred={result.get('rule',result['status']):>9s} heldout={'PASS' if passed else 'FAIL'}")

    # A distinct, one-example ambiguity: reversal of an ascending list is also sort-descending.
    check=GroundedSession(Memory(seed=42),alpha=0.5)
    ambiguous=check.teach_from_examples('turn it around',[([1,2,3],[3,2,1])],min_examples=1)
    unresolved=check.process('turn it around',[4,1,3])
    resolved=check.teach_from_examples('turn it around',[
        ([1,2,3],[3,2,1]),([2,8,1],[1,8,2])],min_examples=2)
    resolved_out=check.process('turn it around',[4,1,3])
    print(f"\nAmbiguity gate: one demo -> {ambiguous['status']} ({len(ambiguous.get('candidates',[]))} candidates), "
          f"query={unresolved}; second contrastive demo -> {resolved['status']} "
          f"({resolved.get('rule')}); output={resolved_out}")

    # A contradictory example should not overwrite a learned case.
    bad=check.teach_from_examples('a contradictory phrase',[
        ([1,2,3],[3,2,1]),([1,2,3],[1,2,3])],min_examples=2)
    print(f"Conflict gate: {bad['status']} ({len(bad.get('candidates',[]))} candidates)")
    print(f"\nLearned {learned}/{checked} phrases; held-out accuracy {correct}/{checked}.")

if __name__=='__main__': main()
