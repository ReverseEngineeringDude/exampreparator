document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('uploadForm');
    const progress = document.getElementById('progress');
    const answers = document.getElementById('answers');

    form.addEventListener('submit', async function (e) {
        e.preventDefault();

        const formData = new FormData(form);

        // Show progress bar
        progress.style.display = 'block';
        answers.textContent = '⏳ Processing... Please wait.';

        try {
            const response = await fetch('/upload', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (response.ok) {
                // Get and show the answers from the server
                const answerRes = await fetch('/get_answers');
                const answerText = await answerRes.text();
                answers.textContent = answerText;
            } else {
                answers.textContent = `❌ Upload failed: ${result.error || 'Unknown error'}`;
            }
        } catch (err) {
            answers.textContent = `❌ Error: ${err.message}`;
        } finally {
            // Hide progress bar
            progress.style.display = 'none';
        }
    });
});

// Trigger file download of the generated answers as a PDF
function downloadPDF() {
    window.location.href = '/download_pdf';
}
