-- =====================================================
-- AI-Driven Bug Tracking & Developer Productivity System
-- MySQL Schema
-- =====================================================

CREATE DATABASE IF NOT EXISTS bugtracker;
USE bugtracker;

-- ---------- USERS ----------
CREATE TABLE IF NOT EXISTS users (
    user_id      INT AUTO_INCREMENT PRIMARY KEY,
    username     VARCHAR(50)  NOT NULL UNIQUE,
    password     VARCHAR(255) NOT NULL,          -- store BCrypt hash, not plain text
    full_name    VARCHAR(100) NOT NULL,
    email        VARCHAR(100),
    role         ENUM('admin','manager','developer','tester') NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------- BUGS ----------
CREATE TABLE IF NOT EXISTS bugs (
    bug_id          VARCHAR(20) PRIMARY KEY,          -- e.g. BUG-0001
    title           VARCHAR(255) NOT NULL,
    description     TEXT NOT NULL,
    severity        ENUM('Critical','High','Medium','Low') DEFAULT 'Medium',
    priority        ENUM('P0','P1','P2','P3') DEFAULT 'P2',
    component       VARCHAR(100),
    assigned_to     VARCHAR(50),
    reported_by     VARCHAR(50) NOT NULL,
    created_date    DATE NOT NULL,
    closed_date     DATE NULL,
    status          ENUM('Open','In Progress','Fixed','Verified','Closed','Reopened') DEFAULT 'Open',
    resolution_time FLOAT NULL,                       -- in days, filled when closed
    reopen_count    INT DEFAULT 0,
    FOREIGN KEY (reported_by) REFERENCES users(username),
    FOREIGN KEY (assigned_to) REFERENCES users(username)
);

-- ---------- SPRINTS ----------
CREATE TABLE IF NOT EXISTS sprints (
    sprint_id   INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    start_date  DATE NOT NULL,
    end_date    DATE NOT NULL,
    status      ENUM('Planned','Active','Completed') DEFAULT 'Planned',
    progress    INT DEFAULT 0
);

-- ---------- SPRINT <-> BUG mapping ----------
CREATE TABLE IF NOT EXISTS sprint_bugs (
    sprint_id  INT NOT NULL,
    bug_id     VARCHAR(20) NOT NULL,
    PRIMARY KEY (sprint_id, bug_id),
    FOREIGN KEY (sprint_id) REFERENCES sprints(sprint_id),
    FOREIGN KEY (bug_id) REFERENCES bugs(bug_id)
);

CREATE INDEX idx_bugs_status ON bugs(status);
CREATE INDEX idx_bugs_severity ON bugs(severity);
CREATE INDEX idx_bugs_assigned ON bugs(assigned_to);
