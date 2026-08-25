-- Run this on an existing CampusHub database if you do NOT want to delete existing data.
USE campushub;

ALTER TABLE users MODIFY role ENUM('student','teacher','admin') NOT NULL DEFAULT 'student';

CREATE TABLE IF NOT EXISTS student_messages(
 id INT AUTO_INCREMENT PRIMARY KEY,sender_id INT NOT NULL,receiver_id INT NOT NULL,message TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE);

CREATE TABLE IF NOT EXISTS staff_messages(
 id INT AUTO_INCREMENT PRIMARY KEY,sender_id INT NOT NULL,receiver_id INT NOT NULL,message TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE);

INSERT IGNORE INTO years(name) VALUES('HND Year 1'),('HND Year 2'),('HND Year 3');



-- Teacher-student communication requires an administrator-approved request.
CREATE TABLE IF NOT EXISTS teacher_requests(
 id INT AUTO_INCREMENT PRIMARY KEY,
 student_id INT NOT NULL,
 teacher_id INT NOT NULL,
 status ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
 approved_by INT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 decided_at TIMESTAMP NULL,
 UNIQUE KEY unique_active_request(student_id,teacher_id,status),
 FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(teacher_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS teacher_student_messages(
 id INT AUTO_INCREMENT PRIMARY KEY,
 request_id INT NOT NULL,
 sender_id INT NOT NULL,
 receiver_id INT NOT NULL,
 message TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(request_id) REFERENCES teacher_requests(id) ON DELETE CASCADE,
 FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Student group community and private student-to-student chats.
CREATE TABLE IF NOT EXISTS student_messages(
 id INT AUTO_INCREMENT PRIMARY KEY,
 sender_id INT NOT NULL,
 receiver_id INT NOT NULL,
 message TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS community_posts(
 id INT AUTO_INCREMENT PRIMARY KEY,
 user_id INT NOT NULL,
 content TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS community_comments(
 id INT AUTO_INCREMENT PRIMARY KEY,
 post_id INT NOT NULL,
 user_id INT NOT NULL,
 content TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(post_id) REFERENCES community_posts(id) ON DELETE CASCADE,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
INSERT IGNORE INTO years(name) VALUES('HND Year 1'),('HND Year 2'),('HND Year 3');

-- CampusHub fixes: profile pictures and online status
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar VARCHAR(255) NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP;
CREATE TABLE IF NOT EXISTS student_online_sessions(
 id INT AUTO_INCREMENT PRIMARY KEY,
 user_id INT NOT NULL,
 last_ping TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
