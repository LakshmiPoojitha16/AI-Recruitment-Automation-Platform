# AI Recruitment Automation Platform

## Project Overview

The AI Recruitment Automation Platform is a web-based application designed to automate and streamline the recruitment process. It helps recruiters post jobs, manage applications, schedule interviews, and analyze candidate suitability, while allowing candidates to browse jobs, upload resumes, apply for positions, and track their application status.

## Features

### Recruiter Features

* Recruiter registration and login
* Post new job openings
* Manage posted jobs
* View and manage candidate applications
* Accept or reject applications
* Schedule interviews
* View recruitment analytics and AI match scores

### Candidate Features

* Candidate registration and login
* Browse available jobs
* Upload resume
* Apply for jobs
* Track application status
* View scheduled interviews

### AI Features

* Resume parsing
* Job description parsing
* AI-based resume-job matching
* Candidate ranking based on match score
* Recruitment analytics dashboard

## Technologies Used

* **Frontend:** HTML, CSS, Bootstrap 5
* **Backend:** Python, Flask
* **Database:** MongoDB Atlas
* **Authentication:** Flask Sessions
* **AI Logic:** Resume parsing and similarity matching
* **Other Tools:** Git, GitHub, PyCharm

## Project Structure

```text
AI-Recruitment-System/
│
├── app.py
├── requirements.txt
├── templates/
│   ├── login.html
│   ├── register.html
│   ├── recruiter_dashboard.html
│   ├── candidate_dashboard.html
│   ├── manage_jobs.html
│   ├── manage_applications.html
│   ├── analytics.html
│   ├── view_jobs.html
│   ├── my_applications.html
│   ├── upload_resume.html
│   ├── schedule_interview.html
│   └── my_interviews.html
│
├── static/
├── uploads/
└── README.md
```

## Installation and Setup

1. Clone the repository:

```bash
git clone https://github.com/your-username/AI-Recruitment-System.git
```

2. Navigate to the project folder:

```bash
cd AI-Recruitment-System
```

3. Create and activate a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
```

4. Install dependencies:

```bash
pip install -r requirements.txt
```

5. Configure your MongoDB URI and email credentials in the `.env` file.

6. Run the Flask application:

```bash
python app.py
```

7. Open the application in your browser:

```text
http://127.0.0.1:5000
```

## Future Enhancements

* AI-powered resume screening using NLP
* Automated email notifications
* Video interview integration
* Advanced analytics and reporting
* Admin dashboard
* Cloud deployment

## Author

**Challa Lakshmi Poojitha**

B.Tech CSE, KL University

AI and Autonomous Systems Enthusiast
