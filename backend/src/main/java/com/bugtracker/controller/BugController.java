package com.bugtracker.controller;

import com.bugtracker.dto.BugRequest;
import com.bugtracker.dto.SuggestionsResponse;
import com.bugtracker.model.Bug;
import com.bugtracker.model.User;
import com.bugtracker.repository.UserRepository;
import com.bugtracker.service.BugService;
import com.bugtracker.service.MLClient;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/bugs")
public class BugController {

    private final BugService bugService;
    private final MLClient mlClient;
    private final UserRepository userRepository;

    public BugController(BugService bugService, MLClient mlClient, UserRepository userRepository) {
        this.bugService = bugService;
        this.mlClient = mlClient;
        this.userRepository = userRepository;
    }

    /** Report a new bug. Severity + priority are predicted by the ML service. */
    @PostMapping
    public ResponseEntity<Bug> reportBug(@Valid @RequestBody BugRequest request, Authentication auth) {
        Bug bug = bugService.reportBug(request, auth.getName());
        return ResponseEntity.ok(bug);
    }

    /** List bugs visible to the current user (all bugs for manager/admin, own for others). */
    @GetMapping
    public ResponseEntity<List<Bug>> listBugs(Authentication auth) {
        User user = userRepository.findByUsername(auth.getName())
                .orElseThrow(() -> new IllegalArgumentException("Unknown user"));
        boolean privileged = user.getRole() == User.Role.manager || user.getRole() == User.Role.admin;
        return ResponseEntity.ok(bugService.getBugsForUser(auth.getName(), privileged));
    }

    /** Tester marks a bug as passed (Verified) or failed (Reopened) after a fix. */
    @PostMapping("/{bugId}/verify")
    public ResponseEntity<Bug> verifyBug(@PathVariable String bugId, @RequestBody Map<String, String> body) {
        boolean passed = "pass".equalsIgnoreCase(body.get("result"));
        return ResponseEntity.ok(bugService.verifyBug(bugId, passed));
    }

    /** Ask the ML service which developers best fit a given component. */
    @PostMapping("/suggest-developers")
    public ResponseEntity<SuggestionsResponse> suggestDevelopers(@RequestBody Map<String, Object> body) {
        String component = (String) body.getOrDefault("component", "");
        int topN = body.get("topN") != null ? ((Number) body.get("topN")).intValue() : 3;
        return ResponseEntity.ok(mlClient.suggestDevelopers(component, topN));
    }
}
