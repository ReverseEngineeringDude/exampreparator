import os
import time
import json
import re
import shutil
import faiss
import numpy as np
import google.generativeai as genai
from PyPDF2 import PdfReader
from sentence_transformers import SentenceTransformer, util
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY

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
_api_keys = []
_current_key_idx = 0
_gemini_configured = False

def init_models():
    global _sbert_model, _api_keys, _current_key_idx, _gemini_configured
    if not _gemini_configured:
        if os.path.exists(API_KEY_PATH):
            with open(API_KEY_PATH) as f:
                # Support multiple keys: one per line, ignore blank lines
                _api_keys = [line.strip() for line in f.readlines() if line.strip()]
            if _api_keys:
                genai.configure(api_key=_api_keys[0])
                _current_key_idx = 0
                _gemini_configured = True
                print(f"[KeyRotator] Loaded {len(_api_keys)} API key(s).")
    if _sbert_model is None:
        _sbert_model = SentenceTransformer(MODEL_NAME_SBERT)

def rotate_api_key():
    """Switch to the next available API key and reconfigure genai. Returns True if rotated."""
    global _current_key_idx
    if len(_api_keys) <= 1:
        return False
    _current_key_idx = (_current_key_idx + 1) % len(_api_keys)
    new_key = _api_keys[_current_key_idx]
    genai.configure(api_key=new_key)
    print(f"[KeyRotator] Rotated to key index {_current_key_idx}.")
    return True

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
You are an exam paper parser. Extract all questions from the question paper below.

RULES:
1. Extract the EXACT question text — do not rephrase or summarize.
2. Match each question to its correct marks. Look for patterns: "(3 marks)", "[7]", "3M", "CO1 - 1 Mark", section headers like "PART A - 3 marks each", etc.
3. Number the questions exactly as they appear in the paper.
4. Each question must be independent — do not mix up question numbers.

Return ONLY a valid JSON array. No markdown, no explanation, no extra text.

Format:
[
  {{
    "id": 1,
    "question_number": "1",
    "question_text": "Exact question text here",
    "marks": 1,
    "category": "short"
  }}
]

Category rules:
- "short" = 1 to 3 marks
- "medium" = 4 to 7 marks
- "long" = 8 or more marks

