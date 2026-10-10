from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import joblib
import numpy as np
from datetime import datetime
import os
import mysql.connector
from werkzeug.security import check_password_hash, generate_password_hash

import config
from ai.resolution_engine import (
    KnowledgeBase, ResolutionAdvisor, LLMFixPlanner, FallbackSeverity,
)

# transformers/torch are heavy and the DistilBERT weights may be absent;
# the app degrades gracefully to the TF-IDF severity classifier.
try:
    import torch
    from transformers import DistilBertTokenizer, DistilBertForSequenceClassification
except Exception as _e:  # pragma: no cover
    torch = None
    print(f"⚠️ transformers/torch unavailable ({_e}); using fallback severity model")

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

print("🚀 Loading ML models...")

# ========== LOAD SEVERITY MODEL ==========
try:
    model_path = './models/bug_severity_model'
    has_weights = any(os.path.exists(os.path.join(model_path, f))
                      for f in ('model.safetensors', 'pytorch_model.bin'))
    if torch is not None and has_weights:
        severity_tokenizer = DistilBertTokenizer.from_pretrained(model_path)
        severity_model = DistilBertForSequenceClassification.from_pretrained(model_path)
        severity_model.eval()
        severity_map = {0: "Critical", 1: "High", 2: "Low", 3: "Medium"}
        print("✅ Severity model loaded")
    else:
        print("⚠️ DistilBERT weights not found (model.safetensors missing) - using fallback severity model")
        severity_model = None
except Exception as e:
    print("❌ Error loading severity model:", e)
    severity_model = None

# ========== LOAD PRIORITY MODEL ==========
try:
    if os.path.exists('./models/priority_xgboost_model.pkl'):
        priority_model = joblib.load('./models/priority_xgboost_model.pkl')
        priority_encoder = joblib.load('./models/priority_encoder.pkl')
        severity_encoder = joblib.load('./models/severity_encoder.pkl')
        component_encoder = joblib.load('./models/component_encoder.pkl')
        tfidf = joblib.load('./models/priority_tfidf.pkl')
        print("✅ Priority model loaded")
    else:
        print("❌ Priority model files not found")
        priority_model = None
except Exception as e:
    print("❌ Error loading priority model:", e)
    priority_model = None

# ========== LOAD DEVELOPER ASSIGNMENT DATA ==========
try:
    if os.path.exists('./models/developer_assignment_data.pkl'):
        model_data = joblib.load('./models/developer_assignment_data.pkl')
        developer_data = model_data['developer_data']
        tfidf_assigner = model_data['tfidf']
        developers_list = model_data['developers']
        print("✅ Developer assignment data loaded")
    else:
        developer_data = None
        print("⚠️ Developer assignment data not found")
except Exception as e:
    print(f"❌ Error loading developer data: {e}")
    developer_data = None

# ========== HELPER FUNCTION: SUGGEST DEVELOPERS ==========
def suggest_developers(title, description, component, severity, top_n=3):
    """DEPRECATED: static scoring from the pickled profile. Superseded by
    ai.resolution_engine.ResolutionAdvisor.recommend_developers (live data + similar-bug evidence)."""
    if not developer_data:
        return []
    
    scores = {}
    text = title + " " + description
    
    for dev in developers_list:
        profile = developer_data.get(dev, {})
        score = 0
        
        # Component match (40% weight)
        component_counts = profile.get('component_counts', {})
        if component in component_counts:
            score += 30
        else:
            score += 5
        
        # Performance (30% weight)
        if profile.get('total_bugs', 0) > 0:
            res_time = profile.get('avg_resolution', 5)
            if res_time < 3:
                score += 25
            elif res_time < 5:
                score += 20
            elif res_time < 8:
                score += 15
            else:
                score += 10
            
            reopen = profile.get('reopen_rate', 0)
            if reopen < 0.1:
                score += 25
            elif reopen < 0.2:
                score += 20
            else:
                score += 15
        else:
            score += 30
        
        # Workload (20% weight)
        workload = profile.get('workload', 0)
        if workload == 0:
            score += 20
        elif workload < 3:
            score += 15
        elif workload < 5:
            score += 10
        else:
            score += 5
        
        scores[dev] = score
    
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [(dev, score) for dev, score in sorted_scores]

# ========== DATABASE CONNECTION ==========
def get_db():
    return mysql.connector.connect(**config.DB_CONFIG)

# ========== AI RESOLUTION ENGINE ==========
import time
fallback_severity = None          # set after the first KB load
llm_planner = LLMFixPlanner()
_ai_cache = {'advisor': None, 'kb': None, 'built': 0.0}
AI_CACHE_TTL = 60  # seconds


def invalidate_ai_cache():
    _ai_cache['built'] = 0.0


