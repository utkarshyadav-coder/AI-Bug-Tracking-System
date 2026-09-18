"""
AI / ML microservice for the Bug Tracking system.

Responsibilities (kept separate from the Java Spring Boot backend so the
two can scale and be deployed independently, and so the ML stack stays in
Python where the trained models already live):

    POST /api/ml/predict              -> severity + priority for a new bug
    POST /api/ml/suggest-developers   -> ranked developer suggestions
    GET  /health                      -> liveness check for the Spring Boot
                                          backend / load balancer

The Spring Boot backend is the ONLY thing that should call this service in
production; it is not meant to be exposed directly to the browser.
"""

import os
import joblib
import numpy as np
import torch
from flask import Flask, request, jsonify
from flask_cors import CORS
from transformers import DistilBertTokenizer, DistilBertForSequenceClassification

app = Flask(__name__)
CORS(app)  # allow calls from the Spring Boot backend during local dev

MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")

# ---------------------------------------------------------------- #
# Load models once at startup
# ---------------------------------------------------------------- #
print("Loading ML models...")

severity_model = None
severity_tokenizer = None
severity_map = {0: "Critical", 1: "High", 2: "Low", 3: "Medium"}

severity_model_path = os.path.join(MODELS_DIR, "bug_severity_model")
if os.path.exists(severity_model_path):
    try:
        severity_tokenizer = DistilBertTokenizer.from_pretrained(severity_model_path)
        severity_model = DistilBertForSequenceClassification.from_pretrained(severity_model_path)
        severity_model.eval()
        print("  severity model loaded")
    except Exception as e:
        print(f"  could not load severity model: {e}")
else:
    print("  severity model folder missing, falling back to 'Medium' default")

priority_model = priority_encoder = severity_encoder = component_encoder = tfidf = None
try:
    priority_model = joblib.load(os.path.join(MODELS_DIR, "priority_xgboost_model.pkl"))
    priority_encoder = joblib.load(os.path.join(MODELS_DIR, "priority_encoder.pkl"))
    severity_encoder = joblib.load(os.path.join(MODELS_DIR, "severity_encoder.pkl"))
    component_encoder = joblib.load(os.path.join(MODELS_DIR, "component_encoder.pkl"))
    tfidf = joblib.load(os.path.join(MODELS_DIR, "priority_tfidf.pkl"))
    print("  priority model loaded")
except Exception as e:
    print(f"  could not load priority model: {e}")

developer_data = tfidf_assigner = developers_list = None
try:
    dev_bundle = joblib.load(os.path.join(MODELS_DIR, "developer_assignment_data.pkl"))
    developer_data = dev_bundle["developer_data"]
    tfidf_assigner = dev_bundle["tfidf"]
    developers_list = dev_bundle["developers"]
    print("  developer-assignment data loaded")
except Exception as e:
    print(f"  could not load developer-assignment data: {e}")

print("Model loading complete.")


# ---------------------------------------------------------------- #
# Core prediction helpers (ported from the original Flask app.py)
# ---------------------------------------------------------------- #
def predict_severity_and_priority(title: str, description: str, component: str):
    severity = "Medium"
    priority = "P2"

    if severity_model is not None:
        try:
            text = f"{title} {description}"
            inputs = severity_tokenizer(
                text, return_tensors="pt", truncation=True, padding=True, max_length=128
            )
            with torch.no_grad():
                outputs = severity_model(**inputs)
                pred = torch.argmax(outputs.logits, dim=1).item()
            severity = severity_map.get(pred, "Medium")
        except Exception as e:
            print(f"severity prediction error: {e}")

    if priority_model is not None:
        try:
            sev_encoded = (
                severity_encoder.transform([severity])[0]
                if severity in severity_encoder.classes_
                else 2
            )
            comp_encoded = (
                component_encoder.transform([component])[0]
                if component in component_encoder.classes_
                else 0
            )
            title_features = tfidf.transform([title]).toarray()[0]
            features = np.array([[sev_encoded, comp_encoded] + list(title_features)])
            pred = priority_model.predict(features)[0]
            priority = priority_encoder.inverse_transform([pred])[0]
        except Exception as e:
            print(f"priority prediction error: {e}")

    return severity, priority


def suggest_developers(component: str, top_n: int = 3):
    """Rank developers by component expertise, historical performance and
    current workload. Text (title/description) is accepted for future use
    (e.g. TF-IDF similarity against past bugs) but the current scoring only
    needs the component, mirroring the original implementation."""
    if not developer_data:
        return []

    scores = {}
    for dev in developers_list:
        profile = developer_data.get(dev, {})
        score = 0

        # Component match (weighted highest)
        component_counts = profile.get("component_counts", {})
        score += 30 if component in component_counts else 5

        # Historical performance
        if profile.get("total_bugs", 0) > 0:
            res_time = profile.get("avg_resolution", 5)
            score += 25 if res_time < 3 else 20 if res_time < 5 else 15 if res_time < 8 else 10

            reopen = profile.get("reopen_rate", 0)
            score += 25 if reopen < 0.1 else 20 if reopen < 0.2 else 15
        else:
            score += 30

        # Current workload (fewer open bugs = higher score)
        workload = profile.get("workload", 0)
        score += 20 if workload == 0 else 15 if workload < 3 else 10 if workload < 5 else 5

        scores[dev] = score

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [{"developer": dev, "score": score} for dev, score in ranked]


# ---------------------------------------------------------------- #
# Routes
# ---------------------------------------------------------------- #
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "up",
        "severity_model_loaded": severity_model is not None,
        "priority_model_loaded": priority_model is not None,
        "developer_model_loaded": developer_data is not None,
    })


@app.route("/api/ml/predict", methods=["POST"])
def predict():
    data = request.get_json(force=True) or {}
    title = data.get("title", "")
    description = data.get("description", "")
    component = data.get("component", "")

    if not title or not description:
        return jsonify({"error": "title and description are required"}), 400

    severity, priority = predict_severity_and_priority(title, description, component)
    return jsonify({"severity": severity, "priority": priority})


@app.route("/api/ml/suggest-developers", methods=["POST"])
def suggest_developers_route():
    data = request.get_json(force=True) or {}
    component = data.get("component", "")
    top_n = int(data.get("topN", 3))

    suggestions = suggest_developers(component, top_n=top_n)
    return jsonify({"suggestions": suggestions})


if __name__ == "__main__":
    # In production run this behind gunicorn, e.g.:
    #   gunicorn -w 2 -b 0.0.0.0:5001 app:app
    app.run(host="0.0.0.0", port=5001, debug=True)
