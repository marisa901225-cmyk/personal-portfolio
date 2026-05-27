from __future__ import annotations


def should_notify(match: dict, game_slug: str) -> bool:
    league_name = (match.get("league") or {}).get("name") or ""

    if game_slug == "league-of-legends":
        allowed_lol = [
            "LCK",
            "LPL",
            "First Stand",
            "First-Stand",
            "MSI",
            "Mid-Season Invitational",
            "Worlds",
            "World Championship",
            "Esports World Cup",
            "EWC",
        ]
        return any(word in league_name for word in allowed_lol)

    if game_slug == "valorant":
        if "Challengers" in league_name or "VCL" in league_name:
            return False
        allowed_vct = ["VCT", "Champions", "Masters"]
        return any(word in league_name for word in allowed_vct)

    return True


def run_demo() -> None:
    test_cases = [
        {"game": "league-of-legends", "league": "LCK Spring 2025", "expected": True},
        {"game": "league-of-legends", "league": "LEC Winter 2025", "expected": False},
        {"game": "valorant", "league": "Valorant Champions Tour 2025: Pacific Kickoff", "expected": True},
        {"game": "valorant", "league": "Valorant Challengers 2025: Korea Split 1", "expected": False},
    ]

    passed = 0
    for case in test_cases:
        result = should_notify({"league": {"name": case["league"]}}, case["game"])
        if result == case["expected"]:
            passed += 1
        print(f"{case['game']} / {case['league']} => {result} (expected {case['expected']})")

    print(f"Passed {passed}/{len(test_cases)} checks")


if __name__ == "__main__":
    run_demo()
