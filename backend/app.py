from flask import Flask, request, jsonify, render_template, send_file
import os
import shutil
import json
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
GENERATED_ANSWERS = os.path.join(BASE_DIR, 'generated_answers.json')
GENERATED_PDF = os.path.join(BASE_DIR, 'generated_answers.pdf')

# Ensure directories exist
os.makedirs(NOTES_FOLDER, exist_ok=True)
os.makedirs(QUESTIONS_FOLDER, exist_ok=True)
os.makedirs(QUESTIONS_FOLDER, exist_ok=True)
os.makedirs(EXTRACTED_FOLDER, exist_ok=True)

# Study Mode Folders
STUDY_UPLOAD_FOLDER = os.path.join(UPLOAD_FOLDER, 'study')
STUDY_NOTES_FOLDER = os.path.join(STUDY_UPLOAD_FOLDER, 'notes')
STUDY_QUESTIONS_FOLDER = os.path.join(STUDY_UPLOAD_FOLDER, 'questions')

os.makedirs(STUDY_NOTES_FOLDER, exist_ok=True)
os.makedirs(STUDY_QUESTIONS_FOLDER, exist_ok=True)

# Initialize models once at startup
services.init_models()

@app.route('/')
def index():
    return render_template('landingpage.html')

@app.route('/upload_page')
def upload_page():
    return render_template('uplaod.html')

@app.route('/answers_page')
def answers_page():
    return render_template('answers.html')

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

        notes_files = request.files.getlist('notes[]')
        questions_files = request.files.getlist('questions[]')

        for file in notes_files:
            if file.filename:
                file.save(os.path.join(NOTES_FOLDER, file.filename))

        for file in questions_files:
            if file.filename:
                file.save(os.path.join(QUESTIONS_FOLDER, file.filename))

        # Core logic execution via services
        # generate_answers now returns (questions_data, final_output_dict)
        extracted_q, final_json = services.process_data(NOTES_FOLDER, QUESTIONS_FOLDER, EXTRACTED_FOLDER)
        
        with open(GENERATED_ANSWERS, 'w', encoding='utf-8') as f:
            json.dump(final_json, f, indent=4)

        return jsonify({'message': 'Files processed successfully'})
    except Exception as e:
        import traceback
        app.logger.error(f"Error processing files: \n{traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500

@app.route('/get_answers', methods=['GET'])
def get_answers():
    try:
        if os.path.exists(GENERATED_ANSWERS):
            with open(GENERATED_ANSWERS, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return jsonify(data)
        return jsonify({"error": "No answers generated yet."}), 404
    except Exception as e:
        return jsonify({"error": f"Error loading answers: {e}"}), 500

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

@app.route('/get_study_material', methods=['GET'])
def get_study_material():
    try:
        study_file = os.path.join(BASE_DIR, "study_material.json")
        if os.path.exists(study_file):
            return send_file(study_file)
        return jsonify([])
    except Exception as e:
        return f"❌ Error loading study material: {e}", 500

@app.route('/progress', methods=['GET'])
def get_progress():
    progress_file = os.path.join(BASE_DIR, "progress.json")
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return jsonify(data)
        except Exception:
            return jsonify({"percent": 0, "message": "Starting..."})
    return jsonify({"percent": 0, "message": "Initializing..."})

@app.route('/study_upload', methods=['POST'])
def study_upload():
    try:
        # Cleanup
        shutil.rmtree(STUDY_UPLOAD_FOLDER, ignore_errors=True)
        os.makedirs(STUDY_NOTES_FOLDER, exist_ok=True)
        os.makedirs(STUDY_QUESTIONS_FOLDER, exist_ok=True)
        
        notes_files = request.files.getlist('study_notes[]')
        questions_files = request.files.getlist('study_questions[]')
        
        # Save Question Papers
        for file in questions_files:
            if file.filename:
                file.save(os.path.join(STUDY_QUESTIONS_FOLDER, file.filename))
                
        # Save Notes (Optional)
        for file in notes_files:
            if file.filename:
                file.save(os.path.join(STUDY_NOTES_FOLDER, file.filename))
        
        # Generate
        study_data = services.generate_study_from_questions(STUDY_QUESTIONS_FOLDER, STUDY_NOTES_FOLDER)
        
        # Save JSON state
        with open(os.path.join(BASE_DIR, "study_material.json"), "w", encoding="utf-8") as f:
            json.dump(study_data, f)
            
        return jsonify({'message': 'Study material generated successfully'})
    except Exception as e:
        app.logger.error(f"Error in study upload: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
