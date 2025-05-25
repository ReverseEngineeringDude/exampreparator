import os
import PyPDF2

# ✅ Dynamically get base directory (i.e., backend/)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# ✅ Set input/output directories relative to BASE_DIR
input_dir = os.path.join(BASE_DIR, 'uploads', 'questions')
output_dir = os.path.join(BASE_DIR, 'extracted_text')

# ✅ Ensure output directory exists
os.makedirs(output_dir, exist_ok=True)

# ✅ Function to extract text from PDF
def extract_text_from_pdf(pdf_path):
    text = ""
    with open(pdf_path, "rb") as file:
        reader = PyPDF2.PdfReader(file)
        for page in reader.pages:
            text += page.extract_text() or ""  # Handle pages with no text
    return text

# ✅ Process all PDF files in the input directory
for filename in os.listdir(input_dir):
    if filename.lower().endswith(".pdf"):
        pdf_path = os.path.join(input_dir, filename)
        extracted_text = extract_text_from_pdf(pdf_path)

        if extracted_text.strip():  # Only save if non-empty
            output_path = os.path.join(output_dir, f"{os.path.splitext(filename)[0]}.txt")
            with open(output_path, "w", encoding="utf-8") as text_file:
                text_file.write(extracted_text)
            print(f"✅ Extracted text saved to: {output_path}")
        else:
            print(f"⚠️ Warning: No text extracted from {filename}.")

print("✅ PDF text extraction complete.")