def load_developer_profiles(cursor):
    """Live developer stats (expertise, speed, quality, current workload)."""
    cursor.execute("SELECT username FROM users WHERE role = 'developer'")
    profiles = {r['username']: {'component_counts': {}, 'avg_resolution': 5.0,
                                'reopen_rate': 0.1, 'workload': 0, 'total_bugs': 0}
                for r in cursor.fetchall()}
    cursor.execute("""
        SELECT assigned_to, component, COUNT(*) AS n, AVG(resolution_time) AS res,
               AVG(reopen_count) AS reopen
        FROM bugs WHERE assigned_to IS NOT NULL AND status IN ('Closed','Verified','Fixed')
        GROUP BY assigned_to, component
    """)
    agg = {}
    for r in cursor.fetchall():
        p = profiles.get(r['assigned_to'])
        if not p:
            continue
        p['component_counts'][r['component']] = int(r['n'])
        p['total_bugs'] += int(r['n'])
        a = agg.setdefault(r['assigned_to'], [0, 0.0, 0.0])
        a[0] += int(r['n'])
        a[1] += float(r['res'] or 0) * int(r['n'])
        a[2] += float(r['reopen'] or 0) * int(r['n'])
    for dev, (n, res_sum, reopen_sum) in agg.items():
        profiles[dev]['avg_resolution'] = res_sum / n if n else 5.0
        profiles[dev]['reopen_rate'] = reopen_sum / n if n else 0.1
    cursor.execute("""
        SELECT assigned_to, COUNT(*) AS n FROM bugs
        WHERE assigned_to IS NOT NULL AND status NOT IN ('Closed','Verified','Fixed')
        GROUP BY assigned_to
    """)
    for r in cursor.fetchall():
        if r['assigned_to'] in profiles:
            profiles[r['assigned_to']]['workload'] = int(r['n'])
    return profiles


def get_advisor(force=False):
    """Build (or reuse) the knowledge base from the live bugs table."""
    global fallback_severity
    fresh = time.time() - _ai_cache['built'] < AI_CACHE_TTL
    if _ai_cache['advisor'] is not None and fresh and not force:
        return _ai_cache['advisor']
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM bugs")
    bugs_rows = cur.fetchall()
    profiles = load_developer_profiles(cur)
    cur.close()
    conn.close()
    kb = KnowledgeBase(bugs_rows)
    advisor = ResolutionAdvisor(kb, profiles)
    if fallback_severity is None or force:
        fallback_severity = FallbackSeverity(bugs_rows)
    _ai_cache.update(advisor=advisor, kb=kb, built=time.time())
    return advisor


# ========== HELPER: PREDICT BUG ==========
def predict_bug(title, description, component):
    severity = "Medium"
    priority = "P2"
    if severity_model is None and fallback_severity is None:
        try:
            get_advisor()
        except Exception as e:
            print(f"Fallback severity unavailable: {e}")
    
    if severity_model:
        try:
            text = title + " " + description
            inputs = severity_tokenizer(text, return_tensors="pt",
                                      truncation=True, padding=True, max_length=128)
            with torch.no_grad():
                outputs = severity_model(**inputs)
                pred = torch.argmax(outputs.logits, dim=1).item()
            severity = severity_map.get(pred, "Medium")
        except Exception as e:
            print(f"Severity error: {e}")
    
    elif fallback_severity is not None:
        severity, _conf = fallback_severity.predict(title, description, component)

    if priority_model:
        try:
            if severity in severity_encoder.classes_:
                sev_encoded = severity_encoder.transform([severity])[0]
            else:
                sev_encoded = 2
            
            if component in component_encoder.classes_:
                comp_encoded = component_encoder.transform([component])[0]
            else:
                comp_encoded = 0
            
            title_features = tfidf.transform([title]).toarray()[0]
            features = np.array([[sev_encoded, comp_encoded] + list(title_features)])
            pred = priority_model.predict(features)[0]
            priority = priority_encoder.inverse_transform([pred])[0]
        except Exception as e:
            print(f"Priority error: {e}")
    
    return severity, priority

def verify_and_upgrade_password(conn, user, supplied):
    """Check a password against a hash. Legacy plaintext rows are accepted once
    and transparently re-saved as hashes."""
    stored = user['password'] or ''
    if stored.startswith(('scrypt:', 'pbkdf2:')):
        return check_password_hash(stored, supplied)
    if stored == supplied:
        cur = conn.cursor()
        cur.execute("UPDATE users SET password = %s WHERE username = %s",
                    (generate_password_hash(supplied), user['username']))
        conn.commit()
        cur.close()
        return True
    return False

