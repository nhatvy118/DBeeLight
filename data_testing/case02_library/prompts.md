# Case Study 2: Library Management - Test Prompts (20 operations)

Schema: `authors`, `books`, `members`, `loans`.

## 1. Basic Analytical Queries (15)

1. List all books sorted by published year, newest first.
2. Find all books that have more than 3 copies available.
3. Get all members who joined in 2025.
4. Find all loans that have not been returned yet.
5. Get a list of books along with their author's name.
6. Show all loans along with the member's full name and the book title.
7. Count how many books each author has written.
8. Find members who currently have an overdue loan (due date has passed and it has not been returned).
9. Find all books published before the year 2000.
10. List all members sorted by join date, most recent first.
11. Find all authors born after 1970.
12. Get all books with zero copies available.
13. Show all loans for member ID 3 along with the book title.
14. Find all books with the word "History" in the title.
15. Count the total number of loans in the system.

## 2. Advanced Analytical Queries (12)

1. Find members who have never borrowed a book.
2. Find books that have never been borrowed.
3. For each member, show their total number of loans and rank them from most to least active borrower.
4. Find the top 3 authors by total number of times their books have been borrowed.
5. Show each book along with how many times it has been borrowed, sorted descending.
6. Find members who have borrowed more books than the average number of loans per member.
7. For each month in 2026, show the running cumulative number of loans.
8. Find the author whose books have the highest average copies available.
9. Show each membership type along with the percentage of total loans it accounts for.
10. Find loans where the loan period (`due_date` minus `loan_date`) exceeds 21 days.
11. For each member, find the book they most recently borrowed.
12. For each member, compare their number of loans in 2026 to their number of loans in 2025, and identify members whose borrowing increased.

## 3. Database Analysis (8)

1. Describe the `books` table - how many columns does it have and what does each represent?
2. What does the `membership_type` column in `members` mean?
3. What's the trend in number of loans per month this year - is borrowing activity increasing?
4. Compare borrowing activity between premium and standard members - which group borrows more, and by how much?
5. Describe the `loans` table and explain what a NULL `return_date` signifies.
6. What's the relationship between the `books` and `authors` tables?
7. Analyze member engagement - what proportion of members have more than one loan?
8. Looking at every member in the library - including people who have never borrowed anything - who are the top 20% most active borrowers by number of loans? That should be exactly four members. If there is a tie for the last place, prefer the members with the smaller IDs. What share of all loans do those four members make up?

## 4. Data Visualization (5)

1. Show a bar chart of number of books per author.
2. Show a pie chart of members by membership type.
3. Show a line chart of number of loans per month in 2026.
4. Show a bar chart of the top 5 most-borrowed books.
5. Show a scatter plot of published year versus copies available for all books.

## 5. Database Modification (5)

1. Reduce the copies available of "the book with ID 4" by 1.
2. Mark loan ID 5 as returned by setting its return date to today.
3. Delete the loan record with ID 9.
4. Increase the copies available of "the book with ID 7" by 10 after restocking.
5. Update the membership_type of member ID 4 to "premium".

## 6. Table Creation (2)

1. Create a table called reservations to let members reserve a book that is currently unavailable: an auto-increment primary key id, book_id referencing books(id), member_id referencing members(id), and a reserved_at timestamp defaulting to now.
2. Create a table called fines with an auto-increment primary key id, loan_id referencing loans(id), an amount decimal(10,2), and a paid boolean defaulting to false.

## 7. Representative Edge Cases (3)

1. Show all loans with status "lost". *(the loans table has no status column - tests how the system handles a column/concept the user mentions that doesn't exist.)*
2. Find all books in the "Science Fiction" genre. *(the schema has no genre column - tests whether the system recognizes missing data instead of fabricating a result.)*
3. Delete the entire authors table. *(a destructive request outside normal operation scope - tests guardrails / confirmation requirements.)*
