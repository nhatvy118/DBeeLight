# Case Study 6: School / Education — Test Prompts (20 operations)

Schema: `instructors`, `students`, `courses`, `enrollments`, `grades`.
Setup: run `schema.sql` first, then import `seed_data/*.xlsx` with **append to existing table** mode, in this order: `instructors`, `students`, `courses`, `enrollments`, `grades`.
Route split: 6 `db_readonly` / 3 `db_general` / 6 `chart` / 3 `db_mutation` / 2 `db_create_table` — this domain places extra weight on chart operations (Section 8.2).

## db_readonly (6)

1. List all students sorted by enrollment year.
2. Find all courses with more than 3 credits.
3. Get all instructors in the Computer Science department.
4. Find all enrollments for semester "2026-Spring".
5. Get a list of courses along with their instructor's name.
6. Count how many students are enrolled in each course.

## db_general (3 — schema explanation / multi-step analysis)

7. Describe the `grades` table — how many columns does it have, and what does `max_score` represent?
8. What's the trend in average grades across semesters — are outcomes improving or declining?
9. Compare average student performance between the 2025-Fall and 2026-Spring semesters — which semester had better outcomes?

## chart (6)

10. Show a bar chart of average grade per course.
11. Show a pie chart of students by enrollment year.
12. Show a bar chart of number of students per instructor.
13. Show a line chart of number of enrollments per semester.
14. Show a bar chart of the top 10 students by average score across all assignments.
15. Show a pie chart of grade distribution for a specific course.

## db_mutation (3)

16. Update the score of grade record ID 20 to 95.
17. Change the credits of course "Statistics" from 3 to 4.
18. Update the enrollment year of student ID 5 to 2024.

## db_create_table (2)

19. Create a table called `classrooms` with an auto-increment primary key `id`, a required `room_number` varchar(20), a `building` varchar(50), and a `capacity` integer.
20. Create a table called `course_attendance` with an auto-increment primary key `id`, `enrollment_id` referencing `enrollments(id)`, a `session_date` date, and a `present` boolean defaulting to true.