# ========== ROUTES ==========

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        if user and not verify_and_upgrade_password(conn, user, password):
            user = None
        cursor.close()
        conn.close()
        
        if user:
            session['user'] = {
                'username': user['username'],
                'name': user['full_name'],
                'role': user['role']
            }
            
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user['role'] == 'manager':
                return redirect(url_for('manager_dashboard'))
            elif user['role'] == 'tester':
                return redirect(url_for('tester_dashboard'))
            elif user['role'] == 'developer':
                return redirect(url_for('developer_dashboard'))
            else:
                return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='Invalid credentials')
    
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT 
            COUNT(*) as total_bugs,
            SUM(CASE WHEN severity = 'Critical' THEN 1 ELSE 0 END) as critical_bugs,
            SUM(CASE WHEN severity = 'High' THEN 1 ELSE 0 END) as high_bugs,
            SUM(CASE WHEN severity = 'Medium' THEN 1 ELSE 0 END) as medium_bugs,
            SUM(CASE WHEN severity = 'Low' THEN 1 ELSE 0 END) as low_bugs,
            SUM(CASE WHEN priority = 'P0' THEN 1 ELSE 0 END) as p0_count,
            SUM(CASE WHEN priority = 'P1' THEN 1 ELSE 0 END) as p1_count,
            SUM(CASE WHEN priority = 'P2' THEN 1 ELSE 0 END) as p2_count,
            SUM(CASE WHEN priority = 'P3' THEN 1 ELSE 0 END) as p3_count,
            SUM(CASE WHEN priority = 'P4' THEN 1 ELSE 0 END) as p4_count,
            SUM(CASE WHEN status = 'Open' THEN 1 ELSE 0 END) as open_bugs,
            SUM(CASE WHEN status = 'Closed' THEN 1 ELSE 0 END) as closed_bugs
        FROM bugs
    """)
    stats = cursor.fetchone()
    
    priority_counts = {
        'P0': stats['p0_count'] or 0,
        'P1': stats['p1_count'] or 0,
        'P2': stats['p2_count'] or 0,
        'P3': stats['p3_count'] or 0,
        'P4': stats['p4_count'] or 0
    }
    
    cursor.execute("SELECT * FROM bugs ORDER BY created_date DESC LIMIT 10")
    recent_bugs = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('dashboard.html',
                         user=session['user'],
                         stats=stats,
                         priority_counts=priority_counts,
                         recent_bugs=recent_bugs)

# ========== TESTER DASHBOARD ==========
@app.route('/tester-dashboard')
def tester_dashboard():
    if 'user' not in session or session['user']['role'] != 'tester':
        return redirect(url_for('login'))
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT 
            COUNT(*) as bugs_found,
            SUM(CASE WHEN status = 'Verified' THEN 1 ELSE 0 END) as verified,
            SUM(CASE WHEN status NOT IN ('Verified', 'Closed') THEN 1 ELSE 0 END) as pending
        FROM bugs 
        WHERE reported_by = %s
    """, (session['user']['username'],))
    stats = cursor.fetchone()
    
    cursor.execute("""
        SELECT * FROM bugs 
        WHERE reported_by = %s 
        ORDER BY 
            CASE status 
                WHEN 'Fixed' THEN 1 
                WHEN 'Open' THEN 2 
                ELSE 3 
            END,
            created_date DESC
        LIMIT 10
    """, (session['user']['username'],))
    my_bugs = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('tester/dashboard.html',
                         user=session['user'],
                         stats=stats,
                         my_bugs=my_bugs)

# ========== DEVELOPER DASHBOARD ==========
@app.route('/developer-dashboard')
def developer_dashboard():
    if 'user' not in session or session['user']['role'] != 'developer':
        return redirect(url_for('login'))
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT 
            COUNT(*) as total_assigned,
            SUM(CASE WHEN status IN ('Closed', 'Verified') THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN status = 'In Progress' THEN 1 ELSE 0 END) as in_progress,
            AVG(resolution_time) as avg_resolution
        FROM bugs 
        WHERE assigned_to = %s
    """, (session['user']['username'],))
    stats = cursor.fetchone()
    
    cursor.execute("""
        SELECT * FROM bugs 
        WHERE assigned_to = %s 
        AND status NOT IN ('Closed', 'Verified')
        ORDER BY 
            CASE priority 
                WHEN 'P0' THEN 1 
                WHEN 'P1' THEN 2 
                WHEN 'P2' THEN 3 
                WHEN 'P3' THEN 4 
                WHEN 'P4' THEN 5 
            END,
            created_date DESC
    """, (session['user']['username'],))
    assigned_bugs = cursor.fetchall()
    
    cursor.execute("""
        SELECT * FROM bugs 
        WHERE assigned_to = %s 
        AND status IN ('Closed', 'Verified')
        ORDER BY closed_date DESC
        LIMIT 10
    """, (session['user']['username'],))
    completed_bugs = cursor.fetchall()
    
    cursor.execute("""
        SELECT component, COUNT(*) as count 
        FROM bugs 
        WHERE assigned_to = %s 
        AND status IN ('Closed', 'Verified')
        GROUP BY component 
        ORDER BY count DESC 
        LIMIT 3
    """, (session['user']['username'],))
    expertise = cursor.fetchall()
    
    suggested_bugs = []
    if expertise:
        components = [e['component'] for e in expertise]
        placeholders = ','.join(['%s'] * len(components))
        cursor.execute(f"""
            SELECT * FROM bugs 
            WHERE component IN ({placeholders})
            AND assigned_to IS NULL
            AND status = 'Open'
            ORDER BY 
                CASE priority 
                    WHEN 'P0' THEN 1 
                    WHEN 'P1' THEN 2 
                    ELSE 3 
                END,
                created_date DESC
            LIMIT 5
        """, components)
        suggested_bugs = cursor.fetchall()
        for bug in suggested_bugs:
            for exp in expertise:
                if exp['component'] == bug['component']:
                    bug['match_score'] = min(exp['count'] * 10, 95)
                    break
    
    cursor.execute("""
        SELECT bug_id, title, status, 
               CASE 
                   WHEN status = 'Closed' THEN closed_date
                   ELSE created_date
               END as activity_date
        FROM bugs 
        WHERE assigned_to = %s
        ORDER BY activity_date DESC
        LIMIT 5
    """, (session['user']['username'],))
    recent = cursor.fetchall()
    
    recent_activity = []
    for bug in recent:
        activity_type = 'fix' if bug['status'] in ['Closed', 'Verified'] else 'start'
        recent_activity.append({
            'text': f"Bug {bug['bug_id']}: {bug['title'][:50]}...",
            'time': 'Recently',
            'type': activity_type
        })
    
    cursor.close()
    conn.close()
    
    return render_template('developer/dashboard.html',
                         user=session['user'],
                         stats=stats,
                         assigned_bugs=assigned_bugs,
                         completed_bugs=completed_bugs,
                         suggested_bugs=suggested_bugs,
                         recent_activity=recent_activity)

@app.route('/update-bug-status', methods=['POST'])
def update_bug_status():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})
    
    data = request.json
    bug_id = data['bug_id']
    status = data['status']
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE bugs 
        SET status = %s
        WHERE bug_id = %s AND assigned_to = %s
    """, (status, bug_id, session['user']['username']))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/claim-bug', methods=['POST'])
