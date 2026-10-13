-- Optional: a developer to log in with on the portal's "Developer" side.
-- assigned_urls = the websites this developer sees bugs for (matched by site origin).
USE bugtracker;
INSERT IGNORE INTO tracker_developers (name, email, assigned_urls)
VALUES ('Test Developer', 'githubtest@gmail.com', '["https://github.com/"]');
