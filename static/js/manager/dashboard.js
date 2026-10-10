// Manager Dashboard JavaScript

let trendsChart;

document.addEventListener('DOMContentLoaded', function() {
    initializeCharts();
    initializeEventListeners();
});

// Initialize charts
function initializeCharts() {
    const ctx = document.getElementById('trendsChart').getContext('2d');
    
    // Sample data - replace with actual data from backend
    const weeks = ['Week 1', 'Week 2', 'Week 3', 'Week 4'];
    
    trendsChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: weeks,
            datasets: [
                {
                    label: 'Critical',
                    data: [5, 7, 4, 6],
                    borderColor: '#f72585',
                    backgroundColor: 'rgba(247, 37, 133, 0.1)',
                    tension: 0.4,
                    fill: true
                },
                {
                    label: 'High',
                    data: [8, 10, 7, 9],
                    borderColor: '#f8961e',
                    backgroundColor: 'rgba(248, 150, 30, 0.1)',
                    tension: 0.4,
                    fill: true
                },
                {
                    label: 'Medium',
                    data: [12, 15, 11, 14],
                    borderColor: '#4cc9f0',
                    backgroundColor: 'rgba(76, 201, 240, 0.1)',
                    tension: 0.4,
                    fill: true
                },
                {
                    label: 'Low',
                    data: [10, 8, 12, 9],
                    borderColor: '#43aa8b',
                    backgroundColor: 'rgba(67, 170, 139, 0.1)',
                    tension: 0.4,
                    fill: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { boxWidth: 12 }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Number of Bugs'
                    }
                }
            }
        }
    });
}

// Initialize event listeners
function initializeEventListeners() {
    // Add any global event listeners here
}

// Filter trends chart
function filterTrends(period) {
    // Update active button
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    event.target.classList.add('active');
    
    // Update chart data based on period
    if (period === 'week') {
        trendsChart.data.labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
        trendsChart.data.datasets.forEach(dataset => {
            dataset.data = [3, 5, 4, 6, 7, 2, 1];
        });
    } else {
        trendsChart.data.labels = ['Week 1', 'Week 2', 'Week 3', 'Week 4'];
        trendsChart.data.datasets.forEach(dataset => {
            dataset.data = [5, 7, 4, 6];
        });
    }
    
    trendsChart.update();
}

// Reassign bug function
function reassignBug(bugId) {
    // Show developer list modal
    showToast(`Reassign feature coming soon for bug ${bugId}`, 'info');
}

// View bug details
function viewDetails(bugId) {
    window.location.href = `/bug-details/${bugId}`;
}

// Generate report
function generateReport() {
    showSpinner();
    
    // Simulate report generation
    setTimeout(() => {
        hideSpinner();
        showToast('Report generated successfully', 'success');
    }, 1500);
}

// Reprioritize
function reprioritize() {
    showToast('Reprioritization tool coming soon', 'info');
}

// Start new sprint
function startSprint() {
    if (confirm('Start a new sprint?')) {
        showSpinner();
        setTimeout(() => {
            hideSpinner();
            showToast('New sprint started!', 'success');
        }, 1000);
    }
}

// Schedule meeting
function scheduleMeeting() {
    showToast('Meeting scheduler coming soon', 'info');
}

// Global helper functions
function showSpinner() {
    const spinner = document.getElementById('globalSpinner');
    if (spinner) spinner.style.display = 'flex';
}

function hideSpinner() {
    const spinner = document.getElementById('globalSpinner');
    if (spinner) spinner.style.display = 'none';
}

function showToast(message, type) {
    // Use the toast function from base.html
    if (window.showToast) {
        window.showToast(message, type);
    } else {
        alert(message);
    }
}
