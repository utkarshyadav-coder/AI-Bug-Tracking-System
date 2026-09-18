requireLogin();

const user = currentUser();
document.getElementById("welcome").textContent = `Welcome, ${user.fullName} (${user.role})`;

async function loadStats() {
    const stats = await apiFetch("/dashboard/stats");
    document.getElementById("stat-total").textContent = stats.totalBugs;
    document.getElementById("stat-critical").textContent = stats.critical;
    document.getElementById("stat-high").textContent = stats.high;
    document.getElementById("stat-medium").textContent = stats.medium;
    document.getElementById("stat-low").textContent = stats.low;
    document.getElementById("stat-open").textContent = stats.open;
    document.getElementById("stat-closed").textContent = stats.closed;
}

loadStats().catch((e) => console.error(e));
