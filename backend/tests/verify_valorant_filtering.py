import sys
import os

# 현재 디렉토리를 path에 추가하여 backend 모듈 import 가능하게 함
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.services.news.esports import is_noise, get_display_league_tag

def test_valorant_filtering():
    print("=== Testing Valorant Filtering Logic ===")
    
    # Test Case 1: Game Changers (Noise)
    gc_match = {
        "league": {"name": "VCT Game Changers"},
        "serie": {"full_name": "VCT 2026: Game Changers EMEA Series 1"},
        "tournament": {"name": "Group Stage"}
    }
    assert is_noise(gc_match) == True, "Failed to filter Game Changers"
    print("✅ Game Changers filtered correctly")

    # Test Case 2: VCT Main Event (Not Noise)
    vct_match = {
        "league": {"name": "VCT"},
        "serie": {"full_name": "VCT 2026: EMEA Kickoff"},
        "tournament": {"name": "Playoffs"}
    }
    assert is_noise(vct_match) == False, "Incorrectly filtered VCT Main Event"
    print("✅ VCT Main Event kept correctly")
    
    # Test Case 3: Showmatch (Noise)
    showmatch = {
         "league": {"name": "Valorant"},
         "serie": {"name": "Showmatch"},
         "tournament": {"name": "Tally Ho"}
    }
    assert is_noise(showmatch) == True, "Failed to filter Showmatch"
    print("✅ Showmatch filtered correctly")

    # Test Case 4: Display Tag Generation
    tag = get_display_league_tag(vct_match)
    print(f"Generated Tag: {tag}")
    assert tag == "VCT 2026: EMEA Kickoff", f"Tag generation failed. Expected 'VCT 2026: EMEA Kickoff', got '{tag}'"
    print("✅ Display Tag generated correctly")

    # Test Case 5: Fallback Tag
    fallback_match = {
        "league": {"name": "Valorant Champions Tour"},
        "serie": {},
        "tournament": {}
    }
    tag_fallback = get_display_league_tag(fallback_match)
    print(f"Fallback Tag: {tag_fallback}")
    assert tag_fallback == "Valorant Champions Tour", "Fallback tag failed"
    print("✅ Fallback Tag generated correctly")

if __name__ == "__main__":
    try:
        test_valorant_filtering()
        print("\n🎉 All tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test Failed: {e}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
