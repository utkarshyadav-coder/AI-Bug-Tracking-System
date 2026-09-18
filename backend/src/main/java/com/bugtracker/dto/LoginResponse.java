package com.bugtracker.dto;

public class LoginResponse {
    private String token;
    private String username;
    private String fullName;
    private String role;

    public LoginResponse(String token, String username, String fullName, String role) {
        this.token = token;
        this.username = username;
        this.fullName = fullName;
        this.role = role;
    }

    public String getToken() { return token; }
    public String getUsername() { return username; }
    public String getFullName() { return fullName; }
    public String getRole() { return role; }
}
