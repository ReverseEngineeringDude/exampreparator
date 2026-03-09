import sys
import os
sys.path.append(os.path.abspath('backend'))
import services

questions_summary, answers = services.process_data('backend/uploads/notes', 'backend/uploads/questions', 'backend/extracted_text')
print(f"Final Output Count: {len(answers)}")
