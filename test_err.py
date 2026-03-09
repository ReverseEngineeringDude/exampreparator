import json

questions_data = {"question": "What is IoT?", "mark": 1}
try:
    for i, item in enumerate(questions_data):
        question = item.get("question", "").strip()
except Exception as e:
    print(f"Type: {type(e)}, str(e): {str(e)}")
