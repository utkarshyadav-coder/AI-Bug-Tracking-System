package com.bugtracker.model;

import jakarta.persistence.*;
import java.time.LocalDate;

@Entity
@Table(name = "bugs")
public class Bug {

    @Id
    @Column(name = "bug_id", length = 20)
    private String bugId;

    @Column(nullable = false)
    private String title;

    @Column(nullable = false, columnDefinition = "TEXT")
    private String description;

    @Enumerated(EnumType.STRING)
    private Severity severity = Severity.Medium;

    @Enumerated(EnumType.STRING)
    private Priority priority = Priority.P2;

    private String component;

    @Column(name = "assigned_to")
    private String assignedTo;

    @Column(name = "reported_by", nullable = false)
    private String reportedBy;

    @Column(name = "created_date", nullable = false)
    private LocalDate createdDate;

    @Column(name = "closed_date")
    private LocalDate closedDate;

    @Enumerated(EnumType.STRING)
    private Status status = Status.Open;

    @Column(name = "resolution_time")
    private Float resolutionTime;

    @Column(name = "reopen_count")
    private Integer reopenCount = 0;

    public enum Severity { Critical, High, Medium, Low }
    public enum Priority { P0, P1, P2, P3 }
    public enum Status { Open, In_Progress, Fixed, Verified, Closed, Reopened }

    public Bug() {}

    public String getBugId() { return bugId; }
    public void setBugId(String bugId) { this.bugId = bugId; }
    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }
    public Severity getSeverity() { return severity; }
    public void setSeverity(Severity severity) { this.severity = severity; }
    public Priority getPriority() { return priority; }
    public void setPriority(Priority priority) { this.priority = priority; }
    public String getComponent() { return component; }
    public void setComponent(String component) { this.component = component; }
    public String getAssignedTo() { return assignedTo; }
    public void setAssignedTo(String assignedTo) { this.assignedTo = assignedTo; }
    public String getReportedBy() { return reportedBy; }
    public void setReportedBy(String reportedBy) { this.reportedBy = reportedBy; }
    public LocalDate getCreatedDate() { return createdDate; }
    public void setCreatedDate(LocalDate createdDate) { this.createdDate = createdDate; }
    public LocalDate getClosedDate() { return closedDate; }
    public void setClosedDate(LocalDate closedDate) { this.closedDate = closedDate; }
    public Status getStatus() { return status; }
    public void setStatus(Status status) { this.status = status; }
    public Float getResolutionTime() { return resolutionTime; }
    public void setResolutionTime(Float resolutionTime) { this.resolutionTime = resolutionTime; }
    public Integer getReopenCount() { return reopenCount; }
    public void setReopenCount(Integer reopenCount) { this.reopenCount = reopenCount; }
}