QUESTION PAPER:
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

    # 3. BUILD valid_qs WITH FULL CONTEXT AND INSTRUCTIONS
    valid_qs = []

    # Pre-map all questions with IDs, contexts, and instructions
    for q_item in questions_data:
        question = q_item.get('question_text', q_item.get('question', ''))
        mark_val = q_item.get('marks', q_item.get('mark', 0))
        
        if not question or len(question.strip()) < 5 or mark_val == 0 or str(mark_val).lower() in ["unmarked", "null", "none"]:
            continue
            
        try:
            mark_val = int(mark_val)
        except (ValueError, TypeError):
            mark_val = 1
            
        # Fine-grained per-mark instruction (matches exam answer rubric)
        m_label = f"{mark_val} Mark{'s' if mark_val != 1 else ''}"
        if mark_val == 1:
            m_val = 1
            instr = "Exactly 1 sentence. One definition or one fact only. No elaboration."
        elif mark_val == 2:
            m_val = 1
            instr = "Exactly 2-3 sentences. One concept with a brief explanation."
        elif mark_val == 3:
            m_val = 3
            instr = "One paragraph of 4-6 sentences. Define + explain + one example."
        elif mark_val == 4:
            m_val = 3
            instr = "One paragraph of 6-8 sentences. Cover main points with explanation."
        elif mark_val == 5:
            m_val = 3
            instr = "Two paragraphs. Definition, explanation, examples, and significance."
        elif mark_val == 6:
            m_val = 7
            instr = "Two solid paragraphs. Concept + working + real-world use."
        elif mark_val == 7:
            m_val = 7
            instr = "Three paragraphs. Intro/definition, detailed explanation with subtopics, example/application."
        elif mark_val == 8:
            m_val = 7
            instr = "Three to four paragraphs. Add comparison or advantages/disadvantages."
        elif mark_val <= 10:
            m_val = 7
            instr = "Four to five paragraphs with subheadings. Full coverage of the topic."
        else:
            m_val = 7
            instr = "Essay format. Introduction, multiple headed sections, examples, conclusion."
            
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
            "topic_area": q_item.get("topic", ""),
            "category": q_item.get("category", ""),
            "question_number": q_item.get("question_number", ""),
            "mark_val": m_val,
            "raw_marks": mark_val,
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
        def generate_single_answer(q):
            """Generate answer for ONE question at a time — prevents answer mismatch."""
            marks = q["raw_marks"]
            question_text = q["topic"]
            instruction = q["instruction"]
            context = q["context"]

            prompt = f"""You are an expert exam answer writer for university-level examinations.

Answer ONLY this ONE question below. Do not answer anything else.

QUESTION: {question_text}
MARKS: {marks}
SUBJECT AREA: {q.get("topic_area", "General")}

STRICT LENGTH RULE FOR {marks} MARK(S):
{instruction}

REFERENCE CONTEXT (use if helpful, ignore if irrelevant):
{context[:2000]}

ABSOLUTE RULES:
1. Always write a complete answer. NEVER say "sorry", "I cannot", or "I don't know".
2. Write from your academic knowledge if context is insufficient.
3. DO NOT exceed or fall short of the required length for {marks} mark(s).
4. Match the answer format to the question — "compare" means a comparison, "list" means bullet points, "explain" means paragraphs, "define" means a definition.
5. Use clear academic English.
6. Output ONLY the answer text. No JSON. No preamble. Just the answer."""

            model = genai.GenerativeModel(MODEL_NAME_GEMINI)
            keys_tried = 0
            for attempt in range(5):
                try:
                    response = model.generate_content(prompt)
                    if response and hasattr(response, 'text') and response.text.strip():
                        return response.text.strip()
                except Exception as e:
                    err = str(e)
                    print(f"Single answer error (attempt {attempt+1}): {err}")
                    if "429" in err or "quota" in err.lower():
                        rotated = rotate_api_key()
                        keys_tried += 1
                        if rotated:
                            # Switched to a fresh key — short pause then retry
                            time.sleep(2)
                        else:
                            # Only one key or all exhausted — exponential backoff
                            wait = min(15 * (2 ** keys_tried), 120)
                            print(f"All keys rate-limited — waiting {wait}s...")
                            time.sleep(wait)
                    else:
                        time.sleep(3)
            return ""

        total_qs = len(valid_qs)
        for idx, q in enumerate(valid_qs):
            pct = 50 + int(40 * (idx / total_qs))
            set_progress(pct, f"Generating answer {idx+1}/{total_qs} ({q['mark_label']})...")
            answer = generate_single_answer(q)
            q["answerHtmlMarkdown"] = answer
            time.sleep(2.5)  # shorter delay now that key rotation handles quota bursts
            
    # Final assembly
    for q in valid_qs:
        ans = q.get("answerHtmlMarkdown", "")
        if not ans or ans.strip().lower() in ["null", "none", ""] or len(ans.strip()) < 20:
            ans = "Answer could not be generated for this question. Please try re-uploading."
            
        final_output.append({
            "id": q["id"],
            "question_number": q.get("question_number", ""),
            "topic": q["topic"],
            "topic_area": q.get("topic_area", ""),
            "category": q.get("category", ""),
            "mark": q["mark_label"],
            "rawMark": str(q.get("raw_marks", q["mark_val"])),
            "answerHtmlMarkdown": ans
        })
        
    set_progress(95, "Finalizing report...")
    return questions_data, final_output

def safe_generate(prompt_template, content):
    init_models()
    # Truncate content if too large for prompt
    truncated_content = content[:15000]
    prompt = prompt_template.format(truncated_content)

    keys_tried = 0
    for attempt in range(5):
        try:
            model = genai.GenerativeModel(MODEL_NAME_GEMINI)
            response = model.generate_content(prompt)
            if response and hasattr(response, 'text'):
                return response.text.strip()
        except Exception as e:
            error_msg = str(e)
            print(f"safe_generate error (attempt {attempt+1}): {error_msg}")
            if "429" in error_msg or "quota" in error_msg.lower():
                rotated = rotate_api_key()
                keys_tried += 1
                if rotated:
                    time.sleep(2)  # brief pause after key switch
                else:
                    wait = min(15 * (2 ** keys_tried), 120)
                    print(f"All keys rate-limited — waiting {wait}s...")
                    time.sleep(wait)
                    if keys_tried >= len(_api_keys) * 2:
                        return "API_QUOTA_ERROR"
            else:
                time.sleep(3)
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
            "diagram": "Mermaid.js flowchart code OR null"
        }},
        ...
    ]
    
    DIAGRAM RULES (very important):
    - Only include a diagram if it genuinely helps understand the topic (architecture, process flow, lifecycle).
    - Use ONLY valid Mermaid.js flowchart syntax. Always start with "graph TD" or "graph LR".
    - Node labels must NOT contain quotes, parentheses, or special characters. Use simple words only.
    - Use --> for arrows. Example of a VALID diagram: "graph TD; A[Start] --> B[Process] --> C[End]"
    - If you are unsure the syntax is correct, set "diagram" to null.
    - NEVER use subgraph, classDef, or style blocks — keep it simple.
    
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