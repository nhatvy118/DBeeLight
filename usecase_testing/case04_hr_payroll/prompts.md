# Case Study 4: HR & Payroll — Test Prompts (50 operations)

Schema: `departments`, `positions`, `employees`, `attendance`, `payroll`.
Setup: run `schema.sql` first, then import `seed_data/*.xlsx` with **append to existing table** mode, in this order: `departments`, `positions`, `employees`, `attendance`, `payroll`.

Prompt distribution (Table 7.3): 15 Basic analytical queries / 12 Advanced analytical queries / 8 Database analysis / 5 Data visualization / 5 Database modification / 2 Table creation / 3 Representative edge cases.

Legend: **[CŨ]** = prompt có sẵn từ trước (20 prompt gốc, giữ nguyên nội dung) · **[MỚI]** = prompt vừa thêm để đủ 50/domain · **⚠️** = prompt có khả năng gây lỗi trong đánh giá (xem Table 7.6/7.7).

## 1. Basic Analytical Queries (15)

1. [CŨ] List all employees sorted by salary, highest first.
2. [CŨ] Find all employees in the "Engineering" department.
3. [CŨ] Get the top 5 highest-paid employees.
4. [CŨ] Find all employees hired after 2023.
5. [CŨ] Get a list of employees along with their department name and position title.
6. [CŨ] Show each department along with the number of employees in it.
7. [CŨ] Find all employees who were marked absent in the attendance log.
8. [CŨ] Get each employee's reporting manager's name.
9. [MỚI] Find all employees in the "Marketing" department.
10. [MỚI] List all positions sorted by level.
11. [MỚI] Find all attendance records marked "late" for a specific date.
12. [MỚI] Get all employees hired in 2022.
13. [MỚI] Show all payroll records for period "2026-05".
14. [MỚI] Find all departments located in "Ho Chi Minh City".
15. [MỚI] Count the total number of employees in the company.

## 2. Advanced Analytical Queries (12)

1. [MỚI] Find employees who have never had a payroll record generated.
2. [MỚI] Find departments with no employees assigned.
3. [MỚI] For each department, show total headcount and rank departments from largest to smallest.
4. [MỚI] Find the top 3 positions by average salary.
5. [MỚI] Show each employee along with their total bonus received across all payroll periods, sorted descending.
6. [MỚI] Find employees whose salary exceeds the average salary of their own department.
7. [MỚI] For each hire year, show the running cumulative headcount of employees hired up to and including that year.
8. [MỚI] Find the manager with the largest number of direct reports.
9. [MỚI] Show each position level along with the percentage of total headcount it accounts for.
10. [MỚI] Find employees whose attendance includes more "late" days than "present" days in a given month.
11. [MỚI] For each employee, find their most recent payroll record.
12. [MỚI] Find the single longest management chain from a top-level employee down to a leaf. Report the chain length (number of employees on the path) and the sum of their salary values. If several chains share the maximum length, keep the one whose leaf employee has the smallest id.

## 3. Database Analysis (8)

1. [CŨ] Describe the `employees` table — how many columns does it have, and what does `manager_id` represent?
2. [CŨ] What does the `level` column in `positions` mean?
3. [CŨ] What's the salary trend across departments — which department pays the highest average salary, and why might that be?
4. [CŨ] Compare payroll cost between departments for period 2026-06 — which department has the highest total net pay?
5. [MỚI] Describe the `attendance` table and explain what the `status` column can represent.
6. [MỚI] What's the relationship between `employees` and `positions`, and how does `manager_id` create a reporting hierarchy?
7. [MỚI] Analyze headcount growth — how many employees were hired in each of the last 3 years?
8. [MỚI] Which department has the highest ratio of senior/lead positions to junior positions, and what might that imply about its structure?

## 4. Data Visualization (5)

1. [CŨ] Show a bar chart of average salary by department.
2. [CŨ] Show a pie chart of employees by position level.
3. [CŨ] Show a bar chart of number of employees per department.
4. [CŨ] Show a line chart of total net pay by payroll period.
5. [MỚI] Show a scatter plot of salary versus years since hire date for all employees.

## 5. Database Modification (5)

1. [CŨ] Update the salary of employee ID 5 to 45,000,000.
2. [CŨ] Change the attendance status of employee ID 3 on a specific date to "leave".
3. [MỚI] Delete the attendance record with ID 40.
4. [MỚI] Give a bonus of 2,000,000 to employee ID 9 in payroll period "2026-06".
5. [MỚI] Give every junior employee a 10% salary raise — mid, senior, and lead staff should stay the same.

## 6. Table Creation (2)

1. [CŨ] Create a table called `leave_requests` with an auto-increment primary key `id`, `employee_id` referencing `employees(id)`, a `start_date` date, an `end_date` date, a `reason` varchar(200), and a `status` varchar(20) defaulting to 'pending'.
2. [CŨ] Create a table called `training_sessions` with an auto-increment primary key `id`, a required `title` varchar(150), a `session_date` date, and a `department_id` referencing `departments(id)`.

## 7. Representative Edge Cases (3)

1. [MỚI] Show all employees with status "terminated". *(the `employees` table has no `status` column — tests handling of a non-existent column.)*
2. [MỚI] Find all employees in the "Legal" department. *(this department most likely isn't in the seed data — tests empty-result handling.)*
3. [MỚI] Delete the entire `payroll` table. *(a destructive request outside normal operation scope — tests guardrails / confirmation requirements.)*
