USE bugtracker;

-- Passwords below are BCrypt hashes of 'password123' -- replace via the app's
-- registration flow in production. Generate real hashes with Spring Security's
-- BCryptPasswordEncoder before going live.
INSERT INTO users (username, password, full_name, email, role) VALUES
('admin1',   '$2a$10$replace_with_real_bcrypt_hash', 'System Admin',  'admin@bugtracker.com',   'admin'),
('mgr_ravi', '$2a$10$replace_with_real_bcrypt_hash', 'Ravi Kumar',    'ravi@bugtracker.com',    'manager'),
('dev_alice','$2a$10$replace_with_real_bcrypt_hash', 'Alice Dev',     'alice@bugtracker.com',   'developer'),
('dev_bob',  '$2a$10$replace_with_real_bcrypt_hash', 'Bob Dev',       'bob@bugtracker.com',     'developer'),
('qa_sarah', '$2a$10$replace_with_real_bcrypt_hash', 'Sarah Tester',  'sarah@bugtracker.com',   'tester');
