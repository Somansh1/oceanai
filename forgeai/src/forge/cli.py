"""forge CLI. Day-1 surface: ingest. The factory grows here: run, chat, report, regression."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .core import Chunk, DocumentMeta, QuarantineRecord, sha256_text
from .evaltypes import RunManifest
from .ingest import SUPPORTED, chunk_document
from .llm import OllamaBackend
from .retrieve import HybridIndex

app = typer.Typer(no_args_is_help=True, help="ForgeAI — the factory that builds agents.")
console = Console()


@app.command()
def version() -> None:
    console.print(f"forge [bold]{__version__}[/bold]")


@app.command()
def ingest(
    docs: Path = typer.Option(..., "--docs", help="Folder of source documents"),
    out: Path = typer.Option(..., "--out", help="Output run folder"),
    chunk_size: int = typer.Option(900, help="Target chunk size in characters"),
    overlap: int = typer.Option(150, help="Chunk overlap in characters"),
) -> None:
    """Chunk + index a document folder. Degrades to BM25-only without ollama, honestly."""
    if not docs.is_dir():
        console.print(f"[red]not a directory:[/red] {docs}")
        raise typer.Exit(2)
    out.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in docs.rglob("*") if p.is_file())
    usable = [p for p in files if p.suffix.lower() in SUPPORTED]
    skipped = [p for p in files if p.suffix.lower() not in SUPPORTED]

    backend = OllamaBackend()
    dense = backend.available()
    degraded: list[str] = []
    if not dense:
        degraded.append("dense retrieval unavailable (ollama down) — BM25-only index")

    all_chunks: list[Chunk] = []
    metas: list[DocumentMeta] = []
    quarantined: list[QuarantineRecord] = []

    with console.status("[bold]ingesting…") as status:
        for i, path in enumerate(usable, 1):
            status.update(f"ingesting {path.name} ({i}/{len(usable)})")
            doc_id = f"d{i:02d}"
            try:
                chunks, meta = chunk_document(path, doc_id, chunk_size, overlap)
                all_chunks.extend(chunks)
                metas.append(meta)
            except Exception as exc:  # quarantine, never crash
                quarantined.append(QuarantineRecord(
                    source_path=str(path), attempted_loader=path.suffix.lower(),
                    error=f"{type(exc).__name__}: {exc}",
                    quarantined_at=datetime.now(timezone.utc).isoformat(),
                ))

    index = HybridIndex(out / "index.sqlite")
    if dense and all_chunks:
        with console.status("[bold]embedding chunks (nomic-embed-text)…"):
            vectors = backend.embed([c.text for c in all_chunks])
        index.add_chunks(all_chunks, vectors)
    else:
        index.add_chunks(all_chunks)

    (out / "chunks.jsonl").write_text(
        "\n".join(c.model_dump_json() for c in all_chunks), encoding="utf-8")
    (out / "docmeta.json").write_text(
        json.dumps([m.model_dump() for m in metas], indent=2), encoding="utf-8")
    if quarantined:
        (out / "quarantine.json").write_text(
            json.dumps([q.model_dump() for q in quarantined], indent=2), encoding="utf-8")

    manifest = RunManifest(
        run_id=f"ingest-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        created_at=datetime.now(timezone.utc).isoformat(),
        brief_sha="n/a (ingest-only)",
        docs=[{"filename": m.filename, "sha256": m.sha256, "n_chunks": m.n_chunks} for m in metas],
        model=backend.model if dense else "none",
        config={"chunk_size": chunk_size, "overlap": overlap, "dense": dense},
        degraded_modes=degraded,
    )
    (out / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    table = Table(title=f"Ingested → {out}")
    table.add_column("doc")
    table.add_column("kind", justify="center")
    table.add_column("chunks", justify="right")
    for m in metas:
        table.add_row(m.filename, m.kind, str(m.n_chunks))
    console.print(table)
    console.print(f"[green]{len(all_chunks)} chunks[/green] indexed "
                  f"({'hybrid dense+sparse' if dense else '[yellow]sparse-only[/yellow]'})")
    for q in quarantined:
        console.print(f"[red]quarantined:[/red] {q.source_path} — {q.error}")
    for p in skipped:
        console.print(f"[dim]skipped (unsupported): {p.name}[/dim]")


@app.command()
def build(
    brief: Path = typer.Option(..., "--brief", help="One-paragraph brief file"),
    docs: Path = typer.Option(..., "--docs", help="Document folder"),
    out: Path = typer.Option(None, "--out", help="Output run folder (default runs/<timestamp>)"),
    auto: bool = typer.Option(True, "--auto/--interactive", help="Auto-resolve interview questions"),
    chunk_size: int = 900,
    overlap: int = 150,
) -> None:
    """The factory stage 1-3: interview -> requirements -> groundability -> definition."""
    from .generate import generate_agent, generate_prompt_candidates, tournament
    from .intake import build_inventory, run_groundability, run_interview, synthesize_requirements
    from .llm import Harness

    if not brief.is_file() or not docs.is_dir():
        console.print("[red]brief must be a file, docs must be a directory[/red]")
        raise typer.Exit(2)
    if out is None:
        out = Path("runs") / f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    brief_text = brief.read_text(encoding="utf-8")

    with console.status("") as status:
        status.update("[bold cyan]ingesting documents…")
        all_chunks, metas = _ingest_folder(docs, chunk_size, overlap)
        backend = OllamaBackend()
        index = HybridIndex(out / "index.sqlite")
        if backend.available():
            status.update("[bold cyan]embedding chunks…")
            vectors = backend.embed([c.text for c in all_chunks])
            index.add_chunks(all_chunks, vectors)
        else:
            index.add_chunks(all_chunks)
        inventory = build_inventory(metas, all_chunks)

        status.update("[bold cyan]interviewing the brief…")
        harness = Harness(backend)
        assumptions, _ = run_interview(harness, brief_text, inventory, auto=auto)

        status.update("[bold cyan]synthesizing requirements…")
        req = synthesize_requirements(harness, brief_text, inventory, assumptions)

        status.update("[bold cyan]probing groundability…")
        req = run_groundability(harness, index, req)

        status.update("[bold cyan]selecting tools…")
        from .generate.generator import _tool_selection
        tools = _tool_selection(harness, req, inventory)

        status.update("[bold cyan]generating prompt candidates…")
        candidates = generate_prompt_candidates(harness, req, [ToolBinding(**t) for t in tools.selected])
        winner, tourney_log = tournament(harness, req, candidates)

        status.update("[bold cyan]assembling definition…")
        definition = generate_agent(harness, req, inventory, winner, tools)

    (out / "requirements.json").write_text(req.model_dump_json(indent=2), encoding="utf-8")
    (out / "definition.json").write_text(definition.model_dump_json(indent=2), encoding="utf-8")
    (out / "chunks.jsonl").write_text("\n".join(c.model_dump_json() for c in all_chunks), encoding="utf-8")
    (out / "candidates.json").write_text(
        json.dumps([c.model_dump() for c in candidates] + [{"tournament": tourney_log}], indent=2),
        encoding="utf-8")

    console.print(f"\n[green]built:[/green] {definition.name} → [bold]{out}[/bold]")
    console.print(f"tools attached: {[t.name for t in definition.tools]}  rejected: {[t.name for t in definition.rejected_tools]}")
    gsum = req.groundability.summary()
    console.print(f"groundability: {gsum}  assumptions: {len(req.assumptions)}  questions: {len(req.clarifying_questions)}")
    for r in req.groundability.rewritten_to_refusal:
        console.print(f"[yellow]rewritten to must-refuse:[/yellow] {r.topic}")


@app.command()
def chat(
    run_dir: Path = typer.Argument(..., help="Run folder containing definition.json + index.sqlite"),
) -> None:
    """Generic runner: load ANY produced definition and talk to it."""
    from .llm import Harness
    from .runner import ForgeAgent
    from .spec import AgentDefinition

    definition = AgentDefinition.model_validate_json(
        (run_dir / "definition.json").read_text(encoding="utf-8"))
    index = HybridIndex(run_dir / "index.sqlite")
    agent = ForgeAgent(Harness(OllamaBackend()), index, definition)
    console.print(f"[bold]{definition.name}[/bold] — type your question, empty line to exit. tools: {[t.name for t in definition.tools]}")
    while True:
        try:
            question = input("\nyou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            break
        with console.status("[dim]thinking…[/dim]"):
            resp = agent.answer(question)
        if resp.refused:
            console.print(f"[yellow]agent (refused):[/yellow] {resp.answer}")
        else:
            console.print(f"agent: {resp.answer}")
        if resp.citations:
            console.print(f"[dim]citations: {', '.join(resp.citations)}[/dim]")


def _ingest_folder(docs: Path, chunk_size: int, overlap: int
                   ) -> tuple[list[Chunk], list[DocumentMeta]]:
    files = sorted(p for p in docs.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED)
    all_chunks: list[Chunk] = []
    metas: list[DocumentMeta] = []
    for i, path in enumerate(files, 1):
        try:
            chunks, meta = chunk_document(path, f"d{i:02d}", chunk_size, overlap)
            all_chunks.extend(chunks)
            metas.append(meta)
        except Exception as exc:
            console.print(f"[red]quarantined:[/red] {path.name} — {exc}")
    return all_chunks, metas


if __name__ == "__main__":
    app()