def claim_bug():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})
    
    data = request.json
    bug_id = data['bug_id']
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE bugs 
        SET assigned_to = %s, status = 'In Progress'
        WHERE bug_id = %s AND assigned_to IS NULL
    """, (session['user']['username'], bug_id))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True})

# ========== ADMIN DASHBOARD ==========
@app.route('/admin-dashboard')
def admin_dashboard():
    if 'user' not in session or session['user']['role'] != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT COUNT(*) as total_users FROM users")
    total_users = cursor.fetchone()['total_users']
    
    cursor.execute("SELECT COUNT(*) as count FROM users WHERE role = 'admin'")
    admins = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM users WHERE role = 'manager'")
    managers = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM users WHERE role = 'developer'")
    developers = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM users WHERE role = 'tester'")
    testers = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as total_bugs FROM bugs")
    total_bugs = cursor.fetchone()['total_bugs']
    
    cursor.execute("SELECT COUNT(*) as open_bugs FROM bugs WHERE status = 'Open'")
    open_bugs = cursor.fetchone()['open_bugs']
    
    cursor.execute("SELECT COUNT(*) as fixed_bugs FROM bugs WHERE status = 'Fixed'")
    fixed_bugs = cursor.fetchone()['fixed_bugs']
    
    cursor.execute("SELECT COUNT(*) as verified_bugs FROM bugs WHERE status = 'Verified'")
    verified_bugs = cursor.fetchone()['verified_bugs']
    
    cursor.execute("SELECT username, full_name, email, role, created_at FROM users ORDER BY created_at DESC")
    users = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    stats = {
        'total_users': total_users,
        'admins': admins,
        'managers': managers,
        'developers': developers,
        'testers': testers,
        'total_bugs': total_bugs,
        'open_bugs': open_bugs,
        'fixed_bugs': fixed_bugs,
        'verified_bugs': verified_bugs
    }
    
    return render_template('admin/dashboard.html',
                         user=session['user'],
                         stats=stats,
                         users=users)

@app.route('/admin/add-user', methods=['POST'])
def add_user():
    if 'user' not in session or session['user']['role'] != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    data = request.json
    username = data['username']
    password = data['password']
    full_name = data['full_name']
    email = data['email']
    role = data['role']
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO users (username, password, full_name, email, role, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (username, generate_password_hash(password), full_name, email, role))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/delete-user', methods=['POST'])
def delete_user():
    if 'user' not in session or session['user']['role'] != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    data = request.json
    username = data['username']
    
    if username == session['user']['username']:
        return jsonify({'success': False, 'error': 'Cannot delete yourself'})
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM users WHERE username = %s", (username,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

# ========== ADMIN REPORT DOWNLOADS ==========
@app.route('/admin/download-report/<report_type>')
def download_report(report_type):
    if 'user' not in session or session['user']['role'] != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    import csv
    from io import StringIO
    from flask import Response
    
    if report_type == 'users':
        cursor.execute("SELECT username, full_name, email, role, created_at FROM users")
        data = cursor.fetchall()
        
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Username', 'Full Name', 'Email', 'Role', 'Created Date'])
        
        for row in data:
            writer.writerow([row['username'], row['full_name'], row['email'], 
                           row['role'], row['created_at'].strftime('%Y-%m-%d') if row['created_at'] else ''])
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=users_report_{datetime.now().strftime("%Y%m%d")}.csv'}
        )
    
    elif report_type == 'bugs':
        cursor.execute("""
            SELECT bug_id, title, severity, priority, component, status, 
                   reported_by, assigned_to, created_date, closed_date 
            FROM bugs 
            ORDER BY created_date DESC
        """)
        data = cursor.fetchall()
        
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Bug ID', 'Title', 'Severity', 'Priority', 'Component', 
                        'Status', 'Reported By', 'Assigned To', 'Created', 'Closed'])
        
        for row in data:
            writer.writerow([
                row['bug_id'], row['title'], row['severity'], row['priority'],
                row['component'], row['status'], row['reported_by'], row['assigned_to'],
                row['created_date'].strftime('%Y-%m-%d') if row['created_date'] else '',
                row['closed_date'].strftime('%Y-%m-%d') if row['closed_date'] else ''
            ])
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=bugs_report_{datetime.now().strftime("%Y%m%d")}.csv'}
        )
    
    elif report_type == 'performance':
        cursor.execute("""
            SELECT assigned_to, 
                   COUNT(*) as total_assigned,
                   SUM(CASE WHEN status IN ('Closed', 'Verified') THEN 1 ELSE 0 END) as completed,
                   AVG(resolution_time) as avg_resolution,
                   AVG(reopen_count) as avg_reopen
            FROM bugs 
            WHERE assigned_to IS NOT NULL
            GROUP BY assigned_to
        """)
        data = cursor.fetchall()
        
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Developer', 'Total Assigned', 'Completed', 'Avg Resolution (days)', 'Avg Reopen Rate'])
        
        for row in data:
            writer.writerow([
                row['assigned_to'], row['total_assigned'], row['completed'],
                round(row['avg_resolution'], 2) if row['avg_resolution'] else 0,
                round(row['avg_reopen'], 3) if row['avg_reopen'] else 0
            ])
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=performance_report_{datetime.now().strftime("%Y%m%d")}.csv'}
        )
    
    cursor.close()
    conn.close()
    return "Invalid report type", 404

# ========== MANAGER DASHBOARD ==========
@app.route('/manager-dashboard')
def manager_dashboard():
    if 'user' not in session or session['user']['role'] != 'manager':
        return redirect(url_for('login'))
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT 
            COUNT(*) as total_bugs,
            SUM(CASE WHEN severity = 'Critical' THEN 1 ELSE 0 END) as critical_bugs,
            SUM(CASE WHEN status = 'Open' THEN 1 ELSE 0 END) as open_bugs,
            AVG(resolution_time) as avg_resolution
        FROM bugs
    """)
    stats = cursor.fetchone()
    
    cursor.execute("""
        SELECT 
            assigned_to as name,
            COUNT(*) as assigned,
            SUM(CASE WHEN status IN ('Closed', 'Verified') THEN 1 ELSE 0 END) as completed,
            AVG(resolution_time) as avg_time,
            AVG(reopen_count) * 100 as reopen_rate
        FROM bugs 
        WHERE assigned_to IS NOT NULL
        GROUP BY assigned_to
    """)
    team = cursor.fetchall()
    
    cursor.execute("""
        SELECT priority, COUNT(*) as count
        FROM bugs
        GROUP BY priority
    """)
    priorities = cursor.fetchall()
    
    priority_stats = {
        'p0_count': 0, 'p1_count': 0, 'p2_count': 0, 'p3_count': 0, 'p4_count': 0,
        'p0_percent': 0, 'p1_percent': 0, 'p2_percent': 0, 'p3_percent': 0, 'p4_percent': 0
    }
    
    total = sum([p['count'] for p in priorities]) or 1
    
    for p in priorities:
        key = f"{p['priority'].lower()}_count"
        if key in priority_stats:
            priority_stats[key] = p['count']
            priority_stats[f"{p['priority'].lower()}_percent"] = round((p['count'] / total * 100), 1)
    
    cursor.execute("""
        SELECT * FROM bugs 
        WHERE severity IN ('Critical', 'High') 
        AND status != 'Closed'
        ORDER BY 
            CASE priority 
                WHEN 'P0' THEN 1 
                WHEN 'P1' THEN 2 
                ELSE 3 
            END,
            created_date DESC
        LIMIT 10
    """)
    critical_bugs = cursor.fetchall()
    
    cursor.execute("SELECT * FROM sprints WHERE status IN ('Planning', 'Active') ORDER BY created_at DESC")
    active_sprints = cursor.fetchall()
    
    sprint = {
        'name': 'Current Sprint',
        'start_date': 'Ongoing',
        'end_date': 'Ongoing',
        'progress': 0,
        'risk_level': 'LOW',
        'blockers': 0,
        'velocity': 0,
        'target_velocity': 15,
        'completion': 0,
        'recommendation': 'Start a new sprint to see risk analysis'
    }
    
    trend_data = {
        'weeks': ['Week 1', 'Week 2', 'Week 3', 'Week 4'],
        'critical': [5, 7, 4, 6],
        'high': [8, 10, 7, 9],
        'medium': [12, 15, 11, 14],
        'low': [10, 8, 12, 9]
    }
    
    cursor.close()
    conn.close()
    
    return render_template('manager/dashboard.html',
                         user=session['user'],
                         stats=stats,
                         team=team,
                         priority_stats=priority_stats,
                         critical_bugs=critical_bugs,
                         sprint=sprint,
                         trend_data=trend_data,
                         active_sprints=active_sprints)

