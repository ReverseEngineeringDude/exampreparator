import os
import time
import torch
import faiss
import numpy as np
from PyPDF2 import PdfReader
from transformers import AutoTokenizer, AutoModel
import google.generativeai as genai

# ✅ Configure Gemini API
with open(r"D:\exampreparator\backend\apikey.txt") as f:
    API_KEY = f.read().strip()

genai.configure(api_key=API_KEY)


# ✅ Load Sentence Transformer Model
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModel.from_pretrained(MODEL_NAME)

# ✅ Parameters for Safe Retry
MODEL_NAME_GEMINI = "models/gemini-1.5-pro"
INITIAL_WORDS = 7000
MIN_WORDS = 300
RETRY_LIMIT = 3
DELAY = 10

# ✅ Dynamic base directory
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INPUT_PATH = os.path.join(BASE_DIR, "grouped_questions.txt")
NOTES_FOLDER = os.path.join(BASE_DIR, "uploads", "notes")
OUTPUT_PATH = os.path.join(BASE_DIR, "generated_answers.txt")

# ✅ Retry Function with Decreasing Token Size
def safe_generate(prompt_template, content):
    word_limit = INITIAL_WORDS
    while word_limit >= MIN_WORDS:
        truncated = ' '.join(content.split()[:word_limit])
        prompt = prompt_template.format(truncated)
        for attempt in range(RETRY_LIMIT):
            try:
                model = genai.GenerativeModel(MODEL_NAME_GEMINI)
                response = model.generate_content(prompt)
                if response and hasattr(response, "text"):
                    return response.text.strip()
                return "⚠️ No response generated."
            except Exception as e:
                print(f"⚠️ Attempt {attempt+1}/{RETRY_LIMIT} failed with {word_limit} words: {e}")
                if attempt < RETRY_LIMIT - 1:
                    time.sleep(DELAY)
        word_limit //= 2
        print(f"⚠️ Reducing word limit and retrying with {word_limit} words...\n")
    return "❌ Error: All retries failed."

# ✅ Extract Text from Notes
def extract_text_from_pdfs(folder_path):
    extracted_texts = []
    for file_name in os.listdir(folder_path):
        if file_name.endswith(".pdf"):
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
                    text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
                    extracted_texts.append(text)
            except Exception as e:
                print(f"❌ Error extracting text from {file_name}: {e}")
    return extracted_texts if extracted_texts else ["No text extracted."]

# ✅ Get Sentence Embedding
def get_embedding(text):
    tokens = tokenizer(text, return_tensors="pt", truncation=True, padding=True)
    with torch.no_grad():
        output = model(**tokens)
    return output.last_hidden_state[:, 0, :].cpu().numpy().reshape(1, -1)

# ✅ Build FAISS Index
def build_faiss_index(texts):
    embeddings = np.vstack([get_embedding(text) for text in texts if text.strip()])
    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(embeddings)
    return index, embeddings

# ✅ Retrieve Relevant Notes
def retrieve_relevant_notes(question, notes, index, embeddings, top_k=2):
    question_embedding = get_embedding(question)
    distances, indices = index.search(np.array(question_embedding), top_k)
    return [notes[idx] for idx in indices[0] if idx < len(notes)]

# ✅ Main Processing Function
def process_questions(input_text, notes_texts):
    extract_template = '''
    Extract all relevant questions from the following text. The questions should be meaningful and related to the subject.

    TEXT:
    {}
    '''
    print("🔎 Extracting questions...")
    extracted_questions = safe_generate(extract_template, input_text)
    print(f"✅ Extracted Questions:\n{extracted_questions}\n")

    print("🔎 Building FAISS index for notes...")
    faiss_index, embeddings = build_faiss_index(notes_texts)

    print("🧠 Generating answers...")
    answers = ""
    for i, question in enumerate(extracted_questions.split("\n")):
        question = question.strip()
        if not question:
            continue

        print(f"\n❓ Q{i+1}: {question}")
        relevant_notes = retrieve_relevant_notes(question, notes_texts, faiss_index, embeddings)
        notes_text = "\n\n".join(relevant_notes)

        if not relevant_notes or len(notes_text.split()) < 50:
            print("⚠️ Notes insufficient. Using fallback to KTU 2019 scheme.")
            answer_template = '''
            Answer the following question according to the KTU 2019 Scheme. Ensure the response is well-structured, concise, and relevant.

            QUESTION:
            {}
            '''
            answer = safe_generate(answer_template, question)
        else:
            answer_template = '''
            Answer the question below based on these retrieved notes. Ensure it's clear, structured, and relevant.

            NOTES:
            {}

            QUESTION:
            ''' + question
            answer = safe_generate("{}", notes_text)

        answers += f"🔹 Question {i+1}: {question}\n🔹 Answer:\n{answer}\n\n"

    return extracted_questions, answers

# ✅ Read Input Questions
with open(INPUT_PATH, "r", encoding="utf-8") as f:
    input_text = f.read()

# ✅ Extract Notes
print("📚 Extracting notes from PDFs...")
notes_texts = extract_text_from_pdfs(NOTES_FOLDER)

# ✅ Process and Generate Answers
questions, answers = process_questions(input_text, notes_texts)

# ✅ Save Output
with open(OUTPUT_PATH, "w", encoding="utf-8") as file:
    file.write("🔹 Extracted Questions:\n" + questions + "\n\n")
    file.write("🔹 Generated Answers:\n\n" + answers)

print(f"\n✅ Done. Answers saved to:\n{OUTPUT_PATH}")
