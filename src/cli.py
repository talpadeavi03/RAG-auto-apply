import os
import sys
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.config import settings, DATA_DIR
from src.models import CandidateProfile, JobPost, Platform, ApplyType
from src.rag.github_loader import GitHubLoader
from src.rag.resume_loader import ResumeLoader
from src.rag.vector_store import LocalVectorStore
from src.rag.generator import RAGGenerator
from src.tracker.database import ApplicationTracker
from src.assistant.agy_bridge import AntigravityCLIBridge
from src.profile_updater.linkedin_updater import LinkedInProfileUpdater
from src.profile_updater.naukri_updater import NaukriProfileUpdater
from src.engines.external_handler import ExternalRedirectHandler
from src.engines.form_submitter import AutonomousFormSubmitter
from src.engines.linkedin_easy_apply import LinkedInEasyApplyEngine
from src.engines.naukri_apply import NaukriApplyEngine
from src.notifier.discord import notifier

app = typer.Typer(help="RAG-AG-Apply: Intelligent Job Application & Profile Management with Antigravity CLI Assistance")
console = Console()

def get_context():
    vector_store = LocalVectorStore()
    profile = settings.profile
    generator = RAGGenerator(profile, vector_store)
    tracker = ApplicationTracker()
    agy_bridge = AntigravityCLIBridge()
    form_submitter = AutonomousFormSubmitter(profile, vector_store, generator, tracker)
    external_handler = ExternalRedirectHandler(profile, vector_store, tracker, agy_bridge, form_submitter=form_submitter)
    return vector_store, profile, generator, tracker, agy_bridge, external_handler

@app.command()
def ingest(
    github_user: str = typer.Option(None, "--github", "-g", help="GitHub username to mine repositories from"),
    resume_path: str = typer.Option(None, "--resume", "-r", help="Path to resume file (PDF, Markdown, TXT)")
):
    """
    Ingest Candidate Resume and GitHub Repositories into the RAG Vector Store.
    """
    console.print(Panel.fit("[bold cyan]RAG Knowledge Base Ingestion[/bold cyan]", border_style="cyan"))
    vector_store = LocalVectorStore()
    all_docs = []

    # 1. Ingest GitHub
    target_user = github_user or settings.profile.github_username or settings.config_data.get("github", {}).get("username")
    if target_user:
        with console.status(f"[bold green]Fetching GitHub repositories for '{target_user}'..."):
            loader = GitHubLoader(username=target_user)
            repos = loader.fetch_repos(max_repos=15)
            gh_docs = loader.to_rag_documents(repos)
            all_docs.extend(gh_docs)
            console.print(f"✓ Ingested [bold green]{len(repos)}[/bold green] GitHub repositories.")

    # 2. Ingest Resume
    target_resume = resume_path
    if not target_resume:
        resumes_dir = DATA_DIR / "resumes"
        if resumes_dir.exists():
            files = list(resumes_dir.glob("*.md")) + list(resumes_dir.glob("*.pdf")) + list(resumes_dir.glob("*.txt"))
            if files:
                target_resume = str(files[0])

    if target_resume and Path(target_resume).exists():
        with console.status(f"[bold green]Parsing resume from '{target_resume}'..."):
            res_loader = ResumeLoader(target_resume)
            res_docs = res_loader.load_and_chunk()
            all_docs.extend(res_docs)
            console.print(f"✓ Ingested [bold green]{len(res_docs)}[/bold green] resume sections.")
    else:
        console.print("[yellow]Notice: No resume file provided. Place your resume in data/resumes/ or pass --resume <path>[/yellow]")

    if all_docs:
        vector_store.add_documents(all_docs)
        console.print(f"\n🎉 [bold green]Success![/bold green] Vector index now contains [bold]{len(vector_store.documents)}[/bold] knowledge documents.")
    else:
        console.print("[red]No documents were ingested. Please check GitHub username or resume path.[/red]")

@app.command()
def profile(
    action: str = typer.Argument("update", help="Action: 'update' or 'preview'"),
    platform: str = typer.Option("both", "--platform", "-p", help="Target: 'linkedin', 'naukri', or 'both'"),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help="Preview generated profile updates without submitting")
):
    """
    Auto-update LinkedIn & Naukri profiles with GitHub projects & ATS optimizations.
    """
    console.print(Panel.fit(f"[bold magenta]Profile Optimizer & Auto-Updater ({platform.upper()})[/bold magenta]", border_style="magenta"))
    vector_store, user_prof, generator, _, _, _ = get_context()

    # Load GitHub repos
    gh_loader = GitHubLoader(user_prof.github_username)
    repos = gh_loader.fetch_repos(max_repos=10)

    # 1. LinkedIn Update
    if platform in ["linkedin", "both"]:
        li_payload = generator.generate_linkedin_profile(repos)
        updater = LinkedInProfileUpdater()
        if action == "preview" or dry_run:
            console.print("\n[bold cyan]=== LinkedIn Profile Preview ===[/bold cyan]")
            console.print(f"[bold]Headline:[/bold] {li_payload.headline}")
            console.print(f"\n[bold]About / Summary:[/bold]\n{li_payload.summary}")
        else:
            with console.status("[bold green]Updating LinkedIn Profile..."):
                updater.update_profile(li_payload, dry_run=False)

    # 2. Naukri Update
    if platform in ["naukri", "both"]:
        nk_payload = generator.generate_naukri_profile(repos)
        updater = NaukriProfileUpdater()
        if action == "preview" or dry_run:
            console.print("\n[bold cyan]=== Naukri Profile Preview ===[/bold cyan]")
            console.print(f"[bold]Resume Headline:[/bold] {nk_payload.headline}")
            console.print(f"\n[bold]Profile Summary:[/bold]\n{nk_payload.summary}")
            if nk_payload.projects_text:
                console.print(f"\n[bold]Projects Text:[/bold]\n{nk_payload.projects_text}")
        else:
            with console.status("[bold green]Updating and Refreshing Naukri Profile..."):
                updater.update_profile(nk_payload, dry_run=False)

