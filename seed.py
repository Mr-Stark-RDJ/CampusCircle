import os
from pymongo import MongoClient
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

MONGO_URL=os.getenv("MONGO_URL")
mongo=MongoClient(MONGO_URL)
db=mongo["campus_circle"]
users=db["users"]
events=db["events"]

users.delete_many({})
events.delete_many({})

from random import choice, randint
import secrets, string

branches=["CSE","ECE","ME","CE","EEE","IT","BBA","MBA"]
first=["Aarav","Vivaan","Aditya","Ishaan","Vihaan","Arjun","Reyansh","Shaurya","Krish","Dhruv","Ananya","Diya","Aadhya","Anika","Ira","Myra","Sara","Kiara","Meera","Aarohi"]
last=["Sharma","Verma","Gupta","Singh","Patel","Reddy","Nair","Das","Khan","Chopra","Bose","Pillai"]
companies=["TCS","Infosys","Wipro","Accenture","HCL","Google","Microsoft","Amazon","Flipkart","Paytm","Zomato","Swiggy","PhonePe","Byjus","Ola"]

for _ in range(80):
    fn=f"{choice(first)} {choice(last)}"
    yr=randint(2012,2025)
    br=choice(branches)
    pe=f"{fn.lower().replace(' ','')}@mail.com"
    users.insert_one({
        "college_email": f"{fn.lower().replace(' ','')}{yr}{br.lower()}@college.edu",
        "personal_email": pe,
        "password_hash": generate_password_hash("Pass@1234"),
        "verified_at": datetime.utcnow(),
        "created_at": datetime.utcnow(),
        "role": "alumni",
        "full_name": fn,
        "phone": "9"+"".join(secrets.choice(string.digits) for _ in range(9)),
        "mobile": "8"+"".join(secrets.choice(string.digits) for _ in range(9)),
        "company": choice(companies),
        "graduation_year": yr,
        "linkedin": "https://linkedin.com/in/"+fn.lower().replace(" ",""),
        "branch": br
    })

base=datetime.utcnow()
events.insert_many([
    {"title":"Annual Alumni Meet","description":"Reunion and networking","date":base+timedelta(days=10),"published":True,"created_at":datetime.utcnow(),"updated_at":datetime.utcnow()},
    {"title":"Mentorship Drive","description":"Alumni mentoring signups","date":base+timedelta(days=25),"published":True,"created_at":datetime.utcnow(),"updated_at":datetime.utcnow()},
    {"title":"Webinar: Careers in AI","description":"Industry talk","date":base+timedelta(days=40),"published":False,"created_at":datetime.utcnow(),"updated_at":datetime.utcnow()}
])

print("Seeded")
