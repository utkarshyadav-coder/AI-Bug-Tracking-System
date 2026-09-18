requireLogin();

const form = document.getElementById("report-bug-form");
const resultBox = document.getElementById("result-box");

form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const payload = {
        title: document.getElementById("title").value.trim(),
        description: document.getElementById("description").value.trim(),
        component: document.getElementById("component").value,
    };

    try {
        const bug = await apiFetch("/bugs", {
            method: "POST",
            body: JSON.stringify(payload),
        });

        resultBox.innerHTML = `
            <p><strong>Bug filed:</strong> ${bug.bugId}</p>
            <p><strong>Predicted Severity:</strong> ${bug.severity}</p>
            <p><strong>Predicted Priority:</strong> ${bug.priority}</p>
        `;
        form.reset();
    } catch (err) {
        resultBox.textContent = "Failed to submit bug: " + err.message;
    }
});