@app.command()
def apply(
    platform: str = typer.Option("both", "--platform", "-p", help="'naukri', 'linkedin', or 'both'"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum jobs to process per platform"),
    min_score: float = typer.Option(0.65, "--min-score", "-s", help="Minimum RAG match score threshold (0.0 - 1.0)")
):
    """
    Search and Apply for Naukri & LinkedIn Easy Apply jobs.
    Directly routes external redirect applications to Antigravity CLI (agy).
    """
    console.print(Panel.fit("[bold green]Autonomous Job Application Pipeline[/bold green]", border_style="green"))
    vector_store, user_prof, generator, tracker, agy_bridge, external_handler = get_context()

    # 1. Naukri Flow
    if platform in ["naukri", "both"]:
        console.print("\n[bold blue]>>> Processing Naukri Applications...[/bold blue]")
        naukri_engine = NaukriApplyEngine(user_prof, vector_store, generator, tracker, external_handler)
        keywords = settings.config_data.get("naukri", {}).get("keywords", user_prof.skills[:3])
        locations = settings.config_data.get("naukri", {}).get("locations", ["India"])
        
        with console.status("[bold blue]Searching Naukri jobs..."):
            naukri_jobs = naukri_engine.search_jobs(keywords=keywords, locations=locations, limit=limit)

        console.print(f"Found {len(naukri_jobs)} jobs. Evaluating matches with RAG...")
        for job in naukri_jobs:
            if job.match_score >= min_score:
                console.print(f"Applying to [bold]{job.title}[/bold] at [cyan]{job.company}[/cyan] (Match: {int(job.match_score*100)}%)")
                naukri_engine.apply_to_job(job)
            else:
                console.print(f"Skipping [dim]{job.title} at {job.company} (Match score {int(job.match_score*100)}% below {int(min_score*100)}%)[/dim]")

    # 2. LinkedIn Easy Apply Flow
    if platform in ["linkedin", "both"]:
        console.print("\n[bold blue]>>> Processing LinkedIn Easy Apply Applications...[/bold blue]")
        li_engine = LinkedInEasyApplyEngine(user_prof, vector_store, generator, tracker, external_handler)
        keywords = settings.config_data.get("linkedin", {}).get("target_titles", user_prof.target_titles or ["Software Engineer"])
        locations = settings.config_data.get("linkedin", {}).get("locations", ["Remote"])

        with console.status("[bold blue]Searching LinkedIn Easy Apply jobs..."):
            li_jobs = li_engine.search_jobs(keywords=keywords, locations=locations, limit=limit)

        console.print(f"Found {len(li_jobs)} Easy Apply jobs. Evaluating matches with RAG...")
        for job in li_jobs:
            if job.match_score >= min_score:
                console.print(f"Processing [bold]{job.title}[/bold] at [cyan]{job.company}[/cyan] (Match: {int(job.match_score*100)}%)")
                li_engine.apply_to_job(job)
            else:
                console.print(f"Skipping [dim]{job.title} at {job.company} (Match: {int(job.match_score*100)}%)[/dim]")

    # Send Cycle Summary Alert to Discord
    stats = tracker.get_summary_stats()
    redirects = tracker.get_redirected_jobs(pending_only=False)
    notifier.notify_cycle_summary(
        total_processed=stats.get("total", 0),
        applied_count=stats.get("breakdown", {}).get("applied", 0),
        redirect_count=len(redirects),
        platform=platform.capitalize()
    )

@app.command()
def assist(
    url: str = typer.Option(..., "--url", "-u", help="External job application portal URL"),
    company: str = typer.Option("Company", "--company", "-c", help="Company Name"),
    title: str = typer.Option("Software Engineer", "--title", "-t", help="Job Title")
):
    """
    Launch Antigravity CLI (agy) Assistant with Candidate Dossier for an External Redirect.
    """
    console.print(Panel.fit("[bold yellow]Antigravity CLI (agy) Application Assistant[/bold yellow]", border_style="yellow"))
    vector_store, user_prof, _, tracker, agy_bridge, external_handler = get_context()

    job = JobPost(
        platform=Platform.EXTERNAL,
        job_id=f"ext_{abs(hash(url))}",
        title=title,
        company=company,
        location="External Portal",
        job_url=url,
        apply_type=ApplyType.EXTERNAL_REDIRECT,
        external_url=url,
        match_score=0.9
    )

    external_handler.handle_redirect(job, interactive=True)

@app.command()
def status():
    """
    View summary of applied jobs, redirects, and statistics.
    """
    tracker = ApplicationTracker()
    stats = tracker.get_summary_stats()

    table = Table(title="Application History & Pipeline Summary")
    table.add_column("Status", style="cyan")
    table.add_column("Count", style="green")

    table.add_row("Total Processed", str(stats["total"]))
    for st, count in stats["breakdown"].items():
        table.add_row(st.capitalize(), str(count))

    console.print(table)

    redirects = tracker.get_redirected_jobs(pending_only=False)
    if redirects:
        r_table = Table(title="External Redirect Applications (Antigravity CLI Assisted)")
        r_table.add_column("Company", style="cyan")
        r_table.add_column("Title", style="white")
        r_table.add_column("Status", style="magenta")
        r_table.add_column("External Portal URL", style="dim")

        for r in redirects[:10]:
            r_table.add_row(r.company, r.title, r.status.value, (r.external_url or "")[:50] + "...")
        console.print(r_table)

if __name__ == "__main__":
    app()