# ========== SPRINT MANAGEMENT ==========
@app.route('/api/sprints')
def get_sprints():
    if 'user' not in session or session['user']['role'] != 'manager':
        return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM sprints ORDER BY created_at DESC")
    sprints = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(sprints)

@app.route('/manager/create-sprint', methods=['POST'])
def create_sprint():
    if 'user' not in session or session['user']['role'] != 'manager':
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.json
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as count FROM sprints")
    count = cursor.fetchone()[0] + 1
    sprint_id = f"SPRINT-{count:03d}"
    
    cursor.execute("""
        INSERT INTO sprints (sprint_id, name, goal, start_date, end_date, status, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        sprint_id,
        data['name'],
        data['goal'],
        data['start_date'],
        data['end_date'],
        'Planning',
        session['user']['username']
    ))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True, 'sprint_id': sprint_id})

@app.route('/manager/add-to-sprint', methods=['POST'])
def add_to_sprint():
    if 'user' not in session or session['user']['role'] != 'manager':
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.json
    sprint_id = data['sprint_id']
    bug_ids = data['bug_ids']
    
    conn = get_db()
    cursor = conn.cursor()
    
    for bug_id in bug_ids:
        cursor.execute("""
            INSERT IGNORE INTO sprint_bugs (sprint_id, bug_id, added_by)
            VALUES (%s, %s, %s)
        """, (sprint_id, bug_id, session['user']['username']))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True, 'added': len(bug_ids)})

@app.route('/manager/start-sprint/<sprint_id>', methods=['POST'])
def start_sprint(sprint_id):
    if 'user' not in session or session['user']['role'] != 'manager':
        return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM sprints WHERE sprint_id = %s", (sprint_id,))
    if not cursor.fetchone():
        return jsonify({'error': 'Sprint not found'}), 404
    
    cursor.execute("UPDATE sprints SET status = 'Active' WHERE sprint_id = %s", (sprint_id,))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/manager/complete-sprint/<sprint_id>', methods=['POST'])
def complete_sprint(sprint_id):
    if 'user' not in session or session['user']['role'] != 'manager':
        return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE sprints 
        SET status = 'Completed', completed_at = CURDATE()
        WHERE sprint_id = %s
    """, (sprint_id,))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/sprint/<sprint_id>')
