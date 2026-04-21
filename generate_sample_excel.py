import pandas as pd
import random

# Fields requested: student name, student id, student number, year, branch, student mobile number, alternative number
names = [
    "Rahul", "Priya", "Amit", "Sneha", "Vikram", "Anjali", "Siddharth", "Kavita", "Aditya", "Riya",
    "Manish", "Pooja", "Arjun", "Neeta", "Sanjay", "Deepa", "Karan", "Megha", "Rohan", "Shweta",
    "Vijay", "Tanvi", "Abhishek", "Ritu", "Sameer", "Preeti", "Alok", "Sonal", "Ishaan", "Nisha",
    "Pranav", "Divya", "Gaurav", "Anita", "Vivek", "Rashmi", "Varun", "Sunita", "Akash", "Rekha",
    "Mayank", "Seema", "Ashwin", "Maya", "Hemant", "Kiran", "Sumit", "Jaya", "Pankaj", "Bhakti"
]
surnames = ["Sharma", "Verma", "Patil", "Deshmukh", "Joshi", "Kulkarni", "Singhania", "Goenka", "Mehta", "Aggarwal"]

branches = ["Computer Science", "Information Technology", "Mechanical Engineering", "Civil Engineering", "Electrical Engineering"]
years = ["First Year", "Second Year", "Third Year", "Fourth Year"]

data = []
for i in range(1, 101):
    first_name = random.choice(names)
    last_name = random.choice(surnames)
    full_name = f"{first_name} {last_name}"
    
    student_id = f"{i}"
    student_num = f"2026BN{5000 + i}"
    year = random.choice(years)
    branch = random.choice(branches)
    
    student_mobile = f"{random.randint(7000000000, 9999999999)}"
    alt_num = f"{random.randint(7000000000, 9999999999)}"
    
    data.append([full_name, student_id, student_num, year, branch, student_mobile, alt_num])

df = pd.DataFrame(data, columns=[
    "student name", "student id", "student number", "year", "branch", "student mobile number", "alternative number"
])

df.to_excel("student_100_sample.xlsx", index=False)
print("Generated student_100_sample.xlsx with 'student mobile number' (IDs starting from 1).")
