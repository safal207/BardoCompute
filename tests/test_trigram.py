from bardocompute import BardoLine, BardoTrigram


def test_trigram_tracks_source_target_and_transition_count() -> None:
    trigram = BardoTrigram(
        BardoLine.between(0, 1),
        BardoLine.stable(1),
        BardoLine.between(1, 0),
    )

    assert trigram.source_bits == (0, 1, 1)
    assert trigram.target_bits == (1, 1, 0)
    assert trigram.transition_count == 2
    assert trigram.settle().source_bits == (1, 1, 0)
    assert trigram.settle().transition_count == 0
