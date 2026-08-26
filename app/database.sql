CREATE DATABASE IF NOT EXISTS campushub;
USE campushub;

CREATE TABLE IF NOT EXISTS specialties(id INT AUTO_INCREMENT PRIMARY KEY,name VARCHAR(100) UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS years(id INT AUTO_INCREMENT PRIMARY KEY,name VARCHAR(50) UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS users(
 id INT AUTO_INCREMENT PRIMARY KEY, full_name VARCHAR(120) NOT NULL,
 email VARCHAR(150) UNIQUE NOT NULL,password VARCHAR(255) NOT NULL,
 role ENUM('student','teacher','admin') NOT NULL DEFAULT 'student',
 specialty_id INT NULL,year_id INT NULL,is_banned BOOLEAN NOT NULL DEFAULT FALSE,is_suspended BOOLEAN NOT NULL DEFAULT FALSE,last_seen TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(specialty_id) REFERENCES specialties(id) ON DELETE SET NULL,
 FOREIGN KEY(year_id) REFERENCES years(id) ON DELETE SET NULL);
CREATE TABLE IF NOT EXISTS courses(id INT AUTO_INCREMENT PRIMARY KEY,code VARCHAR(30),name VARCHAR(150) NOT NULL);
CREATE TABLE IF NOT EXISTS announcements(
 id INT AUTO_INCREMENT PRIMARY KEY,title VARCHAR(200) NOT NULL,content TEXT NOT NULL,
 specialty_id INT NULL,year_id INT NULL,image_filename VARCHAR(255),created_by INT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(specialty_id) REFERENCES specialties(id) ON DELETE SET NULL,
 FOREIGN KEY(year_id) REFERENCES years(id) ON DELETE SET NULL,
 FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL);
CREATE TABLE IF NOT EXISTS timetables(
 id INT AUTO_INCREMENT PRIMARY KEY,title VARCHAR(200) NOT NULL,specialty_id INT NOT NULL,
 year_id INT NOT NULL,pdf_filename VARCHAR(255) NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(specialty_id) REFERENCES specialties(id) ON DELETE CASCADE,
 FOREIGN KEY(year_id) REFERENCES years(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS past_papers(
 id INT AUTO_INCREMENT PRIMARY KEY,title VARCHAR(200) NOT NULL,course_id INT NULL,
 specialty_id INT NULL,year_id INT NULL,academic_year VARCHAR(30),
 filename VARCHAR(255) NOT NULL,file_type VARCHAR(20) NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE SET NULL,
 FOREIGN KEY(specialty_id) REFERENCES specialties(id) ON DELETE SET NULL,
 FOREIGN KEY(year_id) REFERENCES years(id) ON DELETE SET NULL);
CREATE TABLE IF NOT EXISTS hall_distribution(
 id INT AUTO_INCREMENT PRIMARY KEY,title VARCHAR(200) NOT NULL,specialty_id INT NULL,
 year_id INT NULL,course_id INT NULL,hall VARCHAR(100) NOT NULL,distribution_date DATE,
 FOREIGN KEY(specialty_id) REFERENCES specialties(id) ON DELETE SET NULL,
 FOREIGN KEY(year_id) REFERENCES years(id) ON DELETE SET NULL,
 FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE SET NULL);
CREATE TABLE IF NOT EXISTS results(
 id INT AUTO_INCREMENT PRIMARY KEY,student_id INT NOT NULL,course_id INT NULL,score DECIMAL(5,2),
 grade VARCHAR(10),semester VARCHAR(50),academic_year VARCHAR(30),pdf_filename VARCHAR(255),
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE SET NULL);
CREATE TABLE IF NOT EXISTS messages(
 id INT AUTO_INCREMENT PRIMARY KEY,sender_id INT NULL,student_id INT NOT NULL,subject VARCHAR(200) NOT NULL,
 message TEXT NOT NULL,attachment_filename VARCHAR(255),attachment_type VARCHAR(30),
 is_read BOOLEAN DEFAULT FALSE,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE SET NULL,
 FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE);
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
CREATE TABLE IF NOT EXISTS about_us(id INT PRIMARY KEY,title VARCHAR(200) NOT NULL,content TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contact_us(id INT PRIMARY KEY,email VARCHAR(150),phone VARCHAR(80),address VARCHAR(255),content TEXT);
CREATE TABLE IF NOT EXISTS site_settings(id INT PRIMARY KEY,app_name VARCHAR(150) NOT NULL,app_title VARCHAR(255),language VARCHAR(5) DEFAULT 'en');

-- Existing databases may have the old student/admin-only enum.
ALTER TABLE users MODIFY role ENUM('student','teacher','admin') NOT NULL DEFAULT 'student';

INSERT IGNORE INTO specialties(name) VALUES('Software Engineering'),('Network'),('Maintenance');
INSERT IGNORE INTO years(name) VALUES('HND Year 1'),('HND Year 2'),('HND Year 3');
INSERT IGNORE INTO about_us VALUES(1,'About CampusHub','CampusHub centralises announcements, timetables, past papers, results and campus information.');
INSERT IGNORE INTO contact_us VALUES(1,'admin@example.com','','','Contact the CampusHub administration.');
INSERT IGNORE INTO site_settings VALUES(1,'CampusHub','Campus Information Management System','en');



-- Teacher-student communication requires an administrator-approved request.
CREATE TABLE IF NOT EXISTS teacher_requests(
 id INT AUTO_INCREMENT PRIMARY KEY,
 student_id INT NOT NULL,
 teacher_id INT NOT NULL,
 status ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
 approved_by INT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 decided_at TIMESTAMP NULL,
 teacher_response TEXT NULL,
 UNIQUE KEY unique_active_request(student_id,teacher_id,status),
 FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(teacher_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS teacher_notes(
 id INT AUTO_INCREMENT PRIMARY KEY,title VARCHAR(200) NOT NULL,description TEXT,
 filename VARCHAR(255) NOT NULL,file_type VARCHAR(20) NOT NULL,created_by INT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS issue_reports(
 id INT AUTO_INCREMENT PRIMARY KEY,reporter_id INT NOT NULL,subject VARCHAR(200) NOT NULL,message TEXT NOT NULL,
 status ENUM('open','resolved') NOT NULL DEFAULT 'open',admin_reply TEXT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,resolved_at TIMESTAMP NULL,
 FOREIGN KEY(reporter_id) REFERENCES users(id) ON DELETE CASCADE
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
