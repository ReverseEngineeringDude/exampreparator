import sys
import os
sys.path.append(os.path.abspath('backend'))
import services
import google.generativeai as genai

# Try to directly hit limit
def test_quota():
    services.init_models()
    model = genai.GenerativeModel(services.MODEL_NAME_GEMINI)
    try:
        response = model.generate_content("Generate a 1000 word essay about nothing.")
        print("Success, quota has not been hit yet. Run test_direct.py in a hot loop.")
    except Exception as e:
        error_msg = str(e)
        print(f"Caught: {error_msg}")
        print(f"repr: {repr(error_msg)}")
        print(f"type: {type(e)}")
        print(f"429 in error_msg: {'429' in error_msg}")
        print(f"quota in error_msg.lower(): {'quota' in error_msg.lower()}")
        print(f"code attribute: {getattr(e, 'code', 'N/A')}")

for _ in range(25):
    test_quota()
