package com.bugtracker.service;

import com.bugtracker.dto.BugRequest;
import com.bugtracker.dto.MlPredictionResponse;
import com.bugtracker.model.Bug;
import com.bugtracker.repository.BugRepository;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.List;

@Service
public class BugService {

    private final BugRepository bugRepository;
    private final MLClient mlClient;

    public BugService(BugRepository bugRepository, MLClient mlClient) {
        this.bugRepository = bugRepository;
        this.mlClient = mlClient;
    }

    /** Creates a bug, asking the ML service to predict severity + priority. */
    public Bug reportBug(BugRequest request, String reportedBy) {
        MlPredictionResponse prediction = mlClient.predict(
                request.getTitle(), request.getDescription(), request.getComponent());

        Bug bug = new Bug();
        bug.setBugId(nextBugId());
        bug.setTitle(request.getTitle());
        bug.setDescription(request.getDescription());
        bug.setComponent(request.getComponent());
        bug.setSeverity(Bug.Severity.valueOf(prediction.getSeverity()));
        bug.setPriority(Bug.Priority.valueOf(prediction.getPriority()));
        bug.setReportedBy(reportedBy);
        bug.setCreatedDate(LocalDate.now());
        bug.setStatus(Bug.Status.Open);
        bug.setReopenCount(0);

        return bugRepository.save(bug);
    }

    private String nextBugId() {
        long count = bugRepository.count();
        return String.format("BUG-%04d", count + 1);
    }

    public List<Bug> getAllBugs() {
        return bugRepository.findAllByOrderByCreatedDateDesc();
    }

    public List<Bug> getBugsForUser(String username, boolean isManagerOrAdmin) {
        if (isManagerOrAdmin) {
            return bugRepository.findAllByOrderByCreatedDateDesc();
        }
        return bugRepository.findByReportedByOrAssignedToOrderByCreatedDateDesc(username, username);
    }

    public Bug verifyBug(String bugId, boolean passed) {
        Bug bug = bugRepository.findById(bugId)
                .orElseThrow(() -> new IllegalArgumentException("Bug not found: " + bugId));

        if (passed) {
            bug.setStatus(Bug.Status.Verified);
            bug.setClosedDate(LocalDate.now());
        } else {
            bug.setStatus(Bug.Status.Reopened);
            bug.setReopenCount(bug.getReopenCount() + 1);
        }
        return bugRepository.save(bug);
    }
}
