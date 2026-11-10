"""The `ai-recruit` command line."""

from pathlib import Path
from typing import Annotated

import typer
from notion_client import Client as NotionClient
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

from ai_recruitment_agent import __version__
from ai_recruitment_agent.extract import (
    SUPPORTED_CV_FORMATS,
    ExtractionError,
    extract_text,
    extract_text_from_pdf,
)
from ai_recruitment_agent.gemini import GeminiAPIError, GeminiResponseError, Screener
from ai_recruitment_agent.notion_io import (
    NotionError,
    create_candidate_page,
    ensure_properties,
    find_duplicate,
    resolve_data_source,
)
from ai_recruitment_agent.settings import Settings

console = Console()

# After this many Gemini failures in a row (a bad key, an unknown model, an exhausted quota) the run stops instead of failing every CV.
MAX_CONSECUTIVE_API_ERRORS = 3

app = typer.Typer(
    add_completion=False,
    help="AI-powered CV screening against a Job Description — results pushed to Notion.",
    no_args_is_help=False,
)


def say(markup: str) -> None:
    """Print Rich markup. Anything from a file name, an exception or a model goes through `escape()` before it is put in."""
    console.print(markup)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"ai-recruitment-agent v{__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option("--version", "-V", callback=_version_callback, is_eager=True, help="Show version and exit."),
    ] = None,
) -> None:
    """AI-powered CV screening CLI."""
    if ctx.invoked_subcommand is None:
        console.print(
            Panel(
                "[bold cyan]AI Recruitment Scanning Agent[/bold cyan]\n\n"
                "Screens CVs against a Job Description using [bold]Google Gemini[/bold]\n"
                "and pushes ranked candidates into a [bold]Notion database[/bold].",
                title="[bold]ai-recruit[/bold]",
                border_style="cyan",
                padding=(1, 2),
            )
        )
        say("[bold]Usage:[/bold]")
        say(
            "  ai-recruit process [green]<CV_FOLDER>[/green] [green]<JD_PDF>[/green] "
            "[[yellow]--notion-db-id[/yellow] [yellow]<DB_ID>[/yellow]]\n"
        )
        say("[bold]Configure via .env:[/bold]")
        say("  GOOGLE_GEMINI_API_KEY=...")
        say("  NOTION_API_KEY=...")
        say("  DEFAULT_NOTION_DB_ID=...")
        say("  GEMINI_MODEL=...            [dim](optional)[/dim]")
        say("  NOTION_DATA_SOURCE_ID=...   [dim](only for a database with several data sources)[/dim]\n")
        say("Run [cyan]ai-recruit process --help[/cyan] for full usage details.")


