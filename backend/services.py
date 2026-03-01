import os
import time
import json
import re
import shutil
import torch
import faiss
import numpy as np
import google.generativeai as genai
from flask import current_app
from PyPDF2 import PdfReader
from transformers import AutoTokenizer, AutoModel
from sentence_transformers import SentenceTransformer, util
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT

PROGRESS_FILE = os.path.join(os.path.dirname(__file__), "progress.json")

def set_progress(percent, message):
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump({"percent": percent, "message": message}, f)
    except Exception:
        pass

# ==========================================
# CONSTANTS & CONFIG
# ==========================================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
API_KEY_PATH = os.path.join(os.path.dirname(BASE_DIR), "apikey.txt")
MODEL_NAME_SBERT = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_NAME_GEMINI = "models/gemini-2.5-flash"

_sbert_model = None
_tokenizer = None
_auto_model = None
_gemini_configured = False

def init_models():
    global _sbert_model, _tokenizer, _auto_model, _gemini_configured
    if not _gemini_configured:
        if os.path.exists(API_KEY_PATH):
            with open(API_KEY_PATH) as f:
                api_key = f.read().strip()
            genai.configure(api_key=api_key)
            _gemini_configured = True
    if _sbert_model is None:
        _sbert_model = SentenceTransformer(MODEL_NAME_SBERT)

# ==========================================
# EXTRACTION UTILS
# ==========================================
def extract_text_from_pdfs(folder_path):
    extracted_texts = []
    if not os.path.exists(folder_path): return ["No notes uploaded."]
    for file_name in os.listdir(folder_path):
        if file_name.lower().endswith(".pdf"):
            pdf_path = os.path.join(folder_path, file_name)
            try:
                with open(pdf_path, "rb") as pdf_file:
                    reader = PdfReader(pdf_file)
                    text = "".join([page.extract_text() or "" for page in reader.pages])
                    if text.strip(): extracted_texts.append(text)
            except Exception as e: print(f"Error: {e}")
    return extracted_texts