def get_sprint_details(sprint_id):
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM sprints WHERE sprint_id = %s", (sprint_id,))
    sprint = cursor.fetchone()
    
    if sprint:
        cursor.execute("""
            SELECT b.* FROM bugs b
            JOIN sprint_bugs sb ON b.bug_id = sb.bug_id
            WHERE sb.sprint_id = %s
        """, (sprint_id,))
        sprint['bugs'] = cursor.fetchall()
        
        total_bugs = len(sprint['bugs'])
        completed = sum(1 for b in sprint['bugs'] if b['status'] in ['Closed', 'Verified'])
        sprint['progress'] = round((completed / total_bugs * 100) if total_bugs > 0 else 0)
        sprint['blockers'] = sum(1 for b in sprint['bugs'] if b['priority'] in ['P0', 'P1'] and b['status'] != 'Closed')
    
    cursor.close()
    conn.close()
    
    return jsonify(sprint)

@app.route('/api/sprint-risk/<sprint_id>')
def predict_sprint_risk(sprint_id):
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM sprints WHERE sprint_id = %s", (sprint_id,))
    sprint = cursor.fetchone()
    
    if not sprint:
        return jsonify({'error': 'Sprint not found'}), 404
    
    cursor.execute("""
        SELECT b.* FROM bugs b
        JOIN sprint_bugs sb ON b.bug_id = sb.bug_id
        WHERE sb.sprint_id = %s
    """, (sprint_id,))
    bugs = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    total_bugs = len(bugs)
    critical_count = sum(1 for b in bugs if b['severity'] == 'Critical')
    p0_count = sum(1 for b in bugs if b['priority'] == 'P0')
    p1_count = sum(1 for b in bugs if b['priority'] == 'P1')
    
    from datetime import datetime
    today = datetime.now().date()
    days_left = (sprint['end_date'] - today).days if sprint['end_date'] else 0
    
    risk_score = 0
    if p0_count > 3:
        risk_score += 40
    if critical_count > 5:
        risk_score += 30
    if days_left < 3 and total_bugs > 10:
        risk_score += 30
    
    if risk_score >= 70:
        risk_level = "HIGH"
        recommendation = "Immediate action needed! Consider descoping features or adding resources."
    elif risk_score >= 40:
        risk_level = "MEDIUM"
        recommendation = "Monitor closely. Focus on P0/P1 bugs first."
    else:
        risk_level = "LOW"
        recommendation = "On track. Keep up the good work!"
    
    return jsonify({
        'sprint_id': sprint_id,
        'risk_level': risk_level,
        'risk_score': risk_score,
        'recommendation': recommendation,
        'metrics': {
            'total_bugs': total_bugs,
            'critical': critical_count,
            'p0': p0_count,
            'p1': p1_count,
            'days_left': days_left,
            'completion': sprint['progress'] if 'progress' in sprint else 0
        }
    })

