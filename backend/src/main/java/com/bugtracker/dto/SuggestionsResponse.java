package com.bugtracker.dto;

import java.util.List;

public class SuggestionsResponse {
    private List<DeveloperSuggestion> suggestions;

    public List<DeveloperSuggestion> getSuggestions() { return suggestions; }
    public void setSuggestions(List<DeveloperSuggestion> suggestions) { this.suggestions = suggestions; }
}
