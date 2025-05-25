import os
import nltk
import torch
from sentence_transformers import SentenceTransformer, util

# ✅ Download required NLTK model
nltk.download('punkt')

# ✅ Dynamically get base directory (i.e., backend/)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# ✅ Set directories relative to BASE_DIR
input_dir = os.path.join(BASE_DIR, 'extracted_text')
output_file = os.path.join(BASE_DIR, 'grouped_questions.txt')

# ✅ Load pre-trained SBERT model
model = SentenceTransformer("all-MiniLM-L6-v2")

# ✅ Function to extract questions from text
def extract_questions(text):
    sentences = nltk.sent_tokenize(text)
    return [s.strip() for s in sentences if s.endswith("?")]

# ✅ Read all text files and collect questions
all_questions = []
file_map = {}

for filename in os.listdir(input_dir):
    if filename.endswith(".txt"):
        file_path = os.path.join(input_dir, filename)
        with open(file_path, "r", encoding="utf-8") as file:
            text = file.read()
            questions = extract_questions(text)
            all_questions.extend(questions)
            file_map.update({q: filename for q in questions})

# ✅ Encode questions using SBERT
question_embeddings = model.encode(all_questions, convert_to_tensor=True)

# ✅ Compute cosine similarity
similarity_matrix = util.pytorch_cos_sim(question_embeddings, question_embeddings)

# ✅ Group similar questions
threshold = 0.75  # Adjust if needed
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

# ✅ Save grouped questions
with open(output_file, "w", encoding="utf-8") as out_file:
    for idx, group in enumerate(groups, start=1):
        out_file.write(f"Group {idx}:\n")
        for question in group:
            out_file.write(f" - {question} (From: {file_map[question]})\n")
        out_file.write("\n" + "="*50 + "\n\n")

print(f"✅ Grouped questions saved to: {output_file}")
