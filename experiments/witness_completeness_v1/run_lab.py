"""BARDO evidence-completeness lab. Synthetic stress tests, not a production claim.

Normal mode requires byte-exact upstream modules. --excerpt-mode is only a
local development cross-check and must not be presented as a full source run.
No classifier is trained: exact feature collisions establish an information bound.
"""
from __future__ import annotations
import argparse
import dataclasses
import hashlib
import itertools
import json
import platform
import random
import sys
import time
from pathlib import Path

SOURCE = "0b9da9e61eed562797473c8a841902247a2aa946"
SOURCE_BLOBS = {
    "logos_learning.py": "0720a774f83c10b5ff6f9cb43147056ab9d22046",
    "hardware_contract.py": "74c58cd44a8c492ac734180bf79d3e56361fdafb",
}
N = 71
CRITICAL = set(range(18)) | set(range(53,71))
LOADS = (0,1,2,3,4,5,8,16,32)
SEEDS = (11,29,47)
PER_SEED = 128

def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def canonical(value: object) -> bytes:
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()

def mask_of(indices) -> int:
    return sum(1 << i for i in set(indices))

def bitmap(results) -> int:
    return sum(int(not r.valid) << i for i,r in enumerate(results))

def oracle(results, policy: set[int]) -> bool:
    return any(not results[i].valid for i in policy)