# ==========================================
# CORE FIX: GENERATE ANSWERS WITH STRICT MARKS
# ==========================================
def generate_answers(grouped_questions_text, notes_folder):
    set_progress(10, "Extracting text from documents...")
    init_models()
    notes_texts = extract_text_from_pdfs(notes_folder)
    
    # 1. PARSE QUESTIONS FIRST
    if not grouped_questions_text.strip():
        return [], []

    set_progress(20, "Analyzing question formats and marks...")

    extract_template = '''
    ACT AS AN EXAM PAPER PARSER. 
    Analyze the text provided below. Your goal is to extract every unique question and its specific mark weightage.

    STRICT RULES FOR MARKS:
    1. Look for SECTION HEADERS first. (e.g., "PART A - Answer all questions. Each carries 3 marks").
    2. If a question is inside that section, assign it the section's mark (3).
    3. If a question has marks in brackets like [7] or (1) at the end, use that.
    4. If the mark is not found, GUESS based on the question complexity:
       - Simple definitions ("What is...") = 1 mark.
       - Explanations/Comparisons ("Explain...", "Differentiate...") = 3 marks.
       - Detailed Architecture/Derivations ("Design...", "Derive...", "Detailed note on...") = 7 marks.
    
    5. ONLY output these three mark values: 1, 3, or 7. Round any other value to the nearest of these three.

    OUTPUT FORMAT:
    Return ONLY a valid JSON array. No markdown, no "here is the json".
    [
      {{"question": "The text of the question", "mark": 1}},
      {{"question": "The text of the question", "mark": 3}},
      {{"question": "The text of the question", "mark": 7}}
    ]

    TEXT TO PARSE:
    {}
    '''
    
    raw_json_str = safe_generate(extract_template, grouped_questions_text)
    if raw_json_str == "API_QUOTA_ERROR":
        return [], "API Rate Limit Exceeded. Please wait before generating again."

    print(f"DEBUG: raw_json_str Length = {len(raw_json_str)}")
    print(f"DEBUG: raw_json_str (first 200 chars): {raw_json_str[:200]}")
    
    # Robust JSON Cleaning
    try:
        json_match = re.search(r'\[.*\]', raw_json_str, re.DOTALL)
        if json_match:
            questions_data = json.loads(json_match.group())
            print(f"DEBUG: Successfully parsed {len(questions_data)} questions.")
        else:
            print("DEBUG: No JSON array match found!")
            questions_data = []
    except Exception as e:
        print(f"JSON Parse Error: {e}")
        questions_data = []

    set_progress(30, "Indexing reference notes for context...")

    # 2. VECTOR SEARCH SETUP
    valid_notes = [n for n in notes_texts if len(n.strip()) > 10]
    
    if valid_notes:
        note_embeddings = _sbert_model.encode(valid_notes)
        index = faiss.IndexFlatL2(note_embeddings.shape[1])
        index.add(note_embeddings)
    else:
        index = None

    # 3. GENERATION BATCHING
    final_output = []
    
    # Group questions by mark
    grouped_questions = {
        1: {"label": "1 Mark", "instr": "Answer in exactly 1-2 concise sentences. Be very brief.", "items": []},
        3: {"label": "3 Marks", "instr": "Answer in a short paragraph (3-5 sentences). Focus on the core definition and one key point.", "items": []},
        7: {"label": "7 Marks", "instr": "Provide a comprehensive long-form answer. Use bold headings, bullet points, and include a Mermaid.js diagram if the topic allows for a flowchart or architecture.", "items": []}
    }

    # Assign IDs and retrieve context
    valid_qs = []
    for q_item in questions_data:
        question = q_item.get('question', '')
        mark_val = q_item.get('mark', 0)
        
        if not question or len(question.strip()) < 5 or mark_val == 0 or str(mark_val).lower() in ["unmarked", "null", "none"]:
            continue
            
        m_val = 1 if mark_val <= 1 else (3 if mark_val <= 3 else 7)
        
        # RAG Retrieval
        context = ""
        if index is not None and valid_notes:
            q_emb = _sbert_model.encode([question])
            _, indices = index.search(q_emb, k=2)
            context = "\n\n".join([valid_notes[idx] for idx in indices[0] if idx < len(valid_notes)])
            
        if len(context) < 50:
            context = "Notes are insufficient. Use general academic knowledge."
            
        q_id = len(valid_qs) + 1
        q_obj = {
            "id": q_id,
            "topic": question,
            "mark_val": m_val,
            "context": context
        }
        valid_qs.append(q_obj)
        grouped_questions[m_val]["items"].append(q_obj)

    # 3. CONSOLIDATED SINGLE BATCH GENERATION
    valid_qs = []
    
    # Pre-map all questions with IDs, contexts, and instructions
    for q_item in questions_data:
        question = q_item.get('question', '')
        mark_val = q_item.get('mark', 0)
        
        if not question or len(question.strip()) < 5 or mark_val == 0 or str(mark_val).lower() in ["unmarked", "null", "none"]:
            continue
            
        try:
            mark_val = int(mark_val)
        except ValueError:
            mark_val = 1
            
        # Determine instruction based on mark
        if mark_val <= 1:
            m_val = 1
            instr = "Answer in exactly ONE WORD. Provide only the most critical defining term or acronym. Be absolutely minimal."
            m_label = "1 Mark"
        elif mark_val <= 3:
            m_val = 3
            instr = "Answer in exactly 1 to 3 short lines. Focus strictly on the core definition and one key point. Do not exceed 3 lines."
            m_label = "3 Marks"
        else:
            m_val = 7
            instr = "Provide a comprehensive, long-form answer. Use bold headings, bullet points, and include a Mermaid.js diagram if the topic allows for a flowchart or architecture."
            m_label = "7 Marks"
            
        # RAG Retrieval
        context = ""
        if index is not None and valid_notes:
            q_emb = _sbert_model.encode([question])
            _, indices = index.search(q_emb, k=2)
            context = "\n\n".join([valid_notes[idx] for idx in indices[0] if idx < len(valid_notes)])
            
        if len(context) < 50:
            context = "Notes are insufficient. Use general academic knowledge."
            
        q_id = len(valid_qs) + 1
        q_obj = {
            "id": q_id,
            "topic": question,
            "mark_val": m_val,
            "mark_label": m_label,
            "instruction": instr,
            "context": context
        }
        valid_qs.append(q_obj)

    short_qs = [q for q in valid_qs if q["mark_val"] <= 3]
    long_qs = [q for q in valid_qs if q["mark_val"] >= 7]
    
    batches = []
    if short_qs:
        batches.append(("Short Questions (1 & 3 Marks)", short_qs))
    if long_qs:
        batches.append(("Long Questions (7 Marks)", long_qs))

    final_output = []
    if valid_qs:
        for batch_name, current_qs in batches:
            set_progress(50, f"Generating {batch_name}...")
            
            batch_prompt = f'''
            YOU ARE AN EXAM ANSWER GENERATOR.
            
            Below is a JSON array containing {len(current_qs)} questions.
            Each question has its own specific 'context' (reference notes) and 'instruction' (how long/detailed the answer should be).
            
            You MUST generate an answer for EVERY SINGLE QUESTION in the array, explicitly following its individual 'instruction'. Do not skip any.
            
            To ensure you don't mix up questions, YOUR OUTPUT FORMAT MUST BE EXCLUSIVELY A valid JSON array of exactly {len(current_qs)} objects.
            For each object, you MUST restate the "id", the "topic", and the "instruction", and then provide your "answerHtmlMarkdown", exactly like this:
            [
                {{{{
                    "id": 1, 
                    "topic": "Define IoT",
                    "instruction": "Answer in exactly ONE WORD.",
                    "answerHtmlMarkdown": "Network"
                }}}},
                {{{{
                    "id": 2, 
                    "topic": "...",
                    "instruction": "...",
                    "answerHtmlMarkdown": "..."
                }}}}
            ]
            
            DO NOT wrap the JSON in markdown codeblocks like ```json . Just output the raw array starting with [ and ending with ].
            YOU MUST RETURN EXACTLY {len(current_qs)} JSON OBJECTS IN THE ARRAY.

            QUESTIONS TO ANSWER:
            {{}}
            '''
            
            payload = json.dumps([{"id": q["id"], "topic": q["topic"], "instruction": q["instruction"], "context": q["context"]} for q in current_qs], ensure_ascii=False)
            
            answer_raw = safe_generate(batch_prompt, payload)
            if answer_raw == "API_QUOTA_ERROR":
                return [], "API Rate Limit Exceeded. Please wait before generating again."
                
            # Parse returned JSON array
            try:
                json_match = re.search(r'\[.*\]', answer_raw, re.DOTALL)
                if json_match:
                    batch_answers = json.loads(json_match.group())
                    for ans_obj in batch_answers:
                        for q in valid_qs:
                            if str(q["id"]) == str(ans_obj.get("id", "")):
                                q["answerHtmlMarkdown"] = ans_obj.get("answerHtmlMarkdown", "Sorry, could not generate an answer.")
            except Exception as e:
                print(f"Batch JSON Parse Error for {batch_name}: {e}")
                
            import time
            time.sleep(3) # Tiny sleep safely between the distinct batches
            
    # Final assembly
    for q in valid_qs:
        ans = q.get("answerHtmlMarkdown", "")
        if not ans or ans.strip().lower() in ["null", "none", ""]:
            ans = "Sorry, I could not generate an answer for this question from the provided notes."
            
        final_output.append({
            "id": q["id"],
            "topic": q["topic"],
            "mark": grouped_questions[q["mark_val"]]["label"],
            "rawMark": str(q["mark_val"]),
            "answerHtmlMarkdown": ans
        })
        
    set_progress(95, "Finalizing report...")
    return questions_data, final_output

