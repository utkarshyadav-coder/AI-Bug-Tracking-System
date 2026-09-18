import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
import joblib
import mysql.connector
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print("🚀 Building Sprint Risk Prediction Model...")
print("="*60)

# ========== CONNECT TO DATABASE ==========
conn = mysql.connector.connect(
    host='localhost',
    user='root',
    password='Shivani@18',  # Your MySQL password
    database='bugtracker'
)

# ========== LOAD BUG DATA ==========
print("\n📊 Loading bug data...")
df = pd.read_sql("SELECT * FROM bugs", conn)
if len(df) == 0:
    print("❌ No bugs found in database!")
    exit(1)
print(f"✅ Loaded {len(df)} total bugs")

# Load developer data for team velocity
dev_df = pd.read_sql("SELECT username FROM users WHERE role = 'developer'", conn)
team_size = len(dev_df)
print(f"✅ Team size: {team_size} developers")

conn.close()

# Convert dates
df['created_date'] = pd.to_datetime(df['created_date'])
df['closed_date'] = pd.to_datetime(df['closed_date'], errors='coerce')

# ========== CREATE SPRINT DATA ==========
print("\n📅 Creating sprint simulations...")

# Generate synthetic sprints (last 6 months, 2-week sprints)
sprints = []
sprint_duration = 14  # days
num_sprints = 12  # 6 months of sprints

for i in range(num_sprints):
    sprint_end = datetime.now() - timedelta(days=i * sprint_duration)
    sprint_start = sprint_end - timedelta(days=sprint_duration)
    
    # Get bugs created during this sprint
    sprint_bugs = df[
        (df['created_date'] >= sprint_start) & 
        (df['created_date'] < sprint_end)
    ]
    
    if len(sprint_bugs) > 0:
        # Calculate sprint metrics
        total_bugs = len(sprint_bugs)
        critical_count = len(sprint_bugs[sprint_bugs['severity'] == 'Critical'])
        high_count = len(sprint_bugs[sprint_bugs['severity'] == 'High'])
        p0_count = len(sprint_bugs[sprint_bugs['priority'] == 'P0'])
        p1_count = len(sprint_bugs[sprint_bugs['priority'] == 'P1'])
        
        # Resolution metrics
        resolved_bugs = len(sprint_bugs[sprint_bugs['status'] == 'Closed'])
        resolution_rate = resolved_bugs / total_bugs if total_bugs > 0 else 0
        
        avg_resolution = sprint_bugs[sprint_bugs['resolution_time'].notna()]['resolution_time'].mean() or 0
        reopen_rate = sprint_bugs['reopen_count'].mean() or 0
        
        # Bug arrival rate (bugs per day)
        bug_arrival_rate = total_bugs / sprint_duration
        
        # Calculate if sprint was successful (label)
        # Success = >70% bugs resolved AND avg resolution < 10 days
        successful = 1 if (resolution_rate > 0.7 and avg_resolution < 10) else 0
        
        sprints.append({
            'sprint_id': f"SPRINT-{i+1}",
            'total_bugs': total_bugs,
            'critical_count': critical_count,
            'high_count': high_count,
            'p0_count': p0_count,
            'p1_count': p1_count,
            'resolution_rate': resolution_rate,
            'avg_resolution': avg_resolution,
            'reopen_rate': reopen_rate,
            'bug_arrival_rate': bug_arrival_rate,
            'team_size': team_size,
            'workload_per_dev': total_bugs / team_size,
            'successful': successful
        })

sprint_df = pd.DataFrame(sprints)
print(f"✅ Created {len(sprint_df)} sprint records")

print("\n📊 Sample sprint data:")
print(sprint_df[['sprint_id', 'total_bugs', 'resolution_rate', 'avg_resolution', 'successful']].head())

# ========== PREPARE FEATURES FOR MODEL ==========
print("\n🔧 Preparing features...")

feature_columns = [
    'total_bugs', 'critical_count', 'high_count', 'p0_count', 'p1_count',
    'avg_resolution', 'reopen_rate', 'bug_arrival_rate', 'workload_per_dev'
]

X = sprint_df[feature_columns]
y = sprint_df['successful']

print(f"✅ Feature matrix shape: {X.shape}")
print(f"   Features: {', '.join(feature_columns)}")
print(f"   Target distribution:")
print(f"   Successful sprints: {(y == 1).sum()}")
print(f"   Risky sprints: {(y == 0).sum()}")

# ========== TRAIN MODEL ==========
print("\n🤖 Training Random Forest model...")

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

model = RandomForestClassifier(
    n_estimators=100,
    max_depth=10,
    min_samples_split=5,
    random_state=42
)

model.fit(X_train, y_train)

# ========== EVALUATE MODEL ==========
print("\n📊 Evaluating model...")

y_pred = model.predict(X_test)
accuracy = accuracy_score(y_test, y_pred)
print(f"✅ Model Accuracy: {accuracy:.2%}")

# Fix for small dataset - handle case when only one class in test set
unique_classes = np.unique(y_test)
if len(unique_classes) == 1:
    print(f"\n📋 Note: Test set contains only {unique_classes[0]} class")
    print(f"   Predictions: {np.unique(y_pred)}")
    print(f"   With more data, we would see proper classification report")
else:
    print("\n📋 Classification Report:")
    print(classification_report(y_test, y_pred, target_names=['Risky', 'Successful']))

# ========== FEATURE IMPORTANCE ==========
print("\n🔍 Feature Importance:")
importance = model.feature_importances_
for name, imp in sorted(zip(feature_columns, importance), key=lambda x: x[1], reverse=True):
    print(f"   {name}: {imp:.3f}")

# ========== SAVE MODEL ==========
print("\n💾 Saving model...")
joblib.dump(model, './sprint_risk_model.pkl')
joblib.dump(feature_columns, './sprint_risk_features.pkl')
print("✅ Model saved as 'sprint_risk_model.pkl'")

# ========== TEST PREDICTION ==========
print("\n🧪 Testing with new sprint data...")

# Create a test sprint
test_sprint = pd.DataFrame([{
    'total_bugs': 25,
    'critical_count': 3,
    'high_count': 5,
    'p0_count': 2,
    'p1_count': 4,
    'avg_resolution': 8.5,
    'reopen_rate': 0.12,
    'bug_arrival_rate': 1.8,
    'workload_per_dev': 25 / team_size
}])

prediction = model.predict(test_sprint)[0]
probability = model.predict_proba(test_sprint)[0]

print(f"\n📌 Test Sprint Metrics:")
print(f"   Total Bugs: 25")
print(f"   Critical: 3, P0: 2")
print(f"   Avg Resolution: 8.5 days")
print(f"   Reopen Rate: 12%")

print(f"\n🎯 Prediction: {'✅ SUCCESSFUL' if prediction == 1 else '⚠️ RISKY'}")
print(f"   Confidence: {max(probability):.2%}")
print(f"   Risk Score: {probability[0]:.2%}")

print("\n🎉 SPRINT RISK MODEL BUILD SUCCESSFUL!")