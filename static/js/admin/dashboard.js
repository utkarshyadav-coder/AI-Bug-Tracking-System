// Admin Dashboard JavaScript

document.addEventListener('DOMContentLoaded', function() {
    initializeEventListeners();
    // startSystemMonitoring(); // Commented out - remove if you have this route
});

// Initialize event listeners
function initializeEventListeners() {
    // Close modal when clicking outside
    window.onclick = function(event) {
        if (event.target.classList.contains('modal')) {
            event.target.style.display = 'none';
        }
    };
    
    // Add user form submission
    const addUserForm = document.getElementById('addUserForm');
    if (addUserForm) {
        addUserForm.addEventListener('submit', function(e) {
            e.preventDefault();
            addUser();
        });
    }
}

// User Management Functions
function showAddUserModal() {
    const modal = document.getElementById('addUserModal');
    if (modal) {
        modal.style.display = 'flex';
        // Clear form fields
        document.getElementById('username').value = '';
        document.getElementById('fullname').value = '';
        document.getElementById('email').value = '';
        document.getElementById('role').value = 'tester';
        document.getElementById('password').value = '';
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.style.display = 'none';
    }
}

// Add user function
function addUser() {
    const userData = {
        username: document.getElementById('username').value.trim(),
        full_name: document.getElementById('fullname').value.trim(),
        email: document.getElementById('email').value.trim(),
        role: document.getElementById('role').value,
        password: document.getElementById('password').value
    };
    
    // Validation
    if (!userData.username || !userData.full_name || !userData.email || !userData.password) {
        showToast('Please fill all fields', 'error');
        return;
    }
    
    console.log('Sending user data:', userData);
    showSpinner();
    
    fetch('/admin/add-user', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(userData)
    })
    .then(response => response.json())
    .then(data => {
        hideSpinner();
        console.log('Response:', data);
        if (data.success) {
            showToast('User created successfully', 'success');
            closeModal('addUserModal');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast('Error: ' + (data.error || 'Unknown error'), 'error');
        }
    })
    .catch(error => {
        hideSpinner();
        console.error('Fetch error:', error);
        showToast('Network error. Please try again.', 'error');
    });
}

function editUser(username) {
    showToast('Edit feature coming soon', 'info');
}

function deleteUser(username) {
    if (!confirm(`Are you sure you want to delete user ${username}? This action cannot be undone.`)) {
        return;
    }
    
    showSpinner();
    
    fetch('/admin/delete-user', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            username: username
        })
    })
    .then(response => response.json())
    .then(data => {
        hideSpinner();
        if (data.success) {
            showToast('User deleted successfully', 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast('Error: ' + (data.error || 'Unknown error'), 'error');
        }
    })
    .catch(error => {
        hideSpinner();
        console.error('Fetch error:', error);
        showToast('Network error. Please try again.', 'error');
    });
}

// Report Functions
function generateReport() {
    showSpinner();
    setTimeout(() => {
        hideSpinner();
        showToast('Report generation coming soon', 'info');
    }, 1000);
}

function downloadReport(reportType) {
    showSpinner();
    
    fetch(`/admin/download-report/${reportType}`)
    .then(response => {
        if (!response.ok) throw new Error('Download failed');
        return response.blob();
    })
    .then(blob => {
        hideSpinner();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${reportType}_report_${new Date().toISOString().slice(0,10)}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        
        showToast(`${reportType} report downloaded successfully`, 'success');
    })
    .catch(error => {
        hideSpinner();
        console.error('Download error:', error);
        showToast('Error downloading report', 'error');
    });
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
    if (window.showToast) {
        window.showToast(message, type);
    } else {
        alert(message);
    }
}

function handleAjaxError(error) {
    console.error('AJAX Error:', error);
    showToast('An error occurred. Please try again.', 'error');
}