@app.route('/manager/sprint-risk')
def sprint_risk_view():
    if 'user' not in session or session['user']['role'] != 'manager':
        return redirect(url_for('login'))
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM sprints WHERE status = 'Active' LIMIT 1")
    current_sprint = cursor.fetchone()
    
    risk_data = {}
    if current_sprint:
        cursor.execute("""
            SELECT b.* FROM bugs b
            JOIN sprint_bugs sb ON b.bug_id = sb.bug_id
            WHERE sb.sprint_id = %s
        """, (current_sprint['sprint_id'],))
        bugs = cursor.fetchall()
        
        total_bugs = len(bugs)
        critical_count = sum(1 for b in bugs if b['severity'] == 'Critical')
        p0_count = sum(1 for b in bugs if b['priority'] == 'P0')
        p1_count = sum(1 for b in bugs if b['priority'] == 'P1')
        completed = sum(1 for b in bugs if b['status'] in ['Closed', 'Verified'])
        progress = round((completed / total_bugs * 100) if total_bugs > 0 else 0)
        
        from datetime import datetime
        today = datetime.now().date()
        days_left = (current_sprint['end_date'] - today).days if current_sprint['end_date'] else 0
        
        risk_score = 0
        if p0_count > 3:
            risk_score += 40
        if critical_count > 5:
            risk_score += 30
        if days_left < 3 and total_bugs > 10:
            risk_score += 30
        
        if risk_score >= 70:
            risk_level = "HIGH"
            recommendation = "Immediate action needed! Consider descoping features or adding resources."
        elif risk_score >= 40:
            risk_level = "MEDIUM"
            recommendation = "Monitor closely. Focus on P0/P1 bugs first."
        else:
            risk_level = "LOW"
            recommendation = "On track. Keep up the good work!"
        
        risk_data = {
            'risk_level': risk_level,
            'risk_score': risk_score,
            'recommendation': recommendation,
            'metrics': {
                'total_bugs': total_bugs,
                'critical': critical_count,
                'p0': p0_count,
                'p1': p1_count,
                'days_left': days_left,
                'progress': progress,
                'completed': completed
            }
        }
    
    cursor.close()
    conn.close()
    
    return render_template('manager/sprint_risk.html', 
                         user=session['user'],
                         sprint=current_sprint,
                         risk=risk_data)

