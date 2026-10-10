// Tester Dashboard JavaScript

let predictionTimeout;

document.addEventListener('DOMContentLoaded', function() {
    initializeFormListeners();
});

// Setup form listeners for live predictions
function initializeFormListeners() {
    const titleInput = document.querySelector('input[name="title"]');
    const descInput = document.querySelector('textarea[name="description"]');
    const componentSelect = document.querySelector('select[name="component"]');
    
    if (titleInput) {
        titleInput.addEventListener('input', handleInputChange);
    }
    if (descInput) {
        descInput.addEventListener('input', handleInputChange);
    }
    if (componentSelect) {
        componentSelect.addEventListener('change', getAIPrediction);
    }
}

// Handle input change with debounce
function handleInputChange() {
    clearTimeout(predictionTimeout);
    predictionTimeout = setTimeout(getAIPrediction, 500);
    
    const statusEl = document.getElementById('aiStatus');
    if (statusEl) {
        statusEl.textContent = 'Typing...';
        statusEl.style.background = '#f8961e';
    }
}

// Get AI prediction
function getAIPrediction() {
    const title = document.querySelector('input[name="title"]')?.value;
    const description = document.querySelector('textarea[name="description"]')?.value;
    const component = document.querySelector('select[name="component"]')?.value;
    
    if (!title || !description || !component) {
        updateStatus('Ready', '#e9ecef');
        return;
    }
    
    fetch('/predict-api', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            title: title,
            description: description,
            component: component
        })
    })
    .then(response => response.json())
    .then(data => {
        updatePredictions(data);
        updateStatus('Ready', '#e9ecef');
    })
    .catch(error => {
        console.error('Prediction error:', error);
        updateStatus('Error', '#f72585');
    });
}

// Update prediction display
function updatePredictions(data) {
    const severityEl = document.getElementById('predictedSeverity');
    const priorityEl = document.getElementById('predictedPriority');
    
    if (severityEl) {
        severityEl.textContent = data.severity;
        severityEl.className = 'value ' + getSeverityClass(data.severity);
    }
    
    if (priorityEl) {
        priorityEl.textContent = data.priority;
        priorityEl.className = 'value ' + getPriorityClass(data.priority);
    }
}

// Get CSS class for severity
function getSeverityClass(severity) {
    const classes = {
        'Critical': 'text-danger',
        'High': 'text-warning',
        'Medium': 'text-info',
        'Low': 'text-success'
    };
    return classes[severity] || '';
}

// Get CSS class for priority
function getPriorityClass(priority) {
    const classes = {
        'P0': 'text-danger',
        'P1': 'text-warning',
        'P2': 'text-primary',
        'P3': 'text-info',
        'P4': 'text-secondary'
    };
    return classes[priority] || '';
}

// Update status badge
function updateStatus(text, color) {
    const statusEl = document.getElementById('aiStatus');
    if (statusEl) {
        statusEl.textContent = text;
        statusEl.style.background = color;
    }
}

// Verify bug function
function verifyBug(bugId, result) {
    if (!confirm(`Are you sure you want to mark this bug as ${result === 'pass' ? 'VERIFIED' : 'FAILED'}?`)) {
        return;
    }
    
    showSpinner();
    
    fetch('/verify-bug', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            bug_id: bugId,
            result: result
        })
    })
    .then(response => response.json())
    .then(data => {
        hideSpinner();
        if (data.success) {
            showToast(`Bug ${result === 'pass' ? 'verified' : 'reopened'} successfully!`, 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast('Error updating bug', 'danger');
        }
    })
    .catch(error => {
        hideSpinner();
        handleAjaxError(error);
    });
}

// Global functions from base.html
function showSpinner() {
    const spinner = document.getElementById('globalSpinner');
    if (spinner) spinner.style.display = 'flex';
}

function hideSpinner() {
    const spinner = document.getElementById('globalSpinner');
    if (spinner) spinner.style.display = 'none';
}

function showToast(message, type) {
    // This function should be defined in base.html
    if (window.showToast) {
        window.showToast(message, type);
    } else {
        alert(message);
    }
}

function handleAjaxError(error) {
    console.error('AJAX Error:', error);
    showToast('An error occurred. Please try again.', 'danger');
}
