from flask import Flask, request, jsonify, render_template, send_file
import os
import shutil
import services

app = Flask(
    __name__,
    static_folder='../static',
    template_folder='../templates'
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
NOTES_FOLDER = os.path.join(UPLOAD_FOLDER, 'notes')
QUESTIONS_FOLDER = os.path.join(UPLOAD_FOLDER, 'questions')
EXTRACTED_FOLDER = os.path.join(BASE_DIR, 'extracted_text')
GENERATED_ANSWERS = os.path.join(BASE_DIR, 'generated_answers.txt')
GENERATED_PDF = os.path.join(BASE_DIR, 'generated_answers.pdf')

# Ensure directories exist
os.makedirs(NOTES_FOLDER, exist_ok=True)
os.makedirs(QUESTIONS_FOLDER, exist_ok=True)
os.makedirs(EXTRACTED_FOLDER, exist_ok=True)

# Initialize models once at startup
services.init_models()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    try:
        # Cleanup and prepare folders
        shutil.rmtree(NOTES_FOLDER, ignore_errors=True)
        shutil.rmtree(QUESTIONS_FOLDER, ignore_errors=True)
        shutil.rmtree(EXTRACTED_FOLDER, ignore_errors=True)
        
        os.makedirs(NOTES_FOLDER, exist_ok=True)
        os.makedirs(QUESTIONS_FOLDER, exist_ok=True)
        os.makedirs(EXTRACTED_FOLDER, exist_ok=True)

        open(GENERATED_ANSWERS, 'w').close()

        notes_files = request.files.getlist('notes[]')
        questions_files = request.files.getlist('questions[]')

        for file in notes_files:
            if file.filename:
                file.save(os.path.join(NOTES_FOLDER, file.filename))

        for file in questions_files:
            if file.filename:
                file.save(os.path.join(QUESTIONS_FOLDER, file.filename))

        # Core logic execution via services
        services.process_data(NOTES_FOLDER, QUESTIONS_FOLDER, EXTRACTED_FOLDER)

        return jsonify({'message': 'Files processed successfully'})
    except Exception as e:
        app.logger.error(f"Error processing files: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/get_answers', methods=['GET'])
def get_answers():
    try:
        if os.path.exists(GENERATED_ANSWERS):
            with open(GENERATED_ANSWERS, 'r', encoding='utf-8') as f:
                return f.read()
        return "No answers generated yet.", 404
    except Exception as e:
        return f"❌ Error loading answers: {e}", 500

@app.route('/download_pdf', methods=['GET'])
def download_pdf():
    try:
        if not os.path.exists(GENERATED_ANSWERS):
             return "No answers generated to convert.", 404
             
        with open(GENERATED_ANSWERS, 'r', encoding='utf-8') as f:
            content = f.read()

        services.generate_pdf_from_text(content, GENERATED_PDF)

        return send_file(GENERATED_PDF, as_attachment=True)
    except Exception as e:
        app.logger.error(f"Error generating PDF: {e}")
        return f"❌ Error generating PDF: {e}", 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
