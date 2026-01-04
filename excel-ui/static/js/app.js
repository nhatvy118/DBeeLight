let currentData = null;
let currentFilename = null;

// Upload area click handler
document.getElementById('upload-area').addEventListener('click', () => {
    document.getElementById('file-input').click();
});

// Drag and drop
const uploadArea = document.getElementById('upload-area');
uploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadArea.style.borderColor = '#764ba2';
    uploadArea.style.background = '#f0f2ff';
});

uploadArea.addEventListener('dragleave', () => {
    uploadArea.style.borderColor = '#667eea';
    uploadArea.style.background = '#f8f9ff';
});

uploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadArea.style.borderColor = '#667eea';
    uploadArea.style.background = '#f8f9ff';
    
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        handleFile(files[0]);
    }
});

// File input change
document.getElementById('file-input').addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        handleFile(e.target.files[0]);
    }
});

async function handleFile(file) {
    if (!file.name.match(/\.(xlsx|xls)$/i)) {
        showStatus('error', 'Please upload an Excel file (.xlsx or .xls)');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    showStatus('loading', 'Uploading file...');

    try {
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (result.success) {
            showStatus('success', result.message);
            currentData = result.data;
            currentFilename = result.filename;
            
            // Show preview
            displayDataPreview(result.data);
            document.getElementById('preview-section').style.display = 'block';
            document.getElementById('summary-section').style.display = 'block';
            document.getElementById('chart-section').style.display = 'block';
        } else {
            showStatus('error', result.error || 'Upload failed');
        }
    } catch (error) {
        showStatus('error', 'Error uploading file: ' + error.message);
    }
}

function displayDataPreview(data) {
    if (!data || data.length === 0) {
        document.getElementById('data-preview').innerHTML = '<p>No data to display</p>';
        return;
    }

    const columns = Object.keys(data[0]);
    let html = '<table><thead><tr>';
    columns.forEach(col => {
        html += `<th>${col}</th>`;
    });
    html += '</tr></thead><tbody>';

    // Show first 10 rows
    data.slice(0, 10).forEach(row => {
        html += '<tr>';
        columns.forEach(col => {
            html += `<td>${row[col] || ''}</td>`;
        });
        html += '</tr>';
    });
    html += '</tbody></table>';

    if (data.length > 10) {
        html += `<p style="margin-top: 10px; color: #666;">Showing first 10 of ${data.length} rows</p>`;
    }

    document.getElementById('data-preview').innerHTML = html;
}

// Generate Summary
document.getElementById('generate-summary-btn').addEventListener('click', async () => {
    if (!currentData) {
        alert('Please upload a file first');
        return;
    }

    const btn = document.getElementById('generate-summary-btn');
    btn.disabled = true;
    btn.textContent = 'Generating...';

    try {
        const response = await fetch('/api/summary', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ data: currentData })
        });

        const result = await response.json();

        if (result.success) {
            document.getElementById('summary-content').textContent = result.summary;
        } else {
            alert('Error: ' + result.error);
        }
    } catch (error) {
        alert('Error generating summary: ' + error.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Generate Summary';
    }
});

// Suggest Charts
document.getElementById('suggest-charts-btn').addEventListener('click', async () => {
    if (!currentData) {
        alert('Please upload a file first');
        return;
    }

    const btn = document.getElementById('suggest-charts-btn');
    btn.disabled = true;
    btn.textContent = 'Getting suggestions...';

    try {
        const response = await fetch('/api/suggest-charts', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ data: currentData })
        });

        const result = await response.json();

        if (result.success) {
            document.getElementById('chart-suggestions').innerHTML = 
                '<h3>Suggested Chart Types:</h3><pre>' + result.suggestions + '</pre>';
        } else {
            alert('Error: ' + result.error);
        }
    } catch (error) {
        alert('Error getting suggestions: ' + error.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Get Suggestions';
    }
});

// Generate Chart
document.getElementById('generate-chart-btn').addEventListener('click', async () => {
    if (!currentData) {
        alert('Please upload a file first');
        return;
    }

    const chartType = document.getElementById('chart-type').value;
    const chartTitle = document.getElementById('chart-title').value;

    const btn = document.getElementById('generate-chart-btn');
    btn.disabled = true;
    btn.textContent = 'Generating chart...';

    try {
        const response = await fetch('/api/generate-chart', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                chart_type: chartType,
                data: currentData,
                title: chartTitle || `${chartType} Chart`
            })
        });

        const result = await response.json();

        if (result.success) {
            document.getElementById('chart-result').innerHTML = 
                `<img src="${result.chart_url}" alt="Generated Chart">`;
        } else {
            alert('Error: ' + result.error);
        }
    } catch (error) {
        alert('Error generating chart: ' + error.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Generate Chart';
    }
});

function showStatus(type, message) {
    const statusEl = document.getElementById('upload-status');
    statusEl.className = `status-message ${type}`;
    statusEl.textContent = message;
}

