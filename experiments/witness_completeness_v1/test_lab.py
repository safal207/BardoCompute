"""Focused checks for the experiment itself (not a claim of production safety)."""
import itertools
import unittest
from bardocompute import hardware_contract as hw
from bardocompute import logos_learning as ll
from run_lab import bitmap, mask_of, oracle, pack_raw

class LabChecks(unittest.TestCase):
    def test_all_512_single_lane_serialization_roundtrips(self):
        for lines in itertools.product(range(8),repeat=3):
            r=hw.evaluate_trigram(lines)
            word=int.from_bytes(pack_raw([r]),'little')
            actual=(bool(word&1),(word>>1)&255,bool((word>>9)&1),
                    ((word>>10)&7,(word>>13)&7,(word>>16)&7),
                    bool((word>>19)&1),bool((word>>20)&1),(word>>21)&3)
            expected=(r.valid,r.trigram_index,r.policy_allow,r.settled_lines,
                      r.any_discontinuous,r.any_transition,r.target_count)
            self.assertEqual(actual,expected)

    def pair(self,decoys):
        neutral=hw.evaluate_trigram((0,0,0)); invalid=hw.evaluate_trigram((1,0,0))
        p=[neutral]*71; q=p.copy()
        for i in range(18,18+decoys):p[i]=q[i]=invalid
        p[60]=invalid;q[50]=invalid
        return ll.LearningSample(tuple(p),1,60),ll.LearningSample(tuple(q),0,50)

    def test_single_fault_control_distinguishable(self):
        a,b=self.pair(0)
        self.assertEqual(ll.frame_stats(a.results),ll.frame_stats(b.results))
        self.assertNotEqual(ll.encode_hybrid(a),ll.encode_hybrid(b))

    def test_three_decoys_distinguishable(self):
        a,b=self.pair(3)
        self.assertNotEqual(ll.encode_hybrid(a),ll.encode_hybrid(b))

    def test_four_decoys_identical_features_opposite_labels(self):
        a,b=self.pair(4)
        self.assertEqual(ll.encode_hybrid(a),ll.encode_hybrid(b))
        self.assertNotEqual(ll.encode_raw(a),ll.encode_raw(b))
        self.assertNotEqual(a.label,b.label)

    def test_labels_and_focus_not_read_by_encoder(self):
        a,_=self.pair(4)
        altered=ll.LearningSample(a.results,0,None)
        self.assertEqual(ll.encode_hybrid(a),ll.encode_hybrid(altered))

    def test_bitmap_and_raw_byte_widths(self):
        a,b=self.pair(4)
        for sample in (a,b):
            self.assertEqual(len(pack_raw(sample.results)),205)
            self.assertEqual(len(bitmap(sample.results).to_bytes(9,'little')),9)
            self.assertEqual(bool(bitmap(sample.results)&mask_of({60})),oracle(sample.results,{60}))

    def test_bit_position_boundaries(self):
        neutral=hw.evaluate_trigram((0,0,0)); invalid=hw.evaluate_trigram((1,0,0))
        for i in (0,7,8,63,64,70):
            frame=[neutral]*71;frame[i]=invalid
            self.assertEqual(int.from_bytes(bitmap(frame).to_bytes(9,'little'),'little'),1<<i)
        self.assertEqual(mask_of({0,70}),1+(1<<70))
        self.assertEqual(mask_of([]),0)

    def test_bitmap_cannot_answer_every_other_predicate(self):
        neutral=hw.evaluate_trigram((0,0,0)); rising=hw.evaluate_trigram((2,2,0))
        a=[neutral]*71;b=a.copy();b[0]=rising
        self.assertEqual(bitmap(a),bitmap(b))
        self.assertNotEqual(a[0].policy_allow,b[0].policy_allow)

if __name__=='__main__':unittest.main()
