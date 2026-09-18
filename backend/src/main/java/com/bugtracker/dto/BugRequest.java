package com.bugtracker.dto;

import jakarta.validation.constraints.NotBlank;

public class BugRequest {
    @NotBlank
    private String title;
    @NotBlank
    private String description;
    @NotBlank
    private String component;

    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }
    public String getComponent() { return component; }
    public void setComponent(String component) { this.component = component; }
}
