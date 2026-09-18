package com.bugtracker.controller;

import com.bugtracker.model.Bug;
import com.bugtracker.repository.BugRepository;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api/dashboard")
public class DashboardController {

    private final BugRepository bugRepository;

    public DashboardController(BugRepository bugRepository) {
        this.bugRepository = bugRepository;
    }

    @GetMapping("/stats")
    public ResponseEntity<Map<String, Object>> stats() {
        Map<String, Object> stats = Map.of(
            "totalBugs", bugRepository.count(),
            "critical", bugRepository.countBySeverity(Bug.Severity.Critical),
            "high", bugRepository.countBySeverity(Bug.Severity.High),
            "medium", bugRepository.countBySeverity(Bug.Severity.Medium),
            "low", bugRepository.countBySeverity(Bug.Severity.Low),
            "open", bugRepository.countByStatus(Bug.Status.Open),
            "closed", bugRepository.countByStatus(Bug.Status.Closed)
        );
        return ResponseEntity.ok(stats);
    }
}
