document.getElementById("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;
    const errorBox = document.getElementById("error-box");
    errorBox.textContent = "";

    try {
        const data = await apiFetch("/auth/login", {
            method: "POST",
            body: JSON.stringify({ username, password }),
        });

        localStorage.setItem("token", data.token);
        localStorage.setItem("username", data.username);
        localStorage.setItem("fullName", data.fullName);
        localStorage.setItem("role", data.role);

        window.location.href = "dashboard.html";
    } catch (err) {
        errorBox.textContent = "Invalid username or password.";
    }
});
