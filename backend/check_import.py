import sys
import os
sys.path.append("/home/dlckdgn/personal-portfolio")
try:
    from backend.services.alarm import llm_logic
    print("Import success!")
except Exception:
    import traceback
    traceback.print_exc()
