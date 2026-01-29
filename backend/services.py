import os
import time
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

# ==========================================
# CONSTANTS & CONFIG
# ==========================================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
API_KEY_PATH = os.path.join(BASE_DIR, "apikey.txt")
MODEL_NAME_SBERT = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_NAME_GEMINI = "models/gemini-2.5-flash"

# Global model cache
_sbert_model = None
_tokenizer = None
_auto_model = None
_gemini_configured = False

# ==========================================
# INITIALIZATION
# ==========================================
def init_models():
    """Lazily initialize models to avoid reloading on every request."""
    global _sbert_model, _tokenizer, _auto_model, _gemini_configured

    if not _gemini_configured:
        if os.path.exists(API_KEY_PATH):
            with open(API_KEY_PATH) as f:
                api_key = f.read().strip()
            genai.configure(api_key=api_key)
            _gemini_configured = True
            print("✅ Gemini API Configured")
        else:
            print("⚠️ Warning: API Key file not found. Gemini features will not work.")

    if _sbert_model is None:
        print("⏳ Loading SBERT model...")
        _sbert_model = SentenceTransformer(MODEL_NAME_SBERT)
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME_SBERT)
        _auto_model = AutoModel.from_pretrained(MODEL_NAME_SBERT)
        print("✅ SBERT model loaded")

# ==========================================
# TEXT EXTRACTION
# ==========================================
def extract_text_from_pdfs(folder_path):
    extracted_texts = []
    if not os.path.exists(folder_path):
        return ["No notes uploaded."]
        
    for file_name in os.listdir(folder_path):
        if file_name.lower().endswith(".pdf"):
            pdf_path = os.path.join(folder_path, file_name)
            print(f"🔍 Extracting text from {file_name}...")
            try:
                with open(pdf_path, "rb") as pdf_file:
                    reader = PdfReader(pdf_file)
                    if reader.is_encrypted:
                        try:
                            reader.decrypt("")
                        except:
                            print(f"❌ Unable to decrypt {file_name}. Skipping...")
                            continue
                    
                    text = ""
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                    
                    if text.strip():
                        extracted_texts.append(text)
            except Exception as e:
                print(f"❌ Error extracting text from {file_name}: {e}")
                
    return extracted_texts if extracted_texts else ["No text extracted."]

def extract_text_from_questions(questions_folder, extracted_folder):
    """Extracts text from question PDFs and saves to txt files (internal use)."""
    if not os.path.exists(questions_folder):
        return
        
    for filename in os.listdir(questions_folder):
        if filename.lower().endswith(".pdf"):
            pdf_path = os.path.join(questions_folder, filename)
            text = ""
            try:
                with open(pdf_path, "rb") as f:
                    reader = PdfReader(f)
                    for page in reader.pages:
                        text += page.extract_text() or ""
                
                if text.strip():
                    out_path = os.path.join(extracted_folder, f"{os.path.splitext(filename)[0]}.txt")
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(text)
            except Exception as e:
                print(f"❌ Error extracting question PDF {filename}: {e}")

# ==========================================
# FREQUENCY / GROUPING
# ==========================================
def group_questions(extracted_folder):
    """Groups similar questions from extracted text files."""
    init_models()
    
    import nltk
    try:
        nltk.data.find('tokenizers/punkt')
    except LookupError:
        nltk.download('punkt')
        nltk.download('punkt_tab')

    all_questions = []
    file_map = {}

    if not os.path.exists(extracted_folder):
        return ""

    for filename in os.listdir(extracted_folder):
        if filename.endswith(".txt"):
            file_path = os.path.join(extracted_folder, filename)
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
                sentences = nltk.sent_tokenize(text)
                questions = [s.strip() for s in sentences if s.endswith("?")]
                all_questions.extend(questions)
                for q in questions:
                    file_map[q] = filename

    if not all_questions:
        return "No questions found."

    # Encode and group
    embeddings = _sbert_model.encode(all_questions, convert_to_tensor=True)
    similarity_matrix = util.pytorch_cos_sim(embeddings, embeddings)

    threshold = 0.75
    visited = set()
    groups = []

    for i, question in enumerate(all_questions):
        if i in visited:
            continue
        similar_set = {question}
        visited.add(i)

        for j in range(i + 1, len(all_questions)):
            if j not in visited and similarity_matrix[i][j] > threshold:
                similar_set.add(all_questions[j])
                visited.add(j)
        groups.append(similar_set)

    # Format output
    output = []
    for idx, group in enumerate(groups, start=1):
        output.append(f"Group {idx}:")
        for question in group:
            output.append(f" - {question} (From: {file_map.get(question, 'Unknown')})")
        output.append("\n" + "="*50 + "\n")
    
    return "\n".join(output)

