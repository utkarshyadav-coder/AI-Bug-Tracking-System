// Developer Dashboard JavaScript

let performanceChart = null;

document.addEventListener('DOMContentLoaded', function() {
    initializePerformanceChart();
    initializeEventListeners();
});

// Initialize performance chart
function initializePerformanceChart() {
    const ctx = document.getElementById('performanceChart').getContext('2d');
    
    const resolutionData = [2.5, 3.0, 2.8, 2.2, 1.9, 2.1, 1.8];
    const reopenData = [0.15, 0.12, 0.10, 0.08, 0.07, 0.06, 0.05];
    const labels = ['Week 6', 'Week 5', 'Week 4', 'Week 3', 'Week 2', 'Last Week', 'This Week'];
    
    performanceChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Resolution Time (days)',
                    data: resolutionData,
                    borderColor: '#4361ee',
                    backgroundColor: 'rgba(67, 97, 238, 0.1)',
                    tension: 0.4,
                    yAxisID: 'y'
                },
                {
                    label: 'Reopen Rate',
                    data: reopenData,
                    borderColor: '#f72585',
                    backgroundColor: 'rgba(247, 37, 133, 0.1)',
                    tension: 0.4,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        boxWidth: 12,
                        font: { size: 11 }
                    }
                }
            },
            scales: {
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    title: {
                        display: true,
                        text: 'Days'
                    },
                    min: 0
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    title: {
                        display: true,
                        text: 'Rate'
                    },
                    min: 0,
                    max: 0.2,
                    grid: {
                        drawOnChartArea: false,
                    },
                    ticks: {
                        callback: function(value) {
                            return (value * 100) + '%';
                        }
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

// UPDATE BUG STATUS - WITH PAGE RELOAD (GUARANTEED WORKING)
function updateBugStatus(bugId, action) {
    let actionText = '';
    let newStatus = '';
    
    switch(action) {
        case 'start':
            actionText = 'start working on';
            newStatus = 'In Progress';
            break;
        case 'fix':
            actionText = 'mark as fixed';
            newStatus = 'Fixed';
            break;
        case 'help':
            actionText = 'request help for';
            newStatus = 'Blocked';
            break;
    }
    
    if (!confirm(`Are you sure you want to ${actionText} bug ${bugId}?`)) {
        return;
    }
    
    showSpinner();
    
    fetch('/update-bug-status', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            bug_id: bugId,
            status: newStatus,
            action: action
        })
    })
    .then(response => response.json())
    .then(data => {
        hideSpinner();
        if (data.success) {
            showToast(`Bug ${bugId} updated successfully`, 'success');
            // RELOAD THE PAGE TO SHOW UPDATED LIST
            setTimeout(() => {
                location.reload();
            }, 1000);
        } else {
            showToast('Error updating bug', 'danger');
        }
    })
    .catch(error => {
        hideSpinner();
        console.error('Error:', error);
        showToast('An error occurred', 'danger');
    });
}

// Claim a suggested bug
function claimBug(bugId) {
    if (!confirm(`Do you want to claim bug ${bugId}?`)) {
        return;
    }
    
    showSpinner();
    
    fetch('/claim-bug', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            bug_id: bugId
        })
    })
    .then(response => response.json())
    .then(data => {
        hideSpinner();
        if (data.success) {
            showToast(`Bug ${bugId} assigned to you`, 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast('Error claiming bug', 'danger');
        }
    })
    .catch(error => {
        hideSpinner();
        handleAjaxError(error);
    });
}

// Add activity to recent activity list
function addActivity(action, bugId) {
    const activityList = document.querySelector('.activity-list');
    if (!activityList) return;
    
    const activityItem = document.createElement('div');
    activityItem.className = 'activity-item';
    
    let text = '';
    let iconClass = '';
    
    switch(action) {
        case 'start':
            text = `Started working on bug ${bugId}`;
            iconClass = 'start';
            break;
        case 'fix':
            text = `Marked bug ${bugId} as fixed`;
            iconClass = 'fix';
            break;
        case 'help':
            text = `Requested help for bug ${bugId}`;
            iconClass = 'help';
            break;
    }
    
    const now = new Date();
    
    activityItem.innerHTML = `
        <i class="fas fa-circle ${iconClass}"></i>
        <div class="activity-content">
            <div class="activity-text">${text}</div>
            <div class="activity-time">Just now</div>
        </div>
    `;
    
    const emptyState = activityList.querySelector('.empty-state');
    if (emptyState) {
        emptyState.remove();
    }
    
    activityList.insertBefore(activityItem, activityList.firstChild);
    
    const activities = activityList.children;
    if (activities.length > 10) {
        activities[activities.length - 1].remove();
    }
}

// Refresh performance chart with new data
function refreshPerformanceChart(newData) {
    if (performanceChart) {
        performanceChart.data.datasets[0].data = newData.resolution;
        performanceChart.data.datasets[1].data = newData.reopen;
        performanceChart.update();
    }
}

// Global functions
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
        alert(message);
    }
}

function handleAjaxError(error) {
    console.error('AJAX Error:', error);
    showToast('An error occurred. Please try again.', 'danger');
}
