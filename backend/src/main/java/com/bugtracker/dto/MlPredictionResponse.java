package com.bugtracker.dto;

public class MlPredictionResponse {
    private String severity;
    private String priority;

    public String getSeverity() { return severity; }
    public void setSeverity(String severity) { this.severity = severity; }
    public String getPriority() { return priority; }
    public void setPriority(String priority) { this.priority = priority; }
}
