CREATE DATABASE IF NOT EXISTS bugtracker;
USE bugtracker;

CREATE TABLE IF NOT EXISTS users (
    username   VARCHAR(50) PRIMARY KEY,
    password   VARCHAR(255) NOT NULL,          -- werkzeug hash, never plaintext
    full_name  VARCHAR(100),
    email      VARCHAR(120),
    role       ENUM('admin','manager','developer','tester') NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bugs (
    bug_id           VARCHAR(20) PRIMARY KEY,
    title            VARCHAR(255) NOT NULL,
    description      TEXT,
    severity         VARCHAR(20),
    priority         VARCHAR(5),
    component        VARCHAR(50),
    assigned_to      VARCHAR(50) NULL,
    reporter         VARCHAR(50) NULL,
    reported_by      VARCHAR(50) NULL,
    created_date     DATE,
    closed_date      DATE NULL,
    status           VARCHAR(20) DEFAULT 'Open',
    resolution_time  FLOAT NULL,
    reopen_count     INT DEFAULT 0,
    -- new: AI resolution fields
    resolution_notes TEXT NULL,               -- what actually fixed it (feeds the knowledge base)
    duplicate_of     VARCHAR(20) NULL,
    ai_confidence    FLOAT NULL,              -- confidence of the AI advice shown at triage
    INDEX idx_status (status),
    INDEX idx_component (component),
    INDEX idx_assigned (assigned_to)
);

CREATE TABLE IF NOT EXISTS sprints (
    sprint_id    VARCHAR(20) PRIMARY KEY,
    name         VARCHAR(100),
    goal         TEXT,
    start_date   DATE,
    end_date     DATE,
    status       VARCHAR(20) DEFAULT 'Planning',
    created_by   VARCHAR(50),
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATE NULL
);

CREATE TABLE IF NOT EXISTS sprint_bugs (
    sprint_id VARCHAR(20),
    bug_id    VARCHAR(20),
    added_by  VARCHAR(50),
    PRIMARY KEY (sprint_id, bug_id)
);

-- Tables used by the Next.js tester/developer portal (tracker_api.py also creates these automatically)
CREATE TABLE IF NOT EXISTS tracker_developers (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(255),
    email         VARCHAR(255) NOT NULL UNIQUE,
    assigned_urls TEXT,                        -- JSON list of site URLs this developer handles
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS tracker_bugs (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    test_url    VARCHAR(1024),
    category    VARCHAR(64) NOT NULL DEFAULT 'General Bug',
    title       VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    summary     TEXT,
    tags        TEXT,
    severity    VARCHAR(16) NOT NULL DEFAULT 'Medium',
    status      VARCHAR(16) NOT NULL DEFAULT 'Open',
    reports     INT NOT NULL DEFAULT 1,
    reporters   TEXT,
    screenshot  VARCHAR(255),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_tracker_bugs_url (test_url(191))
) CHARACTER SET utf8mb4;

-- BugSight AI module (Random Forest severity + Claude recommendations); also auto-created at startup
CREATE TABLE IF NOT EXISTS bugsight_reports (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    title               VARCHAR(255) NOT NULL,
    description         TEXT,
    bug_type            VARCHAR(20),
    component           VARCHAR(50),
    environment         VARCHAR(20),
    affected_users      INT,
    frequency_per_day   INT,
    time_to_reproduce   VARCHAR(20),
    workaround          VARCHAR(10),
    error_rate_spike    VARCHAR(10),
    stack_depth         INT,
    days_since_reported INT,
    predicted_severity  VARCHAR(20),
    confidence          FLOAT,
    risk_score          FLOAT,
    probabilities       TEXT,
    status              VARCHAR(20) DEFAULT 'Open',
    confirmed_severity  VARCHAR(20) NULL,   -- set by developers; used when retraining the forest
    reporter            VARCHAR(50),
    assigned_to         VARCHAR(50) NULL,
    source              VARCHAR(10) DEFAULT 'manual',
    recommendations     TEXT,               -- cached Claude output, JSON keyed by role
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME NULL,
    INDEX idx_bs_status (status),
    INDEX idx_bs_reporter (reporter)
) CHARACTER SET utf8mb4;
