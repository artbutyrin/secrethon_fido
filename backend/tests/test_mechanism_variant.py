"""A protein change after the gene is not part of the target search ("KRAS G12C inhibitor" -> KRAS)."""
from backend.app.mechanism import parse_mechanism


def test_variant_is_split_off():
    for text, target, variant in [("KRAS G12C inhibitor", "KRAS", "G12C"), ("BRAF V600E inhibitor", "BRAF", "V600E"),
                                  ("EGFR T790M", "EGFR", "T790M"), ("anti-PCSK9 antibody", "PCSK9", None),
                                  ("S1P receptor modulator", "S1P receptor", None), ("P2X7 antagonist", "P2X7", None),
                                  ("HTT antisense oligonucleotide", "HTT", None)]:
        m = parse_mechanism(text)
        assert (m.target_query, m.variant) == (target, variant), text
    assert parse_mechanism("KRAS G12C inhibitor").action == "inhibit"
