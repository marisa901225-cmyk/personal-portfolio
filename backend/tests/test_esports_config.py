from backend.core.esports_config import infer_league_tag_from_name, lol_league_tagger


def test_lol_league_tagger_maps_international_events() -> None:
    for league_name in (
        "First Stand 2026",
        "First-Stand 2026",
        "Mid-Season Invitational 2026",
        "2026 World Championship",
        "Esports World Cup 2026",
        "EWC 2026",
    ):
        assert lol_league_tagger({"league": {"name": league_name}}) == "Worlds/MSI"


def test_infer_league_tag_from_name_recognizes_international_and_major_regions() -> None:
    assert (
        infer_league_tag_from_name(
            "GEN vs JDG - First Stand 2026",
            "league-of-legends",
        )
        == "Worlds/MSI"
    )
    assert (
        infer_league_tag_from_name(
            "FNC vs G2 - LEC Spring 2026",
            "league-of-legends",
        )
        == "LEC"
    )
    assert (
        infer_league_tag_from_name(
            "NS.EA vs HLE - LCK Challengers Spring 2026",
            "league-of-legends",
        )
        == "LCK-CL"
    )
