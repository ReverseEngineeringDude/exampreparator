from flask import Flask, request, jsonify, render_template, send_file
import os
import shutil
import subprocess
from reportlab.pdfgen import canvas

app = Flask(
    __name__,
    static_folder='../static',
    template_folder='../templates'
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))  # backend folder
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
NOTES_FOLDER = os.path.join(UPLOAD_FOLDER, 'notes')
QUESTIONS_FOLDER = os.path.join(UPLOAD_FOLDER, 'questions')
EXTRACTED_FOLDER = os.path.join(BASE_DIR, 'extracted_text')
GENERATED_ANSWERS = os.path.join(BASE_DIR, 'generated_answers.txt')
GROUPED_QUESTIONS = os.path.join(BASE_DIR, 'grouped_questions.txt')
GENERATED_PDF = os.path.join(BASE_DIR, 'generated_answers.pdf')

os.makedirs(NOTES_FOLDER, exist_ok=True)
os.makedirs(QUESTIONS_FOLDER, exist_ok=True)
os.makedirs(EXTRACTED_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    try:
        shutil.rmtree(NOTES_FOLDER, ignore_errors=True)
        shutil.rmtree(QUESTIONS_FOLDER, ignore_errors=True)
        os.makedirs(NOTES_FOLDER, exist_ok=True)
        os.makedirs(QUESTIONS_FOLDER, exist_ok=True)

        open(GENERATED_ANSWERS, 'w').close()
        open(GROUPED_QUESTIONS, 'w').close()

        for filename in os.listdir(EXTRACTED_FOLDER):
            file_path = os.path.join(EXTRACTED_FOLDER, filename)
            if filename.endswith('.txt') and os.path.isfile(file_path):
                os.remove(file_path)

        notes_files = request.files.getlist('notes[]')
        questions_files = request.files.getlist('questions[]')

        for file in notes_files:
            file.save(os.path.join(NOTES_FOLDER, file.filename))

        for file in questions_files:
            file.save(os.path.join(QUESTIONS_FOLDER, file.filename))

        subprocess.run(['python', os.path.join(BASE_DIR, 'extract_text.py')], check=True)
        subprocess.run(['python', os.path.join(BASE_DIR, 'frequency.py')], check=True)
        subprocess.run(['python', os.path.join(BASE_DIR, 'answer.py')], check=True)

        return jsonify({'message': 'Files processed successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_answers', methods=['GET'])
def get_answers():
    try:
        with open(GENERATED_ANSWERS, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"❌ Error loading answers: {e}", 500

@app.route('/download_pdf', methods=['GET'])
def download_pdf():
    try:
        with open(GENERATED_ANSWERS, 'r', encoding='utf-8') as f:
            content = f.read()

        c = canvas.Canvas(GENERATED_PDF)
        width, height = c._pagesize
        textobject = c.beginText(40, height - 50)

        for line in content.split('\n'):
            textobject.textLine(line)
            if textobject.getY() <= 40:
                c.drawText(textobject)
                c.showPage()
                textobject = c.beginText(40, height - 50)

        c.drawText(textobject)
        c.save()

        return send_file(GENERATED_PDF, as_attachment=True)
    except Exception as e:
        return f"❌ Error generating PDF: {e}", 500

if __name__ == '__main__':
    app.run(debug=True)