def safe_generate(prompt_template, content):
    init_models()
    model = genai.GenerativeModel(MODEL_NAME_GEMINI)
    # Truncate content if too large for prompt
    truncated_content = content[:15000] 
    prompt = prompt_template.format(truncated_content)
    
    for attempt in range(3):
        try:
            response = model.generate_content(prompt)
            if response and hasattr(response, 'text'):
                return response.text.strip()
        except Exception as e:
            error_msg = str(e)
            print(f"Error calling Gemini API: {error_msg}")
            if "429" in error_msg and "quota" in error_msg.lower():
                return "API_QUOTA_ERROR"
            time.sleep(2)
    return ""

def generate_pdf_from_text(text_content, output_pdf_path):
    """Generates a PDF from markdown-like text using ReportLab."""
    doc = SimpleDocTemplate(output_pdf_path, pagesize=letter)
    story = []
    styles = getSampleStyleSheet()
    
    styles.add(ParagraphStyle(name='Justify', parent=styles['Normal'], alignment=TA_JUSTIFY))
    
    lines = text_content.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            story.append(Spacer(1, 12))
            continue
            
        if line.startswith('# '):
            style = styles['Heading1']
            text = line[2:]
        elif line.startswith('## '):
            style = styles['Heading2']
            text = line[3:]
        elif line.startswith('### '):
            style = styles['Heading3']
            text = line[4:]
        elif line.startswith('- ') or line.startswith('* '):
            style = styles['Normal'] # Bullet points
            text = "• " + line[2:]
        else:
            style = styles['Normal']
            text = line

        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        import re
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text) # Bold
        text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)     # Italic
        
        p = Paragraph(text, style)
        story.append(p)

    doc.build(story)

