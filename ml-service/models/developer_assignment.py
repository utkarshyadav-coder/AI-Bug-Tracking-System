import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
import joblib
import mysql.connector
import warnings
warnings.filterwarnings('ignore')

print("🚀 Building Developer Assignment Model...")
print("="*60)

# ========== CONNECT TO DATABASE ==========
conn = mysql.connector.connect(
    host='localhost',
    user='root',
    password='Shivani@18',  # YOUR PASSWORD
    database='bugtracker'
)

# ========== LOAD DATA ==========
print("\n📊 Loading bug data...")
df = pd.read_sql("SELECT * FROM bugs WHERE assigned_to IS NOT NULL", conn)
print(f"✅ Loaded {len(df)} bugs with assignments")

# Load developer data
dev_df = pd.read_sql("SELECT username FROM users WHERE role = 'developer'", conn)
developers = dev_df['username'].tolist()
print(f"✅ Found {len(developers)} developers: {', '.join(developers)}")

conn.close()

# ========== CREATE DEVELOPER PROFILES ==========
print("\n👤 Creating developer expertise profiles...")

developer_data = {}

for dev in developers:
    dev_bugs = df[df['assigned_to'] == dev]
    
    if len(dev_bugs) > 0:
        # Component expertise
        component_counts = dev_bugs['component'].value_counts().to_dict()
        total_bugs = len(dev_bugs)
        
        # Performance metrics
        avg_resolution = float(dev_bugs['resolution_time'].mean() or 5.0)
        reopen_rate = float(dev_bugs['reopen_count'].mean() or 0)
        
        # Current workload
        workload = len(dev_bugs[dev_bugs['status'].isin(['Open', 'In Progress'])])
        
        developer_data[dev] = {
            'component_counts': component_counts,
            'total_bugs': total_bugs,
            'avg_resolution': avg_resolution,
            'reopen_rate': reopen_rate,
            'workload': workload
        }
        print(f"  ✅ {dev}: {total_bugs} bugs fixed")
    else:
        developer_data[dev] = {
            'component_counts': {},
            'total_bugs': 0,
            'avg_resolution': 5.0,
            'reopen_rate': 0.1,
            'workload': 0
        }
        print(f"  ⚠️ {dev}: No history")

# ========== CREATE TF-IDF ==========
print("\n📝 Creating text features...")
tfidf = TfidfVectorizer(max_features=50, stop_words='english')
tfidf.fit(df['title'])

# ========== SAVE EVERYTHING AS A DICTIONARY ==========
print("\n💾 Saving model data...")

model_data = {
    'developer_data': developer_data,
    'tfidf': tfidf,
    'developers': developers
}

joblib.dump(model_data, './developer_assignment_data.pkl')
print("✅ Model saved as 'developer_assignment_data.pkl'")

print("\n🎉 BUILD SUCCESSFUL!")
