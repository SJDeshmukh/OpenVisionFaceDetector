import pandas as pd
import random

def generate_dummy_faculty(filename="faculty_dummy_data.xlsx", num_records=100):
    designations = ["Assistant Professor", "Associate Professor", "Professor", "Lecturer", "Senior Lecturer"]
    
    data = []
    for i in range(num_records):
        name = f"Faculty Member {i+1}"
        email = f"faculty{i+1}@example.com"
        phone = f"+91 {random.randint(6000000000, 9999999999)}"
        
        # Ensure at least some HODs, first one is HOD for guaranteed presence
        if i == 0 or random.random() < 0.1:
            designation = "HOD"
        else:
            designation = random.choice(designations)
            
        data.append({
            "faculty name": name,
            "email": email,
            "phone number": phone,
            "designation": designation
        })
    
    df = pd.DataFrame(data)
    df.to_excel(filename, index=False)
    print(f"Generated {num_records} records in {filename}")

if __name__ == "__main__":
    generate_dummy_faculty()
