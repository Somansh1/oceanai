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
from .evaltypes import CostLedger, IterationScorecard, RunManifest
from .ingest import SUPPORTED, chunk_document
from .llm import Harness, OllamaBackend
from .retrieve import HybridIndex


def _load_ledger(run_dir: Path) -> CostLedger:
    p = run_dir / "ledger.json"
    if p.exists():
        try:
            return CostLedger.model_validate_json(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return CostLedger()


def _apply_pair_consistency(harness: Harness, cases: list, results: list) -> None:
    from .evaltypes import CaseKind
    from .judge import pair_consistency
    by_id = {r.case_id: r for r in results}
    case_by_id = {c.id: c for c in cases}
    for c in cases:
        if c.kind == CaseKind.REPHRASE_A and c.rephrase_pair in by_id:
            ok = pair_consistency(harness, by_id[c.id], by_id[c.rephrase_pair])
            if ok is False:
                by_id[c.id].judge_unstable = True
                by_id[c.rephrase_pair].judge_unstable = True
            note = f"pair_consistent={ok}"
            c_note = case_by_id[c.id].notes or ""
            suffix = note + (" (FAIL)" if ok is False else "")
            if suffix not in c_note:
                case_by_id[c.id].notes = (c_note + " | " if c_note else "") + suffix

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
    requirements: Path = typer.Option(None, "--requirements", help="Pre-approved RequirementsDoc JSON (skips intake)"),
    chunk_size: int = 900,
    overlap: int = 150,
) -> Path:
    """The factory stage 1-3: interview -> requirements -> groundability -> definition."""
    from .generate import derive_retrieval_config, generate_agent, generate_prompt_candidates, tournament
    from .intake import (build_inventory, interactive_checkpoint, run_groundability,
                         run_interview, synthesize_requirements)
    from .spec import RequirementsDoc, ToolBinding

    if not brief.is_file() or not docs.is_dir():
        console.print("[red]brief must be a file, docs must be a directory[/red]")
        raise typer.Exit(2)
    if out is None:
        out = Path("runs") / f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    brief_text = brief.read_text(encoding="utf-8")

    # idempotent rebuild: a stale index from a previous build collides with
    # vec0 virtual tables (INSERT OR REPLACE is not honored by sqlite-vec)
    stale_index = out / "index.sqlite"
    if stale_index.exists():
        stale_index.unlink()

    backend = OllamaBackend()
    ledger = CostLedger()
    harness = Harness(backend, ledger=ledger)
    dense = backend.available()
    degraded = [] if dense else ["dense retrieval unavailable (ollama down) — BM25-only index"]

    with console.status("") as status:
        status.update("[bold cyan]ingesting documents…")
        all_chunks, metas = _ingest_folder(docs, chunk_size, overlap)
        index = HybridIndex(out / "index.sqlite")
        if dense and all_chunks:
            status.update("[bold cyan]embedding chunks…")
            vectors = backend.embed([c.text for c in all_chunks])
            index.add_chunks(all_chunks, vectors)
        else:
            index.add_chunks(all_chunks)
        inventory = build_inventory(metas, all_chunks)

        if requirements is not None and requirements.is_file():
            req = RequirementsDoc.model_validate_json(requirements.read_text(encoding="utf-8"))
        else:
            if auto:
                status.update("[bold cyan]interviewing the brief…")
                assumptions, _ = run_interview(harness, brief_text, inventory, auto=True)
            else:
                status.stop()
                assumptions, _ = run_interview(harness, brief_text, inventory, auto=False)
                status.start()

            status.update("[bold cyan]synthesizing requirements…")
            req = synthesize_requirements(harness, brief_text, inventory, assumptions)

        status.update("[bold cyan]selecting tools…")
        from .generate.generator import _tool_selection
        cwd_resolved = Path.cwd().resolve()
        data_files = []
        for p in sorted(docs.rglob("*")):
            if p.is_file() and p.suffix.lower() in (".csv", ".xlsx"):
                rp = p.resolve()
                data_files.append(
                    rp.relative_to(cwd_resolved).as_posix()
                    if rp.is_relative_to(cwd_resolved)
                    else str(rp)
                )
        tools = _tool_selection(harness, req, inventory, data_files)
        attached_names = [t["name"] for t in tools.selected]

        if requirements is None:
            status.update("[bold cyan]probing groundability…")
            req = run_groundability(harness, index, req, attached_tools=attached_names)

            if not auto:
                status.stop()
                req = interactive_checkpoint(req)
                status.start()

        status.update("[bold cyan]generating prompt candidates…")
        candidates = generate_prompt_candidates(harness, req, [ToolBinding(**t) for t in tools.selected])
        winner, tourney_log = tournament(harness, req, candidates)

        status.update("[bold cyan]assembling definition…")
        retrieval = derive_retrieval_config(all_chunks, metas, chunk_size, overlap, dense)
        definition = generate_agent(harness, req, inventory, winner, tools, retrieval=retrieval)

    (out / "requirements.json").write_text(req.model_dump_json(indent=2), encoding="utf-8")
    (out / "definition.json").write_text(definition.model_dump_json(indent=2), encoding="utf-8")
    (out / "chunks.jsonl").write_text("\n".join(c.model_dump_json() for c in all_chunks), encoding="utf-8")
    (out / "docmeta.json").write_text(json.dumps([m.model_dump() for m in metas], indent=2), encoding="utf-8")
    (out / "candidates.json").write_text(
        json.dumps([c.model_dump() for c in candidates] + [{"tournament": tourney_log}], indent=2),
        encoding="utf-8")
    (out / "ledger.json").write_text(harness.ledger.model_dump_json(indent=2), encoding="utf-8")
    prompt_hashes = {
        p.stem: sha256_text(p.read_text(encoding="utf-8"))
        for p in sorted(harness.prompts.directory.glob("*.md"))
    }
    manifest = RunManifest(
        run_id=out.name,
        created_at=datetime.now(timezone.utc).isoformat(),
        brief_sha=sha256_text(brief_text),
        docs=[{"filename": m.filename, "sha256": m.sha256, "n_chunks": m.n_chunks} for m in metas],
        model=backend.model if dense else "none",
        prompt_hashes=prompt_hashes,
        config={"chunk_size": chunk_size, "overlap": overlap, "dense": dense, "auto": auto},
        degraded_modes=degraded,
    )
    (out / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    console.print(f"\n[green]built:[/green] {definition.name} → [bold]{out}[/bold]")
    console.print(f"tools attached: {[t.name for t in definition.tools]}  rejected: {[t.name for t in definition.rejected_tools]}")
    gsum = req.groundability.summary()
    console.print(f"groundability: {gsum}  assumptions: {len(req.assumptions)}  questions: {len(req.clarifying_questions)}")
    for r in req.groundability.rewritten_to_refusal:
        console.print(f"[yellow]rewritten to must-refuse:[/yellow] {r.topic}")
    return out


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
    agent = ForgeAgent(Harness(OllamaBackend()), index, definition, run_dir=run_dir)
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


@app.command()
def evaluate(
    run_dir: Path = typer.Argument(..., help="Run folder (definition.json + index.sqlite)"),
    compile_only: bool = typer.Option(False, "--compile-only", help="Only build the eval set"),
    definition: Path = typer.Option(None, "--definition", help="Alternate definition (e.g. human baseline)"),
) -> None:
    """Compile evals from the corpus, run them, judge them, score honestly."""
    from .evals import compile_evalset
    from .evaltypes import EvalCase
    from .judge import build_scorecard, judge_case
    from .runner import ForgeAgent
    from .spec import AgentDefinition, RequirementsDoc

    if definition is not None:
        defn_path = definition
    else:
        defn_path = run_dir / "definition.json"
    definition_obj = AgentDefinition.model_validate_json(
        defn_path.read_text(encoding="utf-8"))
    req = RequirementsDoc.model_validate_json(
        (run_dir / "requirements.json").read_text(encoding="utf-8"))
    index = HybridIndex(run_dir / "index.sqlite")
    backend = OllamaBackend()
    harness = Harness(backend, ledger=_load_ledger(run_dir))
    agent = ForgeAgent(harness, index, definition_obj, run_dir=run_dir)

    eval_path = run_dir / "evalset.jsonl"
    if not eval_path.exists():
        with console.status("[bold cyan]compiling eval set from documents…"):
            cases = compile_evalset(harness, index, req)
        eval_path.write_text("\n".join(c.model_dump_json() for c in cases), encoding="utf-8")
        console.print(f"[green]compiled {len(cases)} eval cases[/green] → {eval_path}")
    else:
        cases = [EvalCase.model_validate_json(line) for line in
                 eval_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        console.print(f"loaded {len(cases)} existing eval cases")
    if compile_only:
        (run_dir / "ledger.json").write_text(harness.ledger.model_dump_json(indent=2), encoding="utf-8")
        return

    results = []
    kinds = {c.id: c.kind for c in cases}
    case_by_id = {c.id: c for c in cases}
    with console.status("") as status:
        for i, case in enumerate(cases, 1):
            status.update(f"[bold cyan]evaluating {case.id} ({case.kind.value}) [{i}/{len(cases)}]")
            resp = agent.answer(case.question)
            results.append(judge_case(harness, index, case, resp))

        _apply_pair_consistency(harness, cases, results)
        eval_path.write_text("\n".join(c.model_dump_json() for c in cases), encoding="utf-8")

    scorecard = build_scorecard(results, cases, iteration=definition_obj.iteration)
    if definition is not None:
        out_prefix = definition.parent.name
        (run_dir / f"results_{out_prefix}.jsonl").write_text(
            "\n".join(r.model_dump_json() for r in results), encoding="utf-8")
        (run_dir / f"scorecard_{out_prefix}.json").write_text(
            scorecard.model_dump_json(indent=2), encoding="utf-8")
    else:
        (run_dir / "results.jsonl").write_text(
            "\n".join(r.model_dump_json() for r in results), encoding="utf-8")
        (run_dir / "scorecard.json").write_text(scorecard.model_dump_json(indent=2), encoding="utf-8")
        (run_dir / "ledger.json").write_text(
            harness.ledger.model_dump_json(indent=2), encoding="utf-8")

    table = Table(title=f"Scorecard — {definition_obj.name} (iteration {definition_obj.iteration})")
    for col in ("passed", "total", "score", "95% CI", "top failures"):
        table.add_column(col, justify="center")
    top_fail = ", ".join(f"{k}:{v}" for k, v in sorted(scorecard.by_failure.items(),
                                                       key=lambda kv: -kv[1])[:3]) or "—"
    table.add_row(str(scorecard.passed), str(scorecard.total),
                  f"{scorecard.score:.0%}", f"[{scorecard.wilson_low:.0%}, {scorecard.wilson_high:.0%}]",
                  top_fail)
    console.print(table)
    for r in results:
        if not r.passed:
            c = case_by_id.get(r.case_id)
            console.print(f"[red]FAIL[/red] {r.case_id} ({kinds.get(r.case_id, '?').value if kinds.get(r.case_id) else '?'})"
                          f" → {r.failure_class.value if r.failure_class else 'unclassified'}: {c.question[:80] if c else ''}")


@app.command()
def optimize(
    run_dir: Path = typer.Argument(..., help="Run folder (definition + evalset + index)"),
    max_iterations: int = typer.Option(3, "--max-iterations"),
    min_gain: float = typer.Option(0.03, "--min-gain", help="Early-stop marginal-gain threshold"),
    skip_tournament: bool = typer.Option(False, "--skip-tournament"),
    max_tokens: int | None = typer.Option(None, "--max-tokens", help="Optional token budget cap"),
    max_latency_s: int | None = typer.Option(None, "--max-latency-s", help="Optional model latency cap (seconds)"),
) -> None:
    """The critic-optimizer loop: triage -> ONE surgical patch -> re-eval, logged."""
    from .critic import optimize as run_optimize
    from .evaltypes import CaseResult, EvalCase
    from .judge import build_scorecard, judge_case
    from .runner import ForgeAgent
    from .spec import AgentDefinition

    definition = AgentDefinition.model_validate_json(
        (run_dir / "definition.json").read_text(encoding="utf-8"))
    index = HybridIndex(run_dir / "index.sqlite")
    harness = Harness(OllamaBackend(), ledger=_load_ledger(run_dir))
    cases = [EvalCase.model_validate_json(line) for line in
             (run_dir / "evalset.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    def evaluator(defn: AgentDefinition, case_subset: list | None = None
                  ) -> tuple[list[CaseResult], "IterationScorecard"]:
        agent = ForgeAgent(harness, index, defn, run_dir=run_dir)
        active = case_subset if case_subset is not None else cases
        results = []
        for case in active:
            resp = agent.answer(case.question)
            results.append(judge_case(harness, index, case, resp))
        return results, build_scorecard(results, active, iteration=defn.iteration)

    candidates = None
    if not skip_tournament and (run_dir / "candidates.json").exists():
        raw = json.loads((run_dir / "candidates.json").read_text(encoding="utf-8"))
        cand_list = [c for c in raw if isinstance(c, dict) and "system_prompt" in c][:3]
        candidates = [
            AgentDefinition(
                name=c.get("name", f"candidate-{i}"), system_prompt=c["system_prompt"],
                requirements_digest=definition.requirements_digest,
                retrieval=definition.retrieval,
                tools=definition.tools, rejected_tools=definition.rejected_tools,
                output_contract=definition.output_contract,
                refusal_policy=definition.refusal_policy)
            for i, c in enumerate(cand_list, 1)]

    with console.status("[bold cyan]optimizing…"):
        result = run_optimize(
            evaluator, definition, cases, candidates=candidates,
            max_iterations=max_iterations, min_gain=min_gain,
            ledger=harness.ledger, max_tokens=max_tokens,
            max_latency_ms=(max_latency_s * 1000 if max_latency_s is not None else None),
        )
    # the tournament winner is the agent now — it carries the agent's name;
    # candidate identities stay in the tournament log
    result.definition.name = definition.name

    (run_dir / "definition.json").write_text(
        result.definition.model_dump_json(indent=2), encoding="utf-8")
    iterations_blob = {
        "entries": [
            {"scorecard": e.scorecard.model_dump(),
             "patches": [p.model_dump() for p in e.patches], "note": e.note}
            for e in result.entries],
        "tournament_log": result.tournament_log,
        "stopped_early": result.stopped_early,
        "budget_exhausted": result.budget_exhausted,
    }
    (run_dir / "iterations.json").write_text(
        json.dumps(iterations_blob, indent=2), encoding="utf-8")
    # final refresh: reuse final results from optimize (or run if empty) + pair consistency
    if result.final_results:
        final_results = result.final_results
    else:
        final_results, _ = evaluator(result.definition)
    _apply_pair_consistency(harness, cases, final_results)
    final_scorecard = build_scorecard(final_results, cases, iteration=result.definition.iteration)
    (run_dir / "evalset.jsonl").write_text(
        "\n".join(c.model_dump_json() for c in cases), encoding="utf-8")
    (run_dir / "results.jsonl").write_text(
        "\n".join(r.model_dump_json() for r in final_results), encoding="utf-8")
    (run_dir / "scorecard.json").write_text(
        final_scorecard.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "ledger.json").write_text(
        harness.ledger.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"\n[green]optimization complete:[/green] {final_scorecard.passed}/{final_scorecard.total} "
                  f"({final_scorecard.score:.0%}, CI [{final_scorecard.wilson_low:.0%}, {final_scorecard.wilson_high:.0%}]) "
                  f"after {len(result.entries)} evaluated steps"
                  + (" [yellow](stopped early)[/yellow]" if result.stopped_early else ""))
    for e in result.entries:
        for p in e.patches:
            console.print(f"  iter {p.iteration}: {p.failure_class.value} → {p.change[:80]} "
                          f"[{p.score_before:.0%} → {p.score_after:.0%}]")


@app.command()
def report(run_dir: Path = typer.Argument(..., help="Run folder")) -> None:
    """Build the honest markdown report from a run's artifacts."""
    from .report import build_report

    text = build_report(run_dir)
    out = run_dir / "report.md"
    out.write_text(text, encoding="utf-8")
    console.print(f"[green]report written:[/green] {out} ({len(text)} chars)")


@app.command()
def run(
    brief: Path = typer.Option(..., "--brief", help="One-paragraph brief file"),
    docs: Path = typer.Option(..., "--docs", help="Document folder"),
    out: Path = typer.Option(None, "--out", help="Output run folder (default runs/<timestamp>)"),
    auto: bool = typer.Option(True, "--auto/--interactive", help="Unattended mode vs interactive checkpoint"),
    max_iterations: int = typer.Option(3, "--max-iterations"),
    min_gain: float = typer.Option(0.03, "--min-gain"),
    skip_tournament: bool = typer.Option(False, "--skip-tournament"),
    max_tokens: int | None = typer.Option(None, "--max-tokens"),
    max_latency_s: int | None = typer.Option(None, "--max-latency-s"),
    chunk_size: int = 900,
    overlap: int = 150,
) -> None:
    """Unattended full factory pipeline: build -> compile evals -> optimize -> report."""
    run_dir = build(
        brief=brief, docs=docs, out=out, auto=auto, requirements=None,
        chunk_size=chunk_size, overlap=overlap,
    )
    evaluate(run_dir=run_dir, compile_only=True, definition=None)
    optimize(
        run_dir=run_dir, max_iterations=max_iterations, min_gain=min_gain,
        skip_tournament=skip_tournament, max_tokens=max_tokens, max_latency_s=max_latency_s,
    )
    report(run_dir=run_dir)


@app.command()
def regression(
    run_dir: Path = typer.Argument(..., help="Run folder with definition + evalset"),
    docs: Path = typer.Option(..., "--docs", help="Document folder (current state)"),
) -> None:
    """Docs changed? Re-run the old eval set, report regressions and recoveries."""
    from .regression import run_regression

    text = run_regression(run_dir, docs)
    console.print(f"[green]regression report written:[/green] {run_dir}/regression/regression.md "
                  f"({len(text)} chars)")


if __name__ == "__main__":
    app()

