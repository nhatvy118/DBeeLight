# Case Study 3: Blog / CMS — Test Prompts (50 operations)

Schema: `users`, `posts`, `comments`, `tags`, `post_tags`.
Setup: run `schema.sql` first, then import `seed_data/*.xlsx` with **append to existing table** mode, in this order: `users`, `posts`, `tags`, `comments`, `post_tags`.

Prompt distribution (Table 7.3): 15 Basic analytical queries / 12 Advanced analytical queries / 8 Database analysis / 5 Data visualization / 5 Database modification / 2 Table creation / 3 Representative edge cases.

Legend: **[CŨ]** = prompt có sẵn từ trước (20 prompt gốc, giữ nguyên nội dung) · **[MỚI]** = prompt vừa thêm để đủ 50/domain.
## 1. Basic Analytical Queries (15)

1. [CŨ] List all published posts sorted by publish date, newest first.
2. [CŨ] Find all posts written by a specific user (by username).
3. [CŨ] Get the top 5 most-commented posts.
4. [CŨ] Find all comments that are replies to another comment.
5. [CŨ] Get a list of posts along with the author's full name.
6. [CŨ] Show each tag along with the number of posts using it.
7. [CŨ] Find all draft posts that have never been published.
8. [CŨ] Get all comments on a specific post along with the commenter's username.
9. [MỚI] Find all posts written in 2026.
10. [MỚI] List all users sorted by role.
11. [MỚI] Find all comments containing the word "great".
12. [MỚI] Get all tags sorted alphabetically.
13. [MỚI] Show all posts by the user with username "admin".
14. [MỚI] Find all top-level comments (not replies) on a specific post.
15. [MỚI] Count the total number of published posts.

## 2. Advanced Analytical Queries (12)

1. [MỚI] Find users who have never written a post.
2. [MỚI] Find posts that have never received a comment.
3. [MỚI] For each user, show their total number of posts and rank them from most to least prolific author.
4. [MỚI] Find the top 3 tags by total number of comments on posts using them.
5. [MỚI] Show each post along with its comment count and reply count, sorted by comment count descending.
6. [MỚI] Find users whose average comments-per-post exceeds the site-wide average.
7. [MỚI] For each month in 2025, show the running cumulative number of published posts.
8. [MỚI] Find the tag whose posts have the highest average comment count.
9. [MỚI] Show each user role along with the percentage of total comments it accounts for.
10. [MỚI] Find comment threads that are nested more than 2 levels deep (a reply to a reply).
11. [MỚI] For each user, find the most recent post they published.
12. [MỚI] For each user, compare their post count in 2026 to their post count in 2025, and identify users whose output increased.

## 3. Database Analysis (8)

1. [CŨ] Describe the `posts` table — how many columns does it have, and what does the `status` column mean?
2. [CŨ] What does the `parent_comment_id` column in `comments` represent?
3. [CŨ] What's the trend in number of posts published per month — is content output increasing?
4. [CŨ] Compare engagement (average comments per post) between "tech" and "travel" tagged posts — which topic gets more discussion?
5. [MỚI] Describe the `comments` table and explain how `parent_comment_id` enables threaded replies.
6. [MỚI] What's the relationship between `posts`, `tags`, and `post_tags`?
7. [MỚI] Analyze author engagement — what proportion of users have published more than one post?
8. [MỚI] Which post status (draft vs. published) has the higher average number of comments, and what might explain that?

## 4. Data Visualization (5)

1. [CŨ] Show a bar chart of number of posts per tag.
2. [CŨ] Show a pie chart of posts by status (draft vs. published).
3. [CŨ] Show a line chart of number of posts published per month in 2025.
4. [CŨ] Show a bar chart of the top 5 users by number of posts written.
5. [MỚI] Show a scatter plot of number of comments versus number of tags per post.

## 5. Database Modification (5)

1. [CŨ] Change the status of post ID 3 from "draft" to "published".
2. [CŨ] Update the content of comment ID 10 to "Edited: thanks for the feedback!".
3. [MỚI] Delete the comment with ID 15.
4. [MỚI] Assign the tag "featured" to post ID 8.
5. [MỚI] Update the role of user ID 6 to "editor".

## 6. Table Creation (2)

1. [CŨ] Create a table called `post_likes` to track which users liked which posts: an auto-increment primary key `id`, `post_id` referencing `posts(id)`, `user_id` referencing `users(id)`, and a `liked_at` timestamp defaulting to now.
2. [CŨ] Create a table called `newsletter_subscribers` with an auto-increment primary key `id`, a unique required `email` varchar(150), and a `subscribed_at` timestamp defaulting to now.

## 7. Representative Edge Cases (3)

1. [MỚI] Show all posts with status "archived". *(`status` only accepts draft/published — tests handling of an invalid value.)*
2. [MỚI] Find all posts in the "Cooking" category. *(the schema has no `category` column, only `tags` — tests whether the system distinguishes similar-sounding concepts instead of conflating it with the `tags` table.)*
3. [MỚI] Delete the entire `users` table. *(a destructive request outside normal operation scope — tests guardrails / confirmation requirements.)*
