import os
import sys

# Allow import of services
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
import services

with open('test_question_paper_input.txt', 'r') as f:
    text = f.read()

extract_template = '''
Extract all relevant questions from the following text. The questions should be meaningful and related to the subject.
Identify the exact marks/weightage for EACH question. 

CRITICAL INSTRUCTION FOR MARKS:
Often, marks are NOT written next to the individual question. Instead, they are declared in the section header! 
For example: "PART A: Answer all questions. Each question carries 1 mark." -> In this case, EVERY question under PART A is a 1 mark question.
You MUST infer the mark for a question by looking at its preceding section header if it doesn't have an explicit mark attached to it.
Ignore metadata like 'Group 1' or filenames.

Output format MUST strictly be (one question per line):
[Mark] Question Text
Example 1:
[1] Define the term Internet of Things (IoT).
Example 2:
[7] Explain the architecture of a DBMS with a diagram.

Try your absolute hardest to find the correct mark. Only use [Unknown] if it is truly impossible to tell from the entire context.

TEXT:
{}
'''

services.init_models()
res = services.safe_generate(extract_template, text)
print("=== RAW AI OUTPUT ===")
print(res)
print("=====================")
import re
for line in res.split("\n"):
    line = line.strip()
    if not line: continue
    mark_match = re.search(r'\[(.*?)\]\s*(.*)', line)
    if mark_match:
        print(f"MATCHED: Mark={mark_match.group(1)} | Q={mark_match.group(2)}")
    else:
        print(f"FAILED TO MATCH: {line}")
