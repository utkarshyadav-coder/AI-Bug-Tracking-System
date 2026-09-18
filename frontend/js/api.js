// Central place for talking to the Spring Boot backend.
const API_BASE = "http://localhost:8080/api";

function authHeaders() {
    const token = localStorage.getItem("token");
    return token ? { "Authorization": `Bearer ${token}` } : {};
}

async function apiFetch(path, options = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...authHeaders(),
            ...(options.headers || {}),
        },
    });

    if (res.status === 401) {
        localStorage.clear();
        window.location.href = "login.html";
        return null;
    }

    if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Request failed: ${res.status}`);
    }

    const contentType = res.headers.get("content-type") || "";
    return contentType.includes("application/json") ? res.json() : res.text();
}

function requireLogin() {
    if (!localStorage.getItem("token")) {
        window.location.href = "login.html";
    }
}

function currentUser() {
    return {
        username: localStorage.getItem("username"),
        fullName: localStorage.getItem("fullName"),
        role: localStorage.getItem("role"),
    };
}

function logout() {
    localStorage.clear();
    window.location.href = "login.html";
}
