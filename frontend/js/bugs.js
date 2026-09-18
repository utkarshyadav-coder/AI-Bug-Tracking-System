requireLogin();

async function loadBugs() {
    const bugs = await apiFetch("/bugs");
    const tbody = document.getElementById("bugs-body");
    tbody.innerHTML = "";

    bugs.forEach((bug) => {
        const row = document.createElement("tr");
        row.innerHTML = `
            <td>${bug.bugId}</td>
            <td>${bug.title}</td>
            <td><span class="badge severity-${bug.severity}">${bug.severity}</span></td>
            <td><span class="badge priority-${bug.priority}">${bug.priority}</span></td>
            <td>${bug.component ?? ""}</td>
            <td>${bug.status}</td>
            <td>${bug.assignedTo ?? "Unassigned"}</td>
        `;
        tbody.appendChild(row);
    });
}

loadBugs().catch((e) => console.error(e));
