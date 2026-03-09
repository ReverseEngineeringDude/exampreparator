📚 ExamPreparator
ExamPreparator is an intelligent assistant designed to streamline exam preparation for students following the KTU 2019 scheme. Upload your class notes and previous question papers, and get organized, relevant, and smartly generated answers — all in one place.

🚀 Features
📄 PDF Upload: Upload notes and question papers for processing.

📤 Text Extraction: Automatically extracts relevant text from uploaded documents.

❓ Question Extraction: Identifies and groups frequently asked or important questions using SBERT embeddings.

⚡ Batched AI Output: Aggregates questions into a minimal number of payloads to completely safeguard against API Rate Limits.

📏 Dynamic Answer Constraints: Strictly formats generated answers based on mark values (1-mark = 1 word, 3-marks = short paragraph, 7-marks = detailed essay).

🧠 RAG-Based Answering: Combines retrieval-augmented generation (via FAISS) with Gemini 1.5 Pro to ground answers in your uploaded notes.

📘 KTU 2019 Scheme Support: Generates fallback answers based on curriculum guidelines when material is insufficient.

📊 Progress Indicators: Shows real-time processing status and quota-warnings directly in the web UI.

📁 Organized Output: Saves results to beautifully formatted JSON text files for later use.

⚙️ Installation
Prerequisites
Python 3.8+

pip

Flask

PyPDF2

FAISS

sentence-transformers

Gemini API (optional) or LLaMA 3 local model

📌 Tech Stack
Backend: Python, Flask, PyPDF2, FAISS, sentence-transformers, Gemini API / LLaMA 3

Frontend: HTML, CSS, JavaScript

AI/ML Models: SBERT for embeddings, Gemini or LLaMA 3 for generation

Curriculum: KTU 2019 scheme

📄 License
This project is licensed under the MIT License.

🙋‍♂️ Maintainer
Neeraj Varghese
AI & Web Developer
