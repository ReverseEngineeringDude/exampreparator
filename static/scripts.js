document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('uploadForm');
    const progressContainer = document.getElementById('progress');
    const answers = document.getElementById('answers');
    const downloadBtn = document.getElementById('downloadBtn');
    const submitBtn = form.querySelector('button[type="submit"]');

    // Handle File Input Changes for Custom UI
    const handleFileInput = (inputId, listId) => {
        const input = document.getElementById(inputId);
        const list = document.getElementById(listId);

        input.addEventListener('change', () => {
            if (input.files.length > 0) {
                const names = Array.from(input.files).map(f => f.name).join(', ');
                list.textContent = names;
                list.style.color = '#fff';
            } else {
                list.textContent = 'No files selected';
                list.style.color = '#94a3b8';
            }
        });
    };

    handleFileInput('notes-input', 'notes-file-list');
    handleFileInput('questions-input', 'questions-file-list');

    // Form Submission
    form.addEventListener('submit', async function (e) {
        e.preventDefault();

        const formData = new FormData(form);

        // UI Updates for Loading
        progressContainer.style.display = 'block';
        submitBtn.disabled = true;
        submitBtn.querySelector('span').textContent = 'Processing...';
        answers.innerHTML = '<span class="placeholder-text">Analyzing your documents... This may take a moment.</span>';
        downloadBtn.classList.add('hidden');

        try {
            const response = await fetch('/upload', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (response.ok) {
                // Fetch Answers
                const answerRes = await fetch('/get_answers');
                const answerText = await answerRes.text();

                answers.textContent = answerText;

                // Show Download Button
                downloadBtn.classList.remove('hidden');
            } else {
                answers.innerHTML = `<span style="color: #ef4444">❌ Upload failed: ${result.error || 'Unknown error'}</span>`;
            }
        } catch (err) {
            answers.innerHTML = `<span style="color: #ef4444">❌ Error: ${err.message}</span>`;
        } finally {
            // Reset UI
            progressContainer.style.display = 'none';
            submitBtn.disabled = false;
            submitBtn.querySelector('span').textContent = 'Analyze Documents';
        }
    });

    // Study Mode Upload Handler
    handleFileInput('study-questions-input', 'study-questions-file-list');

    const studyForm = document.getElementById('studyUploadForm');
    const studyProgress = document.getElementById('study-progress');
    const studyResults = document.getElementById('study-results');
    const studyBtn = studyForm.querySelector('button');

    studyForm.addEventListener('submit', async function (e) {
        e.preventDefault();

        const formData = new FormData(studyForm);

        studyProgress.style.display = 'block';
        studyResults.style.display = 'none';
        studyBtn.disabled = true;
        studyBtn.querySelector('span').textContent = 'Generating Study Material...';

        try {
            const response = await fetch('/study_upload', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (response.ok) {
                await loadStudyMaterial();
                studyResults.style.display = 'grid';
            } else {
                alert(`Error: ${result.error || 'Unknown error'}`);
            }
        } catch (err) {
            alert(`Error: ${err.message}`);
        } finally {
            studyProgress.style.display = 'none';
            studyBtn.disabled = false;
            studyBtn.querySelector('span').textContent = 'Generate Study Material';
        }
    });

});

// Study Mode Toggle
const modeToggle = document.getElementById('mode-toggle');
const analysisView = document.getElementById('analysis-view');
const studyView = document.getElementById('study-view');

modeToggle.addEventListener('change', () => {
    if (modeToggle.checked) {
        analysisView.style.display = 'none';
        studyView.style.display = 'block';
        loadStudyMaterial();
    } else {
        analysisView.style.display = 'block';
        studyView.style.display = 'none';
    }
});

async function loadStudyMaterial() {
    const notesList = document.getElementById('study-notes-list');
    const videosList = document.getElementById('study-videos-list');

    try {
        const response = await fetch('/get_study_material');
        const data = await response.json();

        if (!data || data.length === 0) {
            notesList.innerHTML = '<div class="loading-placeholder">No study material found. Please run the analysis first.</div>';
            return;
        }

        notesList.innerHTML = '';
        videosList.innerHTML = '';

        data.forEach((item, index) => {
            // Notes Card
            const card = document.createElement('div');
            card.className = 'topic-card';
            card.innerHTML = `
                    <div class="topic-title">${item.topic}</div>
                    <div class="topic-summary">${item.summary}</div>
                    <ul class="topic-points">
                        ${item.points.map(p => `<li>${p}</li>`).join('')}
                    </ul>
                `;
            notesList.appendChild(card);

            // Video Search Link
            const videoCard = document.createElement('div');
            videoCard.className = 'topic-card';
            videoCard.innerHTML = `
                    <div class="topic-title">${item.topic}</div>
                    <a href="https://www.youtube.com/results?search_query=${encodeURIComponent(item.topic + ' tutorial')}" 
                       target="_blank" class="video-btn">
                       <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 11.75a29 29 0 0 0 .46 5.33A2.78 2.78 0 0 0 3.4 19c1.72.46 8.6.46 8.6.46s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2 29 29 0 0 0 .46-5.25 29 29 0 0 0-.46-5.33z"></path><polygon points="9.75 15.02 15.5 11.75 9.75 8.48 9.75 15.02"></polygon></svg>
                       Watch on YouTube
                    </a>
                `;
            videosList.appendChild(videoCard);
        });

    } catch (err) {
        console.error(err);
        notesList.innerHTML = '<div class="loading-placeholder">Error loading data.</div>';
    }
}