def process_data(notes_folder, questions_folder, extracted_folder):
    init_models()
    # 1. Extract raw text from all question PDFs
    all_qp_text = ""
    if os.path.exists(questions_folder):
        for filename in os.listdir(questions_folder):
            if filename.endswith(".pdf"):
                with open(os.path.join(questions_folder, filename), "rb") as f:
                    reader = PdfReader(f)
                    all_qp_text += f"\n--- FILE: {filename} ---\n"
                    all_qp_text += "".join([p.extract_text() for p in reader.pages if p.extract_text()])

    # 2. Use the improved generator
    questions_summary, answers = generate_answers(all_qp_text, notes_folder)
    
    # Save answers (app.py expects this file to exist to build download_pdf)
    out_txt = os.path.join(BASE_DIR, "generated_answers.txt")
    with open(out_txt, "w", encoding="utf-8") as f:
        # Save as json string representation for download_pdf fallback or similar logic.
        f.write(f"Questions:\n{json.dumps(questions_summary)}\n\nAnswers:\n{json.dumps(answers)}")
    
    return questions_summary, answers

def generate_study_material(notes_folder):
    """Generates grouped topics and key points from notes for the Study Mode."""
    init_models()
    
    notes_texts = extract_text_from_pdfs(notes_folder)
    combined_notes = "\n\n".join(notes_texts)
    
    if not combined_notes.strip():
        return []

    prompt = '''
    Analyze the following academic notes and extract the main topics.
    For each topic, provide a brief summary (under 50 words) and 3-5 key bullet points.
    
    Output the result EXCLUSIVELY in this specific JSON format (no markdown, no extra text):
    [
        {{
            "topic": "Topic Name",
            "summary": "Brief summary of the topic.",
            "points": ["Key point 1", "Key point 2", "Key point 3"]
        }},
        ...
    ]
    
    NOTES CONTENT:
    {}
    '''
    
    try:
        json_output = safe_generate(prompt, combined_notes)
        if json_output == "API_QUOTA_ERROR":
            return "API Rate Limit Exceeded. Please wait before generating again."
        
        start_index = json_output.find('[')
        end_index = json_output.rfind(']')
        
        if start_index != -1 and end_index != -1 and end_index > start_index:
            cleaned_json = json_output[start_index:end_index+1]
            study_data = json.loads(cleaned_json)
            return study_data
        else:
            print(f"❌ Could not find JSON array in output: {json_output[:100]}...")
            return []

    except Exception as e:
        print(f"❌ Error generating study material: {e}")
        return []

def generate_study_from_questions(questions_folder, notes_folder=None):
    """Generates grouped topics and key points from Question Papers (and optional Notes) for the Study Mode."""
    set_progress(10, "Extracting text from Question Papers...")
    init_models()
    
    qp_texts = extract_text_from_pdfs(questions_folder)
    combined_qp = "\n\n".join(qp_texts)
    
    if not combined_qp.strip() or combined_qp == "No notes uploaded.":
        return []

    set_progress(40, "Extracting text from Reference Notes...")
    notes_context = "No notes provided. Use general knowledge."
    if notes_folder:
        notes_texts = extract_text_from_pdfs(notes_folder)
        extracted_notes = "\n\n".join(notes_texts)
        if extracted_notes.strip() and extracted_notes != "No notes uploaded.":
            notes_context = extracted_notes

    content_payload = f"""
    QUESTION PAPER CONTENT:
    {combined_qp}
    
    REFERENCE NOTES CONTENT:
    {notes_context}
    """

    set_progress(70, "AI analyzing topics and generating Study Guide...")
    prompt_template = '''
    Analyze the following Question Paper text to identify the main topics and key questions asked.
    For each identified topic, provide a brief summary (simple notes) and 3-5 key bullet points.
    
    Use the provided 'Reference Notes' content as the primary source of information if available. 
    If Reference Notes are empty or irrelevant, use your general knowledge to explain the topics found in the Question Paper.
    
    Output the result EXCLUSIVELY in this specific JSON format:
    [
        {{
            "topic": "Topic Name (from Question Paper)",
            "summary": "Simple explanation/notes about this topic.",
            "points": ["Key concept 1", "Key concept 2", "Key concept 3"],
            "diagram": "Mermaid.js code for a flowchart/diagram if applicable, else null"
        }},
        ...
    ]
    
    If a topic can be better explained with a flowchart or diagram, provide the Mermaid.js code in the "diagram" field.
    Example diagram code: "graph TD; A-->B; B-->C;"
    
    {} 
    '''
    
    try:
        json_output = safe_generate(prompt_template, content_payload)
        if json_output == "API_QUOTA_ERROR":
            return "API Rate Limit Exceeded. Please wait before generating again."
        
        start_index = json_output.find('[')
        end_index = json_output.rfind(']')
        
        if start_index != -1 and end_index != -1 and end_index > start_index:
            cleaned_json = json_output[start_index:end_index+1]
            study_data = json.loads(cleaned_json)
            set_progress(100, "Study Material Generation Complete!")
            return study_data
        else:
            return []

    except Exception as e:
        print(f"❌ Error generating study from questions: {e}")
        return []