@app.command(name="process", help="Screen CVs in a folder against a Job Description PDF.")
def process_documents(
    cv_folder_path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            help="Folder containing CV files (.pdf / .docx).",
        ),
    ],
    jd_pdf_path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Job Description PDF file.",
        ),
    ],
    notion_db_id_cli: Annotated[
        str | None,
        typer.Option(
            "--notion-db-id",
            "-n",
            help="Notion database ID (overrides DEFAULT_NOTION_DB_ID in .env).",
        ),
    ] = None,
    data_source_id_cli: Annotated[
        str | None,
        typer.Option(
            "--data-source-id",
            help="Notion data source ID, for a database with several (overrides NOTION_DATA_SOURCE_ID).",
        ),
    ] = None,
) -> None:
    """Screen CVs against a Job Description and push results to Notion. Exits 1 if any CV could not be processed."""
    settings = Settings.load()

    # --- Pre-run validation ---
    errors: list[str] = []
    if not settings.gemini_api_key:
        errors.append("GOOGLE_GEMINI_API_KEY not found")
    if not settings.notion_api_key:
        errors.append("NOTION_API_KEY not found")
    database_id = notion_db_id_cli or settings.notion_database_id
    data_source_id = data_source_id_cli or settings.notion_data_source_id
    if not database_id and not data_source_id:
        errors.append("Notion Database ID is not provided (use --notion-db-id or set DEFAULT_NOTION_DB_ID in .env)")
    if errors:
        for err in errors:
            say(f"[bold red]✗[/bold red] {escape(err)}")
        raise typer.Exit(code=1)
    assert settings.gemini_api_key and settings.notion_api_key  # narrowed above

    say("[bold green]✓[/bold green] Pre-run checks passed.")

    # --- Notion ---
    notion = NotionClient(auth=settings.notion_api_key)
    try:
        source = resolve_data_source(notion, database_id or "", data_source_id)
    except NotionError as exc:
        say(f"[bold red]✗ Notion initialization failed:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc
    say(f"[bold green]✓[/bold green] Notion connection established: [cyan]{escape(source.database_title)}[/cyan]")

    screener = Screener(settings.gemini_api_key, settings.gemini_model)

    # --- Job description ---
    say(f"\n[bold]Reading JD:[/bold] {escape(jd_pdf_path.name)}")
    try:
        jd_text = extract_text_from_pdf(jd_pdf_path)
    except ExtractionError as exc:
        say(f"[bold red]✗[/bold red] Could not read the JD {escape(jd_pdf_path.name)}: {escape(str(exc))}")
        raise typer.Exit(code=1) from exc
    try:
        details = screener.job_details(jd_text)
    except (GeminiAPIError, GeminiResponseError) as exc:
        say(f"[bold red]✗ Gemini could not read the JD:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc
    say(
        f"[bold green]✓[/bold green] JD parsed — Position: [cyan]{escape(details['position_title'])}[/cyan]  "
        f"Job ID: [cyan]{escape(details['job_id'])}[/cyan]"
    )

    # --- CV discovery ---
    entries = list(cv_folder_path.iterdir())
    cv_files = sorted(f for f in entries if f.is_file() and f.suffix.lower() in SUPPORTED_CV_FORMATS)
    if not cv_files:
        say(f"\n[yellow]No supported CV files (.pdf, .docx) found in:[/yellow] {escape(str(cv_folder_path))}")
        raise typer.Exit(code=0)
    say(f"\n[bold]Found {len(cv_files)} CV(s) to process.[/bold]\n")

    stats = {"total_in_folder": len(entries), "found": len(cv_files), "success": 0, "duplicates": 0, "failed": 0}
    api_errors_in_a_row = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[cyan]{task.completed}/{task.total}[/cyan]"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Starting...", total=len(cv_files))

        for cv_path in cv_files:
            name = escape(cv_path.name)
            progress.update(task, description=f"[bold]{name}[/bold]")
            try:
                outcome = _screen_one(cv_path, screener, jd_text, details, notion, source.id)
                api_errors_in_a_row = 0
            except _ApiFailure as exc:
                api_errors_in_a_row += 1
                say(f"  [yellow]⚠[/yellow]  {name}: {escape(str(exc))}")
                stats["failed"] += 1
                progress.advance(task)
                if api_errors_in_a_row >= MAX_CONSECUTIVE_API_ERRORS:
                    say(
                        f"[bold red]✗ Stopping:[/bold red] Gemini failed {MAX_CONSECUTIVE_API_ERRORS} times in a row "
                        "(check the API key, the model name in GEMINI_MODEL, and the quota)."
                    )
                    break
                continue
            except _Skipped as exc:
                say(f"  [yellow]⚠[/yellow]  {name}: {escape(str(exc))}")
                stats["failed"] += 1
                progress.advance(task)
                continue

            if outcome == "duplicate":
                say(f"  [dim]↩  Duplicate skipped:[/dim] {name}")
                stats["duplicates"] += 1
            else:
                stats["success"] += 1
                say(f"  [green]✓[/green]  {name} — {escape(outcome)}")
            progress.advance(task)

    # --- Summary ---
    console.print()
    table = Table(title="Processing Summary", show_lines=True, border_style="dim")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")
    table.add_row("Total files in folder", str(stats["total_in_folder"]))
    table.add_row("Supported CV files found", str(stats["found"]))
    table.add_row("Successfully processed & added to Notion", Text(str(stats["success"]), style="bold green"))
    table.add_row("Skipped (duplicates)", str(stats["duplicates"]))
    table.add_row("Failed", Text(str(stats["failed"]), style="bold red") if stats["failed"] else str(stats["failed"]))
    console.print(table)
    say(
        f"\n[bold green]Done.[/bold green] {stats['success']} candidate(s) added to Notion database "
        f"[dim]{escape(source.database_title)}[/dim]"
    )
    if stats["failed"]:
        say(f"[bold red]{stats['failed']} CV(s) could not be processed[/bold red] — see the messages above.")
        raise typer.Exit(code=1)


class _Skipped(Exception):
    """One CV cannot be processed (unreadable file, a Gemini answer that is not usable, a Notion failure): the run goes on."""


class _ApiFailure(_Skipped):
    """The Gemini service itself failed: the run goes on, but several in a row stop it."""


def _screen_one(cv_path: Path, screener: Screener, jd_text: str, details: dict[str, str], notion: NotionClient, source_id: str) -> str:
    """Read, screen and store one CV. Returns "duplicate" or a one-line result; raises _Skipped / _ApiFailure."""
    try:
        cv_text = extract_text(cv_path)
    except ExtractionError as exc:
        raise _Skipped(f"skipped: {exc}") from exc
    try:
        candidate = screener.analyse(cv_text, jd_text, details)
    except GeminiAPIError as exc:
        raise _ApiFailure(f"Gemini failed: {exc}") from exc
    except GeminiResponseError as exc:
        raise _Skipped(f"Gemini analysis failed: {exc}") from exc
    try:
        if find_duplicate(notion, source_id, candidate, details["job_id"], cv_path.name):
            return "duplicate"
        create_candidate_page(notion, source_id, candidate, details, cv_path.name)
    except NotionError as exc:
        raise _Skipped(str(exc)) from exc
    if candidate.match_score is None:
        return "added (no usable match score: review by hand)"
    return f"{candidate.ranking_category} ({candidate.match_score}/100)"


@app.command(name="setup-notion", help="Add required properties to an existing Notion database.")
def setup_notion(
    notion_db_id: Annotated[
        str | None,
        typer.Option(
            "--notion-db-id",
            "-n",
            help="Notion database ID (overrides DEFAULT_NOTION_DB_ID in .env).",
        ),
    ] = None,
    data_source_id_cli: Annotated[
        str | None,
        typer.Option(
            "--data-source-id",
            help="Notion data source ID, for a database with several (overrides NOTION_DATA_SOURCE_ID).",
        ),
    ] = None,
) -> None:
    """Configure a Notion database with all properties required for CV screening."""
    settings = Settings.load()
    errors: list[str] = []
    if not settings.notion_api_key:
        errors.append("NOTION_API_KEY not found")
    database_id = notion_db_id or settings.notion_database_id
    data_source_id = data_source_id_cli or settings.notion_data_source_id
    if not database_id and not data_source_id:
        errors.append("Notion Database ID not provided (use --notion-db-id or set DEFAULT_NOTION_DB_ID in .env)")
    if errors:
        for err in errors:
            say(f"[bold red]✗[/bold red] {escape(err)}")
        raise typer.Exit(code=1)
    assert settings.notion_api_key

    notion = NotionClient(auth=settings.notion_api_key)
    try:
        source = resolve_data_source(notion, database_id or "", data_source_id)
        report = ensure_properties(notion, source.id)
    except NotionError as exc:
        say(f"[bold red]✗ Notion setup failed:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc
    say(f"[bold green]✓[/bold green] Connected: [cyan]{escape(source.database_title)}[/cyan]\n")

    failed = False
    for what, name in report:
        if what == "exists":
            say(f"  [dim]↩  Already exists:[/dim] {escape(name)}")
        elif what == "added":
            say(f"  [green]✓[/green]  Added: {escape(name)}")
        elif what == "renamed":
            say(f"  [green]✓[/green]  Renamed {escape(name)}")
        else:
            failed = True
            say(f"  [yellow]⚠[/yellow]  Could not rename the title property '{escape(name)}': rename it to 'Candidate Name' in Notion by hand.")
    say(
        "\n[bold green]Notion database is ready.[/bold green] Run [cyan]ai-recruit process[/cyan] to start screening CVs."
        if not failed
        else "\n[yellow]Notion database needs one manual step (above) before screening.[/yellow]"
    )


if __name__ == "__main__":
    app()
