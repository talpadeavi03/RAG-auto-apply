# RAG-AG-Apply

**RAG & GitHub-Powered Autonomous Job Application & Profile Management Pipeline**  
*Tailored for LinkedIn, Naukri, and External Career Portals with Antigravity CLI (`agy`) Assistance.*

---

## 🚀 Overview

`RAG-AG-Apply` is an intelligent, agent-assisted automation framework designed to streamline the tech job search and profile presence across **LinkedIn** and **Naukri**:

1. **RAG Knowledge Base & GitHub Mining**: Ingests your master resume and public GitHub repositories (including READMEs, architectures, starred projects, and technical skills) into a local vector retrieval index.
2. **Auto Profile Updating**:
   - **LinkedIn**: Generates and updates ATS-optimized headlines, About/Summary sections featuring live GitHub projects, and core skill endorsements.
   - **Naukri**: Formulates an ATS-tailored Resume Headline (strict 250 character compliance) and Profile Summary. Refreshes the profile timestamp daily to maximize recruiter search ranking.
3. **Automated Applications**:
   - **Naukri**: Searches target roles, evaluates RAG match scores, answers screening questions, and performs direct 1-click apply.
   - **LinkedIn**: Searches roles with Easy Apply filters, calculates skill fit via RAG, automatically navigates multi-step modals, answers recruiter screening questions, and submits applications.
4. **External Link Redirection & Antigravity CLI (`agy`) Assist**:
   - When a job redirects to an external career portal (e.g. Workday, Greenhouse, Lever, Taleo, Ashby, SmartRecruiters, or company career sites), the engine intercepts the redirect.
   - Auto-compiles an **Application Dossier** containing candidate contact info, tailored cover letter, matched skills, and RAG context.
   - Hands off directly to the **Antigravity CLI** (`agy -i` / `agy -p`) to assist you in filling out the external portal smoothly.

---

## 🛠️ Architecture

```
                  ┌──────────────────────┐
                  │ Master Resume & PDF  │
                  └──────────┬───────────┘
                             │
 ┌─────────────────┐         ▼         ┌─────────────────────────┐
 │ GitHub Profile  ├──────► RAG ◄──────┤ Candidate Preferences   │
 │ & Repositories  │    Vector Store   │ (config/user_profile)   │
 └─────────────────┘         │         └─────────────────────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
   ┌──────────────────────┐      ┌──────────────────────┐
   │ LinkedIn Integration │      │  Naukri Integration  │
   ├──────────────────────┤      ├──────────────────────┤
   │ • Profile Headline   │      │ • Resume Headline    │
   │ • About & Summary    │      │ • Profile Summary    │
   │ • Easy Apply Modal   │      │ • 1-Click Apply      │
   │ • RAG Q&A Answering  │      │ • Screening Q&A      │
   └──────────┬───────────┘      └──────────┬───────────┘
              │                             │
              └──────────────┬──────────────┘
                             │
                   External Redirect?
                             │
                             ▼
              ┌─────────────────────────────┐
              │ External Redirect Handler   │
              │ • Prepares Dossier          │
              │ • Synthesizes Cover Letter  │
              └──────────────┬──────────────┘
                             │
                             ▼
              ┌─────────────────────────────┐
              │    Antigravity CLI (agy)    │
              │    External Portal Assist   │
              └─────────────────────────────┘
```

---

## 📦 Installation & Setup

### 1. Antigravity CLI Installation
Antigravity CLI can be installed directly via:
```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```
Verify installation:
```bash
agy --version
```

### 2. Python Environment Setup
```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies and editable package
pip install -e .

# Install Playwright browser
playwright install chromium
```

---

## ⚙️ Configuration

### 1. Candidate Profile: `config/user_profile.json`
Update your personal details, GitHub username, notice period, target roles, and answers to common recruiter questions:
```json
{
  "full_name": "Your Name",
  "email": "you@example.com",
  "phone": "+91 9876543210",
  "github_username": "your-github-handle",
  "years_of_experience": 3.5,
  "notice_period_days": 15,
  "skills": ["Python", "FastAPI", "React", "Docker", "Kubernetes", "PostgreSQL"]
}
```

