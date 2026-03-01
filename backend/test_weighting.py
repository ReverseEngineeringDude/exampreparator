import os
import sys

# Allow import of services
sys.path.append(os.path.join(os.path.dirname(__file__)))
import services

def test_answers():
    services.init_models()
    
    questions_data = [
        {"question": "What is Python?", "mark": 2},
        {"question": "Explain the architecture of a web application.", "mark": 10},
    ]
    
    print("Testing Fallback (No Notes)")
    for item in questions_data:
        q = item["question"]
        m = item["mark"]
        print(f"\n--- Question ({m} marks): {q} ---")
        
        # Determine mark instruction manually just for log
        if m <= 3:
            mark_instruction = "This is a short answer question. Provide a brief and concise answer (2-4 sentences)."
        elif m <= 7:
            mark_instruction = "This is a medium-length question. Provide a detailed answer with key points and explanations."
        else:
            mark_instruction = "This is an essay/long answer question. Provide a highly detailed, comprehensive answer with clear headings, bullet points, and elaborated explanations."

        answer_template = f'''
        Answer the following question according to General Knowledge or Standard Syllabus (KTU 2019 Scheme if applicable).
        
        INSTRUCTION BASED ON MARKS:
        {mark_instruction}
        
        QUESTION:
        {{}}
        '''
        ans = services.safe_generate(answer_template, q)
        print(f"Answer Length: {len(ans)} characters")
        print(f"Snippet:\n{ans[:200]}...")

if __name__ == "__main__":
    test_answers()
