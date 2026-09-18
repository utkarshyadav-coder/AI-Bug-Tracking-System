package com.bugtracker.service;

import com.bugtracker.dto.MlPredictionResponse;
import com.bugtracker.dto.SuggestionsResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.Map;

/**
 * Thin client for the Python ML microservice. Keeping this isolated means
 * the rest of the backend never talks HTTP to Python directly, and the base
 * URL / timeout / error handling live in exactly one place.
 */
@Service
public class MLClient {

    private final RestClient restClient;

    public MLClient(@Value("${ml.service.base-url}") String baseUrl) {
        this.restClient = RestClient.builder().baseUrl(baseUrl).build();
    }

    public MlPredictionResponse predict(String title, String description, String component) {
        return restClient.post()
                .uri("/api/ml/predict")
                .body(Map.of("title", title, "description", description, "component", component))
                .retrieve()
                .body(MlPredictionResponse.class);
    }

    public SuggestionsResponse suggestDevelopers(String component, int topN) {
        return restClient.post()
                .uri("/api/ml/suggest-developers")
                .body(Map.of("component", component, "topN", topN))
                .retrieve()
                .body(SuggestionsResponse.class);
    }
}
