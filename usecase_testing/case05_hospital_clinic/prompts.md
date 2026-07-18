# Case Study 5: Hospital / Clinic — Test Prompts (20 operations)

Schema: `departments`, `doctors`, `patients`, `appointments`, `prescriptions`.
Setup: run `schema.sql` first, then import `seed_data/*.xlsx` with **append to existing table** mode, in this order: `departments`, `doctors`, `patients`, `appointments`, `prescriptions`.
Route split: 6 `db_readonly` / 6 `db_general` / 3 `chart` / 3 `db_mutation` / 2 `db_create_table` — this domain places extra weight on follow-up and mutation operations (Section 8.2).

## db_readonly (6)

1. List all doctors along with their specialty and department.
2. Find all appointments scheduled for a specific date.
3. Get all patients born before 1980.
4. Find all appointments with status "cancelled".
5. Get a list of prescriptions along with the patient's name and doctor's name for each appointment.
6. Count how many appointments each doctor has handled.

## db_general (6 — schema explanation / multi-step analysis)

7. Describe the `appointments` table — how many columns does it have, and what does the `status` column mean?
8. What values can the `status` column in `appointments` take, and what does each one mean?
9. What's the trend in number of appointments per month — is patient volume increasing?
10. Compare appointment volume between the Cardiology and Pediatrics departments — which sees more patients?
11. Why might a particular doctor have a high cancellation rate? Analyze the status breakdown of their appointments.
12. Analyze prescription patterns across the clinic — which medication is prescribed most often, and does that correlate with a specific department?

## chart (3)

13. Show a bar chart of number of appointments per department.
14. Show a pie chart of appointments by status.
15. Show a bar chart of number of patients per doctor.

## db_mutation (3)

16. Update the status of appointment ID 10 from "scheduled" to "completed".
17. Change the reason field of appointment ID 5 to "Follow-up consultation".
18. Update the dosage of prescription ID 7 to "500mg once daily".

## db_create_table (2)

19. Create a table called `lab_tests` with an auto-increment primary key `id`, `appointment_id` referencing `appointments(id)`, a `test_name` varchar(100), a `result` text, and a `test_date` date defaulting to today.
20. Create a table called `insurance_policies` with an auto-increment primary key `id`, `patient_id` referencing `patients(id)`, a `provider_name` varchar(150), a `policy_number` varchar(50), and an `expiry_date` date.
