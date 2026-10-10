// Sprint Risk Page JavaScript

document.addEventListener('DOMContentLoaded', function() {
    initializePage();
});

function initializePage() {
    // Add any interactive features here
    console.log('Sprint Risk page loaded');
    
    // Auto-refresh risk data every 5 minutes
    setInterval(refreshRiskData, 300000);
}

function refreshRiskData() {
    showSpinner();
    
    fetch('/api/sprint-risk/current')
        .then(response => response.json())
        .then(data => {
            updateRiskDisplay(data);
            hideSpinner();
        })
        .catch(error => {
            console.error('Error refreshing risk data:', error);
            hideSpinner();
            showToast('Failed to refresh risk data', 'error');
        });
}

function updateRiskDisplay(data) {
    // Update risk level
    const riskBadge = document.querySelector('.risk-badge');
    if (riskBadge) {
        riskBadge.textContent = data.risk_level + ' RISK';
        riskBadge.className = 'risk-badge ' + data.risk_level.toLowerCase();
    }
    
    // Update risk score
    const riskScore = document.querySelector('.risk-score');
    if (riskScore) {
        riskScore.textContent = data.risk_score + '% Risk Score';
    }
    
    // Update recommendation
    const recommendation = document.querySelector('.recommendation');
    if (recommendation) {
        recommendation.innerHTML = `<i class="fas fa-lightbulb"></i> ${data.recommendation}`;
        recommendation.className = 'recommendation ' + data.risk_level.toLowerCase();
    }
    
    // Update metrics
    document.querySelectorAll('.metric-value').forEach((el, index) => {
        const metrics = [
            data.metrics.total_bugs,
            data.metrics.critical,
            data.metrics.p0,
            data.metrics.days_left
        ];
        if (index < metrics.length) {
            el.textContent = metrics[index];
        }
    });
    
    // Update progress
    const progressFill = document.querySelector('.progress-fill');
    if (progressFill) {
        progressFill.style.width = data.metrics.progress + '%';
        progressFill.textContent = data.metrics.progress + '%';
    }
    
    showToast('Risk data refreshed', 'success');
}

// Helper functions
function showSpinner() {
    const spinner = document.getElementById('globalSpinner');
    if (spinner) spinner.style.display = 'flex';
}

function hideSpinner() {
    const spinner = document.getElementById('globalSpinner');
    if (spinner) spinner.style.display = 'none';
}

function showToast(message, type) {
    if (window.showToast) {
        window.showToast(message, type);
    } else {
        console.log(message);
    }
}