package com.bugtracker.repository;

import com.bugtracker.model.Bug;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface BugRepository extends JpaRepository<Bug, String> {

    List<Bug> findAllByOrderByCreatedDateDesc();

    List<Bug> findByReportedByOrAssignedToOrderByCreatedDateDesc(String reportedBy, String assignedTo);

    List<Bug> findByReportedByOrderByCreatedDateDesc(String reportedBy);

    long countBySeverity(Bug.Severity severity);

    long countByPriority(Bug.Priority priority);

    long countByStatus(Bug.Status status);
}
