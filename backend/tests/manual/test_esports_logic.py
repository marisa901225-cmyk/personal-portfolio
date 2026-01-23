import sys
import os

# Filter Logic extracted from the code for testing
def should_notify(match, game_slug):
    league_name = (match.get("league") or {}).get("name") or ""
    
    print(f"Testing [{game_slug}] League: '{league_name}'")
    
    is_valid_league = False
    
    if game_slug == "league-of-legends":
        allowed_lol = [
            'LCK', 'LPL', 
            'First Stand', 'First-Stand',
            'MSI', 'Mid-Season Invitational', 
            'Worlds', 'World Championship', 
            'Esports World Cup', 'EWC'
        ] 
        is_valid_league = any(word in league_name for word in allowed_lol)
        
    elif game_slug == "valorant":
        if 'Challengers' in league_name or 'VCL' in league_name:
            is_valid_league = False
        else:
            allowed_vct = ['VCT', 'Champions', 'Masters']
            is_valid_league = any(word in league_name for word in allowed_vct)
    else:
        # Default mock
        is_valid_league = True

    return is_valid_league

# Test Cases
test_cases = [
    # LoL Valid
    {"game": "league-of-legends", "league": "LCK Spring 2025", "expected": True},
    {"game": "league-of-legends", "league": "LPL Spring 2025", "expected": True},
    {"game": "league-of-legends", "league": "LCK CL Spring 2025", "expected": True}, # Should be valid (contains LCK)
    
    # LoL International (New)
    {"game": "league-of-legends", "league": "First Stand 2026", "expected": True},
    {"game": "league-of-legends", "league": "Mid-Season Invitational 2026", "expected": True},
    {"game": "league-of-legends", "league": "MSI 2026", "expected": True},
    {"game": "league-of-legends", "league": "2026 World Championship", "expected": True},
    {"game": "league-of-legends", "league": "Esports World Cup 2026", "expected": True},
    {"game": "league-of-legends", "league": "EWC 2026", "expected": True},
    
    # LoL Invalid
    {"game": "league-of-legends", "league": "LEC Winter 2025", "expected": False},
    {"game": "league-of-legends", "league": "LCS Spring 2025", "expected": False},
    {"game": "league-of-legends", "league": "LCO Split 1", "expected": False},

    # Valorant Valid
    {"game": "valorant", "league": "Valorant Champions Tour: Pacific", "expected": True}, # Contains VCT ? No, wait. 'Valorant Champions Tour' usually abbreviated?
    # Actually API usually returns "VCT 2024: Pacific Stage 1" or "Valorant Champions Tour 2024: Pacific"
    # The logic checks for 'VCT', 'Champions', 'Masters'.
    # If the name is "Valorant Champions Tour", 'Champions' is in it.
    {"game": "valorant", "league": "Valorant Champions Tour 2025: Pacific Kickoff", "expected": True},
    {"game": "valorant", "league": "VCT 2025: Americas Kickoff", "expected": True},
    {"game": "valorant", "league": "Valorant Champions 2025", "expected": True},
    {"game": "valorant", "league": "VCT 2025: Masters Bangkok", "expected": True},

    # Valorant Invalid
    {"game": "valorant", "league": "Valorant Challengers 2025: Korea Split 1", "expected": False},
    {"game": "valorant", "league": "VCL 2025: Japan Split 1", "expected": False},
    {"game": "valorant", "league": "Valorant Challengers Ascension", "expected": False},
]

print("=== Running Filter Logic Tests ===")
passed = 0
failed = 0

for case in test_cases:
    match = {"league": {"name": case["league"]}}
    result = should_notify(match, case["game"])
    
    status = "PASS" if result == case["expected"] else "FAIL"
    if status == "PASS":
        passed += 1
    else:
        failed += 1
        
    print(f"Result: {result} | Expected: {case['expected']} -> {status}\n")

print(f"=== Summary ===")
print(f"Passed: {passed}")
print(f"Failed: {failed}")
print(f"Total: {len(test_cases)}")