### 2. Search Settings: `config/settings.yaml`
Configure search keywords, locations, match thresholds, and headless browser mode.

---

## 💻 CLI Usage

### Step 1: Ingest GitHub & Resume
Fetch your GitHub repositories and chunk your resume into the RAG vector store:
```bash
rag-apply ingest --github <your-username> --resume data/resumes/sample_resume.md
```

### Step 2: Auto-Update & Refresh Profiles
Preview or push updates to LinkedIn and Naukri:
```bash
# Preview generated ATS summaries and headlines
rag-apply profile preview --platform both

# Update profiles using browser session
rag-apply profile update --platform both
```

### Step 3: Run Job Applications (Naukri & LinkedIn Easy Apply)
```bash
# Run auto-apply with a minimum RAG match score of 65%
rag-apply apply --platform both --limit 10 --min-score 0.65
```

### Step 4: Antigravity CLI External Application Assistance
When encountering an external job redirect, or to assist with a specific external portal URL directly:
```bash
rag-apply assist --url "https://jobs.lever.co/company/job-id" --company "Acme Corp" --title "Senior Backend Engineer"
```
This generates a tailored application dossier in `data/applications/` and launches `agy -i` to guide form completion.

### Step 5: Check Application Status
```bash
rag-apply status
```

---

## ⚡ GitHub Actions Automation

The entire pipeline runs autonomously via GitHub Actions.

### Configured Workflows

1. **`daily-job-pipeline.yml`**:
   - **Trigger:** Scheduled every 4 hours daily (`0 */4 * * *`) and on manual dispatch.
   - **Actions:**
     - Bootstraps Antigravity CLI (`agy`) directly on the Ubuntu runner via `curl -fsSL https://antigravity.google/cli/install.sh | bash`.
     - Ingests latest GitHub repositories and resume into the RAG index.
     - Automatically updates & refreshes LinkedIn and Naukri profile timestamps.
     - Runs automated job applications for Naukri Direct & LinkedIn Easy Apply.
     - Prepares application dossiers for external redirects and assists with `agy`.
     - Uploads artifacts (`data/applications/`, `data/tracker.db`) and publishes a GitHub Step Summary.
     - Persists tracking state back to the repository.

2. **`assist-external-portal.yml`**:
   - **Trigger:** Manual dispatch with `url`, `company`, and `title`.
   - **Actions:**
     - Prepares tailored ATS application answers, tailored pitch, and dossier.
     - Runs the Antigravity CLI assistant against the portal.
     - Displays the complete dossier in the GitHub Step Summary.

### Repository Secrets Configuration
To enable automated applications and Discord alerts on GitHub Actions, add these repository secrets in **Settings > Secrets and variables > Actions**:
- `LINKEDIN_EMAIL` & `LINKEDIN_PASSWORD`
- `NAUKRI_EMAIL` & `NAUKRI_PASSWORD`
- `GH_PAT` (Personal Access Token for authenticated git commits & API requests)
- `DISCORD_WEBHOOK_URL` (Discord channel webhook URL for real-time embeds)

---

## 📢 Discord Alerts

The system sends real-time colored embeds directly to your Discord channel:
- 🔄 **Profile Updates:** When LinkedIn/Naukri profiles are refreshed with latest GitHub project links.
- 🎉 **Applied Jobs:** Real-time alert when a job is successfully applied (Job title, company, platform, match score, link).
- 🔗 **External Redirects:** When a job redirects externally, an alert is sent with the direct portal link and Antigravity CLI dossier.
- 📊 **Cycle Summary:** Metrics summary after each 4-hour cycle.

---

## 🔄 Daily Automation

Run the included automated daily script or schedule it via cron:
```bash
./scripts/run_daily.sh
```
This script automatically:
1. Re-indexes your latest GitHub commits and repos.
2. Updates and bumps your Naukri & LinkedIn profile activity timestamps.
3. Searches and applies to matching open positions.
4. Flags external applications for Antigravity CLI assist.
