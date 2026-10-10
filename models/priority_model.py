# priority_model_xgboost.py
# Modern approach using XGBoost (Industry Standard 2024)

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report, accuracy_score, confusion_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from xgboost import XGBClassifier
import joblib
import warnings
warnings.filterwarnings('ignore')

print("🚀 Building PRIORITY Prediction Model using XGBoost (Modern Approach)")
print("="*60)

# STEP 1: Load data
df = pd.read_csv('bug_reports_FINAL_v7.csv')
print(f"✅ Loaded {len(df)} bugs")

# STEP 2: Check priority distribution
print("\n📊 Priority distribution in data:")
print(df['priority'].value_counts())

# STEP 3: Encode priority labels
priority_encoder = LabelEncoder()
df['priority_label'] = priority_encoder.fit_transform(df['priority'])
print("\n✅ Priority encoding:")
for i, priority in enumerate(priority_encoder.classes_):
    print(f"   {priority} -> {i}")

# STEP 4: Encode severity
severity_encoder = LabelEncoder()
df['severity_encoded'] = severity_encoder.fit_transform(df['severity'])
print("\n✅ Severity encoding:")
for i, sev in enumerate(severity_encoder.classes_):
    print(f"   {sev} -> {i}")

# STEP 5: Encode component
component_encoder = LabelEncoder()
df['component_encoded'] = component_encoder.fit_transform(df['component'])
print("\n✅ Component encoding (first 5):")
for comp in df['component'].unique()[:5]:
    print(f"   {comp} -> {component_encoder.transform([comp])[0]}")

# STEP 6: Create text features from title
print("\n📝 Creating text features from titles using TF-IDF...")
tfidf = TfidfVectorizer(max_features=30, stop_words='english')
title_features = tfidf.fit_transform(df['title']).toarray()
print(f"✅ Created {title_features.shape[1]} text features")

# STEP 7: Combine all features
X = np.column_stack([
    df['severity_encoded'],
    df['component_encoded'],
    title_features
])
y = df['priority_label']

print(f"\n✅ Feature matrix shape: {X.shape}")
print(f"   - Severity: 1 feature")
print(f"   - Component: 1 feature")
print(f"   - Text: {title_features.shape[1]} features")
print(f"   Total: {X.shape[1]} features")

# STEP 8: Split data
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)
print(f"\n✅ Data split:")
print(f"   Training: {len(X_train)} samples")
print(f"   Testing: {len(X_test)} samples")

# STEP 9: Train XGBoost model (MODERN APPROACH)
print("\n🤖 Training XGBoost model...")
model = XGBClassifier(
    n_estimators=100,        # Number of trees
    learning_rate=0.1,        # Step size shrinkage
    max_depth=6,              # Tree depth
    random_state=42,          # Reproducibility
    use_label_encoder=False,  # Avoid warning
    eval_metric='mlogloss',   # Metric for multi-class
    verbosity=0               # Quiet mode
)

# Train the model
model.fit(X_train, y_train)
print("✅ Model training complete!")

# STEP 10: Make predictions
y_pred = model.predict(X_test)

# STEP 11: Evaluate
accuracy = accuracy_score(y_test, y_pred)
print(f"\n📊 Model Accuracy: {accuracy:.2%}")

# Detailed classification report
print("\n📋 Detailed Classification Report:")
print(classification_report(y_test, y_pred, 
                          target_names=priority_encoder.classes_))

# STEP 12: Feature importance (Great for viva!)
print("\n🔍 Top 5 features influencing priority:")
importance = model.feature_importances_
feature_names = ['severity', 'component'] + [f'word_{i}' for i in range(title_features.shape[1])]
feature_importance = sorted(zip(feature_names, importance), key=lambda x: x[1], reverse=True)
for name, imp in feature_importance[:5]:
    print(f"   {name}: {imp:.3f}")

# STEP 13: Test with a new bug
print("\n🔍 Testing with a new bug report...")
test_bug = {
    'title': 'Payment fails for international credit cards',
    'severity': 'High',
    'component': 'Payment'
}

# Encode test data
test_severity = severity_encoder.transform([test_bug['severity']])[0]
test_component = component_encoder.transform([test_bug['component']])[0]
test_title_features = tfidf.transform([test_bug['title']]).toarray()[0]

# Combine features
test_features = np.array([[test_severity, test_component] + list(test_title_features)])

# Predict
pred_priority = model.predict(test_features)[0]
pred_priority_name = priority_encoder.inverse_transform([pred_priority])[0]
print(f"\n   New bug: {test_bug['title']}")
print(f"   Severity: {test_bug['severity']}, Component: {test_bug['component']}")
print(f"   Predicted Priority: {pred_priority_name}")

# STEP 14: Save model and encoders
print("\n💾 Saving model and encoders...")
joblib.dump(model, 'priority_xgboost_model.pkl')
joblib.dump(priority_encoder, 'priority_encoder.pkl')
joblib.dump(severity_encoder, 'severity_encoder.pkl')
joblib.dump(component_encoder, 'component_encoder.pkl')
joblib.dump(tfidf, 'priority_tfidf.pkl')
print("✅ Model saved as 'priority_xgboost_model.pkl'")
print("✅ Encoders saved")

print("\n🎉 PRIORITY MODEL BUILD SUCCESSFUL!")
print("="*60)