# ========== SHARED ROUTES ==========
@app.route('/report-bug', methods=['GET', 'POST'])
def report_bug():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        component = request.form['component']
        
        severity, priority = predict_bug(title, description, component)
        
        # AI triage: duplicates, similar fixes, best developer
        advice = {}
        try:
            advice = get_advisor().advise(title, description, component)
        except Exception as e:
            print(f"AI advice error: {e}")
        auto_assign = request.form.get('auto_assign') == 'on'
        assignee = None
        status = 'Open'
        if auto_assign and advice.get('recommended_developers'):
            assignee = advice['recommended_developers'][0]['developer']
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT MAX(CAST(SUBSTRING(bug_id, 5) AS UNSIGNED)) as max_id FROM bugs")
        result = cursor.fetchone()
        next_id = (result[0] or 0) + 1
        bug_id = f"BUG-{next_id:04d}"
        
        cursor.execute("""
            INSERT INTO bugs 
            (bug_id, title, description, severity, priority, component, 
             reported_by, created_date, status, assigned_to, ai_confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            bug_id, title, description, severity, priority, component,
            session['user']['username'], datetime.now().strftime('%Y-%m-%d'), status,
            assignee, advice.get('confidence')
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        invalidate_ai_cache()
        
        return render_template('shared/report_bug.html',
                             user=session['user'],
                             title=title,
                             description=description,
                             component=component,
                             severity=severity,
                             priority=priority,
                             saved=True,
                             bug_id=bug_id,
                             assignee=assignee,
                             advice=advice)
    
    return render_template('shared/report_bug.html', user=session['user'])

@app.route('/bugs')
def bugs():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    reporter_filter = request.args.get('reporter', '')
    severity_filter = request.args.get('severity', '')
    priority_filter = request.args.get('priority', '')
    
    where, params = [], []
    if reporter_filter:
        where.append("reported_by = %s")
        params.append(reporter_filter)
    elif session['user']['role'] not in ('manager', 'admin'):
        where.append("(reported_by = %s OR assigned_to = %s)")
        params += [session['user']['username']] * 2
    if severity_filter:
        where.append("severity = %s")
        params.append(severity_filter)
    if priority_filter:
        where.append("priority = %s")
        params.append(priority_filter)
    sql = "SELECT * FROM bugs" + (" WHERE " + " AND ".join(where) if where else "") \
          + " ORDER BY created_date DESC"
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(sql, params)
    bugs_list = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('shared/bugs.html',
                         user=session['user'],
                         bugs=bugs_list,
                         severity_filter=severity_filter,
                         priority_filter=priority_filter)

@app.route('/predict-api', methods=['POST'])
def predict_api():
    data = request.json
    severity, priority = predict_bug(data['title'], data['description'], data['component'])
    return jsonify({'severity': severity, 'priority': priority})

@app.route('/suggest-developers', methods=['POST'])
def suggest_developers_api():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})
    data = request.json or {}
    try:
        advice = get_advisor().advise(data.get('title', ''), data.get('description', ''),
                                      data.get('component'))
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    suggestions = [{'developer': d['developer'], 'score': d['score'], 'reasons': d['reasons']}
                   for d in advice['recommended_developers']]
    return jsonify({'success': True, 'suggestions': suggestions})


# ========== AI RESOLUTION ENDPOINTS ==========
@app.route('/api/ai-advice', methods=['POST'])
def ai_advice():
    """Live triage panel on the report form: duplicates, similar bugs, fixes, ETA, developers."""
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    data = request.json or {}
    if not data.get('title'):
        return jsonify({'success': False, 'error': 'title required'}), 400
    try:
        advice = get_advisor().advise(data['title'], data.get('description', ''),
                                      data.get('component'))
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, **advice})


@app.route('/bug/<bug_id>')
def bug_detail(bug_id):
    if 'user' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM bugs WHERE bug_id = %s", (bug_id,))
    bug = cursor.fetchone()
    cursor.close()
    conn.close()
    if not bug:
        return "Bug not found", 404
    advice = get_advisor().advise(bug['title'], bug['description'] or '',
                                  bug['component'], exclude_id=bug_id)
    return render_template('shared/bug_detail.html', user=session['user'], bug=bug,
                           advice=advice, llm_available=llm_planner.available)


@app.route('/api/bug/<bug_id>/fix-plan', methods=['POST'])
def bug_fix_plan(bug_id):
    """LLM-drafted root-cause hypotheses + fix/test plan (needs ANTHROPIC_API_KEY)."""
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    if not llm_planner.available:
        return jsonify({'success': False,
                        'error': 'LLM planner disabled. Set ANTHROPIC_API_KEY and install `anthropic`.'}), 503
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM bugs WHERE bug_id = %s", (bug_id,))
    bug = cursor.fetchone()
    cursor.close()
    conn.close()
    if not bug:
        return jsonify({'success': False, 'error': 'Bug not found'}), 404
    advice = get_advisor().advise(bug['title'], bug['description'] or '', bug['component'],
                                  exclude_id=bug_id)
    plan = llm_planner.plan(bug, advice['similar_bugs'])
    if not plan:
        return jsonify({'success': False, 'error': 'Could not generate a plan'}), 502
    return jsonify({'success': True, 'plan': plan})


@app.route('/api/bug/<bug_id>/auto-assign', methods=['POST'])
def auto_assign(bug_id):
    """Assign an unassigned bug to the AI's top-ranked developer (manager/admin only)."""
    if 'user' not in session or session['user']['role'] not in ('manager', 'admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM bugs WHERE bug_id = %s", (bug_id,))
    bug = cursor.fetchone()
    if not bug:
        cursor.close(); conn.close()
        return jsonify({'success': False, 'error': 'Bug not found'}), 404
    advice = get_advisor(force=True).advise(bug['title'], bug['description'] or '',
                                            bug['component'], exclude_id=bug_id)
    if not advice['recommended_developers']:
        cursor.close(); conn.close()
        return jsonify({'success': False, 'error': 'No developers available'})
    dev = advice['recommended_developers'][0]['developer']
    cursor.execute("UPDATE bugs SET assigned_to = %s, status = 'In Progress' "
                   "WHERE bug_id = %s AND assigned_to IS NULL", (dev, bug_id))
    changed = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    invalidate_ai_cache()
    if not changed:
        return jsonify({'success': False, 'error': 'Bug is already assigned'})
    return jsonify({'success': True, 'assigned_to': dev})


@app.route('/api/bug/<bug_id>/resolve', methods=['POST'])
def resolve_bug(bug_id):
    """Developer closes a bug AND records how it was fixed. These notes are what the
    knowledge base learns from, so every fix makes the next suggestion better."""
    if 'user' not in session or session['user']['role'] not in ('developer', 'manager', 'admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    data = request.json or {}
    notes = (data.get('resolution_notes') or '').strip()
    if len(notes) < 10:
        return jsonify({'success': False,
                        'error': 'Please describe the fix (at least 10 characters).'}), 400
    conn = get_db()
    cursor = conn.cursor()
    sql = """UPDATE bugs SET status = 'Fixed', resolution_notes = %s, closed_date = CURDATE(),
                    resolution_time = DATEDIFF(CURDATE(), created_date)
             WHERE bug_id = %s"""
    params = [notes, bug_id]
    if session['user']['role'] == 'developer':
        sql += " AND assigned_to = %s"
        params.append(session['user']['username'])
    cursor.execute(sql, params)
    changed = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    if not changed:
        return jsonify({'success': False, 'error': 'Bug not found or not assigned to you'}), 404
    invalidate_ai_cache()
    return jsonify({'success': True})


@app.route('/api/bug/<bug_id>/mark-duplicate', methods=['POST'])
def mark_duplicate(bug_id):
    if 'user' not in session or session['user']['role'] not in ('manager', 'admin', 'developer'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    original = (request.json or {}).get('duplicate_of', '').strip()
    if not original or original == bug_id:
        return jsonify({'success': False, 'error': 'Invalid original bug id'}), 400
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM bugs WHERE bug_id = %s", (original,))
    if not cursor.fetchone():
        cursor.close(); conn.close()
        return jsonify({'success': False, 'error': 'Original bug not found'}), 404
    cursor.execute("UPDATE bugs SET duplicate_of = %s, status = 'Closed', closed_date = CURDATE(), "
                   "resolution_notes = %s WHERE bug_id = %s",
                   (original, f"Duplicate of {original}", bug_id))
    conn.commit()
    cursor.close()
    conn.close()
    invalidate_ai_cache()
    return jsonify({'success': True})


@app.route('/verify-bug', methods=['POST'])
def verify_bug():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})
    
    data = request.json
    bug_id = data['bug_id']
    result = data['result']
    
    conn = get_db()
    cursor = conn.cursor()
    
    if result == 'pass':
        cursor.execute("""
            UPDATE bugs 
            SET status = 'Verified', closed_date = %s 
            WHERE bug_id = %s
        """, (datetime.now().strftime('%Y-%m-%d'), bug_id))
    else:
        cursor.execute("""
            UPDATE bugs 
            SET status = 'Reopened', reopen_count = reopen_count + 1 
            WHERE bug_id = %s
        """, (bug_id,))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_DEBUG', '0') == '1')