def pack_raw(results) -> bytes:
    word = 0
    for lane,r in enumerate(results):
        settled = r.settled_lines[0] | r.settled_lines[1]<<3 | r.settled_lines[2]<<6
        item = (int(r.valid) | r.trigram_index<<1 | int(r.policy_allow)<<9 |
                settled<<10 | int(r.any_discontinuous)<<19 |
                int(r.any_transition)<<20 | r.target_count<<21)
        require(0 <= item < 1<<23,"TX1 field overflow")
        word |= item << (23*lane)
    return word.to_bytes((len(results)*23+7)//8,"little")

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path("evidence"))
    parser.add_argument("--excerpt-mode",action="store_true")
    args = parser.parse_args()
    if args.excerpt_mode:
        sys.path.insert(0,str(Path(__file__).parent/"local_excerpt"))
    from bardocompute import logos_learning as ll
    from bardocompute import hardware_contract as hw
    source_info = {}
    for name,module in (("logos_learning.py",ll),("hardware_contract.py",hw)):
        raw = Path(module.__file__).read_bytes()
        blob = hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
        source_info[name] = {"git_blob":blob,"sha256":sha(raw),"expected_blob":SOURCE_BLOBS[name]}
        if not args.excerpt_mode:
            require(blob==SOURCE_BLOBS[name],f"unmatched upstream source: {name}")
    require(ll.LANES==N and ll.WITNESS_COUNT==4,"changed lane/witness contract")
    neutral = hw.evaluate_trigram((0,0,0))
    invalid = hw.evaluate_trigram((1,0,0))
    valid = tuple(hw.evaluate_trigram(x) for x in itertools.product((0,2,3,4,5,6),repeat=3))
    require(all(r.valid for r in valid) and not invalid.valid,"bad fixture contract")
    args.output.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter()
    rows=[]
    examples=[]
    all_checks=0
    for distractors in LOADS:
        collisions=raw_collisions=bitmap_errors=0
        for seed in SEEDS:
            rng=random.Random(seed*1000+distractors)
            for case in range(PER_SEED):
                focus=rng.randrange(53,71)
                base=[rng.choice(valid) for _ in range(N)]
                base[focus]=base[50]=neutral
                decoys=sorted(rng.sample(range(18,50),distractors))
                for i in decoys: base[i]=invalid
                positive=base.copy(); negative=base.copy()
                positive[focus]=invalid; negative[50]=invalid
                p=ll.LearningSample(tuple(positive),1,focus)
                q=ll.LearningSample(tuple(negative),0,50)
                require(oracle(p.results,CRITICAL) and not oracle(q.results,CRITICAL),"label mismatch")
                require(ll.frame_stats(p.results)==ll.frame_stats(q.results),"unmatched global facts")
                equal=ll.encode_hybrid(p)==ll.encode_hybrid(q)
                raw_equal=ll.encode_raw(p)==ll.encode_raw(q)
                collisions+=int(equal); raw_collisions+=int(raw_equal)
                require(equal==(distractors>=4),"unexpected cutoff: falsifies lab hypothesis")
                require(not raw_equal,"RAW lost the control signal")
                for sample in (p,q):
                    payload=bitmap(sample.results).to_bytes(9,"little")
                    answer=bool(int.from_bytes(payload,"little") & mask_of(CRITICAL))
                    bitmap_errors+=int(answer!=bool(sample.label))
                    require(len(pack_raw(sample.results))==205,"raw width")
                all_checks+=1
                if seed==SEEDS[0] and case==0:
                    examples.append({"distractors":distractors,"positive_focus":focus,
                        "negative_focus":50,"decoy_lanes":decoys,
                        "positive":[dataclasses.asdict(r) for r in positive],
                        "negative":[dataclasses.asdict(r) for r in negative],
                        "hybrid_features_equal":equal,
                        "positive_hybrid_sha256":sha(canonical(ll.encode_hybrid(p))),
                        "negative_hybrid_sha256":sha(canonical(ll.encode_hybrid(q)))})
        pairs=len(SEEDS)*PER_SEED
        rows.append({"ordinary_distractors":distractors,"pairs":pairs,"frames":2*pairs,
            "opposite_label_hybrid_collisions":collisions,"raw_feature_collisions":raw_collisions,
            "bitmap_errors":bitmap_errors,"paired_accuracy_upper_bound":1-collisions/(2*pairs)})

    # Relabel six physical positions and the query together; no semantic labels
    # are leaked into the unchanged upstream encoder. All 720 layouts are kept.
    collision_layouts=0
    positions=(18,19,20,21,50,60)
    for layout in itertools.permutations(positions):
        p=[neutral]*N; q=p.copy()
        for i in layout[:4]:p[i]=q[i]=invalid
        p[layout[4]]=invalid; q[layout[5]]=invalid
        a=ll.LearningSample(tuple(p),1,layout[4]); b=ll.LearningSample(tuple(q),0,layout[5])
        require(oracle(p,{layout[4]}) and not oracle(q,{layout[4]}),"permutation oracle")
        collision_layouts+=int(ll.encode_hybrid(a)==ll.encode_hybrid(b))
    require(collision_layouts==48,"layout bound changed")

    # Independent exhaustive reference: direct boolean scan, not a bitwise oracle.
    exhaustive=0
    for data in itertools.product((False,True),repeat=8):
        encoded=sum(int(v)<<i for i,v in enumerate(data))
        for policy in itertools.product((False,True),repeat=8):
            expected=any(d and p for d,p in zip(data,policy))
            actual=bool(encoded & sum(int(v)<<i for i,v in enumerate(policy)))
            require(actual==expected,"8-lane bitmap discrepancy")
            exhaustive+=1
    rng=random.Random(20260905)
    random_checks=100_000
    for _ in range(random_checks):
        data=[bool(rng.getrandbits(1)) for _ in range(N)]
        # Include sparse queries, empty queries and singletons; dense queries alone
        # would produce almost exclusively positive answers and be a weak control.
        policy=rng.sample(range(N),rng.choice((0,1,2,3,8,36,71)))
        expected=any(data[i] for i in policy)
        encoded=sum(int(v)<<i for i,v in enumerate(data)).to_bytes(9,"little")
        require(bool(int.from_bytes(encoded,"little") & mask_of(policy))==expected,"71-lane discrepancy")

    # Predicate boundary: a validity bitmap is NOT sufficient for another task.
    rising=hw.evaluate_trigram((2,2,0))
    left=[neutral]*N; right=left.copy(); right[0]=rising
    require(bitmap(left)==bitmap(right),"validity bitmap should match")
    require(left[0].policy_allow!=right[0].policy_allow,"negative task control failed")
    # Policy freshness: a one-bit answer for one scope is not reusable for another.
    data=[neutral]*N; data[60]=invalid
    require(not oracle(data,{18}) and oracle(data,{60}),"policy drift control failed")

    result={"schema_version":1,"experiment":"bardo-witness-completeness-v1",
        "source_commit":SOURCE,"source_mode":"LOCAL_EXCERPT_ONLY" if args.excerpt_mode else "FULL_PINNED_UPSTREAM",
        "source_modules":source_info,"python":platform.python_version(),
        "design":{"synthetic":True,"seed_list":list(SEEDS),"pairs_per_seed_per_load":PER_SEED,
            "loads":list(LOADS),"labels":"invalid exists in critical outer region",
            "stress":"right critical fault vs late ordinary fault; earlier ordinary invalid distractors",
            "training_performed":False,"timings_are_not_a_speed_benchmark":True},
        "overload":rows,"total_pairs":all_checks,"total_frames":2*all_checks,
        "layout_permutations":{"layouts":720,"collisions":collision_layouts},
        "bitmap":{"full_8_lane_state_policy_cases":exhaustive,"random_71_lane_state_policy_cases":random_checks,
            "errors":0,"bitmap_bytes":9,"full_tx1_bytes":205,
            "raw_payload_reduction_fraction":1-9/205,
            "scope":"any subset query over lane validity only; source is trusted; no cryptographic certificate",
            "other_predicate_counterexample_confirmed":True,"one_bit_policy_drift_counterexample_confirmed":True},
        "non_claims":["No production traces or FPGA execution", "No universal learning/CPU advantage",
            "No financial savings or investor demand measured","Bitmap is a conventional exact baseline, not a novel algorithm",
            "No authentication, completeness-of-source or freshness proof", "Original single-fault benchmark not invalidated"],
        "elapsed_seconds":time.perf_counter()-started,"status":"PASS"}
    (args.output/"result.json").write_text(json.dumps(result,indent=2)+"\n")
    (args.output/"counterexamples.json").write_text(json.dumps(examples,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    print("evidence_completeness_lab=pass")

if __name__=="__main__":main()
