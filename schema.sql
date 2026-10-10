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