# ==========================================
# ANSWER GENERATION
# ==========================================
def safe_generate(prompt_template, content):
    """Retries generation with decreasing context verification."""
    init_models()
    # If content is empty/very short, handle gracefully?
    
    # Simple retry logic
    MODEL_NAME = "models/gemini-2.5-flash"
    MAX_WORDS = 7000
    MIN_WORDS = 300
    
    word_limit = MAX_WORDS
    while word_limit >= MIN_WORDS:
        truncated = ' '.join(content.split()[:word_limit])
        prompt = prompt_template.format(truncated)
        
        for attempt in range(3):
            try:
                model = genai.GenerativeModel(MODEL_NAME)
                response = model.generate_content(prompt)
                if response and hasattr(response, "text"):
                    return response.text.strip()
            except Exception as e:
                print(f"⚠️ Attempt {attempt+1} failed: {e}")
                time.sleep(2)
        
        word_limit //= 2
        print(f"⚠️ Reducing word limit to {word_limit}...")
        
    return "❌ Error: AI service unavailable or content too large."

def get_manual_embedding(text):
    """Fallback embedding using standard transformers if SBERT model object wrapper not used."""
    # Note: We can just use _sbert_model.encode(text) if available.
    if _sbert_model:
        return _sbert_model.encode([text])[0].reshape(1, -1)
    return np.zeros((1, 384)) # Fallback dummy

def generate_answers(grouped_questions_text, notes_folder):
    """Main logic to generate answers from notes."""
    init_models()
    
    # 1. Extract notes
    notes_texts = extract_text_from_pdfs(notes_folder)
    
    # 2. Extract meaningful questions from the raw grouped text
    extract_template = '''
    Extract all relevant questions from the following text. The questions should be meaningful and related to the subject.
    Ignore metadata like 'Group 1' or filenames.
    
    TEXT:
    {}
    '''
    extracted_questions = safe_generate(extract_template, grouped_questions_text)
    
    # 3. Build FAISS index for notes
    # Filter empty notes
    valid_notes = [n for n in notes_texts if n.strip()]
    if not valid_notes:
        return extracted_questions, "No notes available to answer questions."

    note_embeddings = _sbert_model.encode(valid_notes)
    index = faiss.IndexFlatL2(note_embeddings.shape[1])
    index.add(note_embeddings)

    # 4. Generate answers
    answers_output = ""
    
    for i, question in enumerate(extracted_questions.split("\n")):
        question = question.strip()
        if not question: continue
        
        # Retrieve context
        q_emb = _sbert_model.encode([question])
        distances, indices = index.search(q_emb, k=2)
        
        relevant_notes = [valid_notes[idx] for idx in indices[0] if idx < len(valid_notes)]
        context_text = "\n\n".join(relevant_notes)
        
        if not relevant_notes or len(context_text.split()) < 50:
             # Fallback
            answer_template = '''
            Answer the following question according to General Knowledge or Standard Syllabus (KTU 2019 Scheme if applicable).
            
            QUESTION:
            {}
            '''
            answer = safe_generate(answer_template, question)
        else:
            answer_template = '''
            Answer the question below based on these retrieved notes.
            
            NOTES:
            {}
            
            QUESTION:
            ''' + question
            answer = safe_generate("{}", context_text)
            
        answers_output += f"## Question {i+1}: {question}\n\n{answer}\n\n---\n\n"
        
    return extracted_questions, answers_output

# ==========================================
# PDF GENERATION
# ==========================================
def generate_pdf_from_text(text_content, output_pdf_path):
    """Generates a PDF from markdown-like text using ReportLab."""
    doc = SimpleDocTemplate(output_pdf_path, pagesize=letter)
    story = []
    styles = getSampleStyleSheet()
    
    # Create custom styles
    styles.add(ParagraphStyle(name='Justify', parent=styles['Normal'], alignment=TA_JUSTIFY))
    
    # Convert Markdown to HTML-like fragments for ReportLab? 
    # ReportLab supports basic XML tags like <b>, <i>.
    # We can use the 'markdown' lib to output HTML, but ReportLab's HTML support is limited (Paragraph).
    # Better approach: simplistic parsing or use a library, but let's stick to basic XML tags manually or simple cleanup.
    
    # Actually, let's use the 'markdown' library to render to HTML, then we parse that?
    # No, that's complex. Let's do simple cleaning.
    # Markdown symbols: **bold**, *italic*, # Header
    
    lines = text_content.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            story.append(Spacer(1, 12))
            continue
            
        # Headers
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

        # XML escape special chars first (ReportLab requires it)
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        # Regex for Bold and Italic
        import re
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text) # Bold
        text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)     # Italic

        
        p = Paragraph(text, style)
        story.append(p)

    doc.build(story)

# ==========================================
# ORCHESTRATOR
# ==========================================
def process_data(notes_folder, questions_folder, extracted_folder):
    """Orchestrates the entire flow."""
    init_models()
    
    # 1. Extract text from Questions PDFs
    print("🚀 Starting processing...")
    extract_text_from_questions(questions_folder, extracted_folder)
    
    # 2. Group Questions
    grouped_text = group_questions(extracted_folder)
    # Save grouped text (legacy requirement?)
    with open(os.path.join(BASE_DIR, "grouped_questions.txt"), "w", encoding="utf-8") as f:
        f.write(grouped_text)
        
    # 3. Generate Answers
    questions_summary, answers = generate_answers(grouped_text, notes_folder)
    
    # Save answers
    out_txt = os.path.join(BASE_DIR, "generated_answers.txt")
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write(f"Questions:\n{questions_summary}\n\nAnswers:\n{answers}")
        
    return answers
