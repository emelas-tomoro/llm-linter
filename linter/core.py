from __future__ import annotations as _annotations

import argparse
import asyncio
import json
from pathlib import Path
import os
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from agents import Agent, RunContextWrapper, Runner, TResponseInputItem, function_tool, handoff


# Reuse tools and helpers from the previous implementation by importing them from the flat module if present.
# If this package is used standalone, we define light wrappers here to avoid duplication.
from .tools import (
    LinterContext,
    LinterInput,
    LintIssue,
    LintReport,
    load_rules_text,
    scan_repo_index,
    check_complexity_lengths,
    check_typing_and_docs,
    check_error_handling,
    check_code_duplication,
    check_class_cohesion,
    check_file_structure,
    check_tests,
    check_security_heuristics,
    read_code_snippet,
    create_linter_context,
)


def _read_prompt(name: str) -> str:
    p = Path(__file__).with_name("prompts") / f"{name}.md"
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _agent_instructions_with_prompt(default_header: str, prompt_name: str):
    def _fn(run_context: RunContextWrapper[LinterContext], agent: Agent[LinterContext]) -> str:
        rules = (run_context.context.rules_text or "").strip()
        rules_section = f"\nBest-practice guidelines to adhere to:\n{rules}\n" if rules else ""
        prompt = _read_prompt(prompt_name)
        return default_header + "\n\n" + prompt + rules_section
    return _fn


def _get_model_config(cli_specialist: Optional[str] = None, cli_triage: Optional[str] = None, cli_recommendations: Optional[str] = None) -> Dict[str, str]:
    """Get model configuration from CLI args, environment variables, or defaults (in that order)."""
    return {
        "specialist_model": cli_specialist or os.getenv("LLM_LINTER_SPECIALIST_MODEL", "gpt-5-mini-2025-08-07"),
        "triage_model": cli_triage or os.getenv("LLM_LINTER_TRIAGE_MODEL", "gpt-5-2025-08-07"),
        "recommendations_model": cli_recommendations or os.getenv("LLM_LINTER_RECOMMENDATIONS_MODEL", "gpt-5-mini-2025-08-07"),
    }


def _extract_final_output(result: Any) -> str:
    """Best-effort extraction of final text from Runner result across API variants."""
    if isinstance(result, str):
        return result
    # Method form
    fo = getattr(result, "final_output", None)
    if callable(fo):
        try:
            return fo()  # type: ignore[no-any-return]
        except TypeError:
            pass
    # Property form
    if isinstance(fo, str):
        return fo
    # Other common attributes
    for attr in ("final", "text", "content"):
        val = getattr(result, attr, None)
        if isinstance(val, str):
            return val
    # Fallback
    return str(result)


def _create_agents(models: Dict[str, str]) -> Dict[str, Agent[LinterContext]]:
    """Create agents with the specified model configuration."""
    
    # Specialized agents with per-agent prompts
    duplication_agent = Agent[LinterContext](
        name="Duplication Lint Agent",
        model=models["specialist_model"],
        handoff_description="Detects duplicated code blocks across the repository.",
        instructions=_agent_instructions_with_prompt("Use your tools to analyze duplication and return compact JSON.", "duplication"),
        tools=[check_code_duplication, scan_repo_index, load_rules_text],
    )

    design_agent = Agent[LinterContext](
        name="Design Lint Agent",
        model=models["specialist_model"],
        handoff_description="Evaluates class cohesion and placement of methods.",
        instructions=_agent_instructions_with_prompt("Use your tools to check class cohesion and return compact JSON.", "design"),
        tools=[check_class_cohesion, scan_repo_index, load_rules_text],
    )

    structure_agent = Agent[LinterContext](
        name="Structure Lint Agent",
        model=models["specialist_model"],
        handoff_description="Assesses file/directory structure.",
        instructions=_agent_instructions_with_prompt("Use your tools to assess structure and return compact JSON.", "structure"),
        tools=[check_file_structure, scan_repo_index, load_rules_text],
    )

    complexity_agent = Agent[LinterContext](
        name="Complexity Lint Agent",
        model=models["specialist_model"],
        handoff_description="Flags long files, classes, and functions.",
        instructions=_agent_instructions_with_prompt("Use your tools to flag long code and return compact JSON.", "complexity"),
        tools=[check_complexity_lengths, scan_repo_index, load_rules_text],
    )

    typing_docs_agent = Agent[LinterContext](
        name="Typing & Docs Lint Agent",
        model=models["specialist_model"],
        handoff_description="Checks Python type hints, docstrings, and comment density.",
        instructions=_agent_instructions_with_prompt("Use your tools to check typing/docs and return compact JSON.", "typing_docs"),
        tools=[check_typing_and_docs, scan_repo_index, load_rules_text],
    )

    error_handling_agent = Agent[LinterContext](
        name="Error Handling Lint Agent",
        model=models["specialist_model"],
        handoff_description="Checks for proper error handling patterns.",
        instructions=_agent_instructions_with_prompt("Use your tools to check error handling and return compact JSON.", "error_handling"),
        tools=[check_error_handling, scan_repo_index, load_rules_text],
    )

    testing_agent = Agent[LinterContext](
        name="Testing Lint Agent",
        model=models["specialist_model"],
        handoff_description="Estimates test coverage and testing hygiene.",
        instructions=_agent_instructions_with_prompt("Use your tools to check tests and return compact JSON.", "testing"),
        tools=[check_tests, scan_repo_index, load_rules_text],
    )

    security_agent = Agent[LinterContext](
        name="Security Lint Agent",
        model=models["specialist_model"],
        handoff_description="Flags common security smell patterns.",
        instructions=_agent_instructions_with_prompt("Use your tools to check security smells and return compact JSON.", "security"),
        tools=[check_security_heuristics, scan_repo_index, load_rules_text],
    )


def _recommendations_instructions(run_context: RunContextWrapper[LinterContext], agent: Agent[LinterContext]) -> str:
    prompt = _read_prompt("recommendations")
    return (
        "You generate concise, actionable recommendations for the provided lint issues.\n"
        "Return ONLY JSON with 'recommendations': [{path, line_start, rule, text, code_suggestion?}].\n"
        "Keep each text concise; include code_suggestion only if short and necessary.\n"
        + prompt
    )


    recommendations_agent = Agent[LinterContext](
        name="Recommendations Agent",
        model=models["recommendations_model"],
        handoff_description="Generates actionable code recommendations for selected issues.",
        instructions=_recommendations_instructions,
        tools=[read_code_snippet],
    )


def _triage_instructions(run_context: RunContextWrapper[LinterContext], agent: Agent[LinterContext]) -> str:
    ctx = run_context.context
    base = ctx.repo_path
    return (
        "You are the Linter Triage Agent. Orchestrate specialized lint agents via handoffs.\n"
        "1) Load rules if provided. 2) Run each specialized agent as needed. 3) Aggregate their JSON tool outputs into a single structured report.\n"
        f"Target repository root: {base}\n"
        "Important: Output a compact JSON object with fields 'summary' and 'issues'. Merge duplicate issues."
    )


async def _on_linter_handoff(context: RunContextWrapper[LinterContext], input: LinterInput) -> None:
    context.context.repo_path = input.repo_path
    if input.rules_path:
        # Preload rules
        base = Path(input.rules_path)
        if base.exists():
            blobs: List[str] = []
            for ext in (".md", ".txt"):
                for p in base.rglob(f"*{ext}"):
                    try:
                        blobs.append(p.read_text(encoding="utf-8"))
                    except Exception:
                        pass
            rules = "\n\n".join(b for b in blobs if b.strip())
            context.context.rules_text = rules
    if input.prompt_overrides:
        context.context.rules_text = ((context.context.rules_text or "") + "\n\n" + input.prompt_overrides).strip()


    linter_triage_agent = Agent[LinterContext](
        name="Linter Triage Agent",
        model=models["triage_model"],
        handoff_description="Orchestrates repository linting across specialized agents and returns a consolidated report.",
        instructions=_triage_instructions,
        handoffs=[
            handoff(agent=duplication_agent, on_handoff=_on_linter_handoff, input_type=LinterInput),
            handoff(agent=design_agent, on_handoff=_on_linter_handoff, input_type=LinterInput),
            handoff(agent=structure_agent, on_handoff=_on_linter_handoff, input_type=LinterInput),
            handoff(agent=complexity_agent, on_handoff=_on_linter_handoff, input_type=LinterInput),
            handoff(agent=typing_docs_agent, on_handoff=_on_linter_handoff, input_type=LinterInput),
            handoff(agent=error_handling_agent, on_handoff=_on_linter_handoff, input_type=LinterInput),
            handoff(agent=testing_agent, on_handoff=_on_linter_handoff, input_type=LinterInput),
            handoff(agent=security_agent, on_handoff=_on_linter_handoff, input_type=LinterInput),
        ],
        tools=[scan_repo_index, load_rules_text],
    )

    return {
        "duplication": duplication_agent,
        "design": design_agent,
        "structure": structure_agent,
        "complexity": complexity_agent,
        "typing_docs": typing_docs_agent,
        "error_handling": error_handling_agent,
        "testing": testing_agent,
        "security": security_agent,
        "recommendations": recommendations_agent,
        "triage": linter_triage_agent,
    }


async def run_linter(repo_path: str, rules_path: Optional[str] = None, prompt_overrides: Optional[str] = None, models: Optional[Dict[str, str]] = None) -> LintReport:
    logger = logging.getLogger("linter")
    logger.info("Starting linter run")
    logger.debug("Inputs: repo_path=%s, rules_path=%s, prompt_overrides_len=%s", repo_path, rules_path, (len(prompt_overrides) if prompt_overrides else 0))
    
    if models is None:
        models = _get_model_config()
    
    agents = _create_agents(models)
    ctx = create_linter_context(repo_path, rules_path, prompt_overrides)
    seed: List[TResponseInputItem] = [
        {"role": "user", "content": "Perform a full repository lint and return a JSON report with 'summary' and 'issues'."}
    ]
    result = await Runner.run(agents["triage"], seed, context=ctx)
    txt = _extract_final_output(result)
    try:
        data = json.loads(txt)
        summary = data.get("summary", {})
        issues_raw = data.get("issues", [])
        issues = [LintIssue(**i) if isinstance(i, dict) else LintIssue(rule="ad_hoc", path="", message=str(i)) for i in issues_raw]
        logger.info("Linter completed successfully: %d issues", len(issues))
        return LintReport(summary=summary, issues=issues)
    except Exception:
        logger.warning("Final output was not valid JSON; returning raw text in issue", exc_info=False)
        return LintReport(summary={"note": "LLM returned non-JSON output"}, issues=[LintIssue(rule="unparsed_output", path="", message=txt)])


async def run_linter_parallel(repo_path: str, rules_path: Optional[str] = None, prompt_overrides: Optional[str] = None, models: Optional[Dict[str, str]] = None) -> LintReport:
    """Run each specialized lint agent concurrently and aggregate results."""
    logger = logging.getLogger("linter")
    logger.info("Starting parallel linter run")
    
    if models is None:
        models = _get_model_config()
    
    agent_dict = _create_agents(models)
    base_ctx = create_linter_context(repo_path, rules_path, prompt_overrides)
    seed: List[TResponseInputItem] = [
        {"role": "user", "content": "Run your tools and return a compact JSON with 'summary' and 'issues'. Keep outputs concise."}
    ]

    agents: List[Agent[LinterContext]] = [
        agent_dict["duplication"],
        agent_dict["design"],
        agent_dict["structure"],
        agent_dict["complexity"],
        agent_dict["typing_docs"],
        agent_dict["error_handling"],
        agent_dict["testing"],
        agent_dict["security"],
    ]

    async def _run_one(agent: Agent[LinterContext]):
        # Give each agent an isolated context copy
        agent_ctx = base_ctx.model_copy(deep=True)
        logger.debug("Running agent %s", agent.name)
        result = await Runner.run(agent, seed, context=agent_ctx)
        txt = _extract_final_output(result)
        try:
            data = json.loads(txt)
            return agent.name, data
        except Exception:
            logger.warning("Agent %s returned non-JSON output", agent.name)
            return agent.name, {
                "summary": {"note": "non_json_output"},
                "issues": [{"rule": "unparsed_output", "path": "", "message": txt, "severity": "info"}],
            }

    results = await asyncio.gather(*[_run_one(a) for a in agents], return_exceptions=True)

    by_agent: Dict[str, Any] = {}
    issues: List[LintIssue] = []
    for res in results:
        if isinstance(res, Exception):
            # Capture exception as an issue
            issues.append(LintIssue(rule="agent_exception", path="", message=str(res), severity="error"))
            continue
        agent_name, data = res
        by_agent[agent_name] = data.get("summary", {})
        for i in data.get("issues", []) or []:
            try:
                issues.append(LintIssue(**i))
            except Exception:
                issues.append(LintIssue(rule="ad_hoc", path="", message=str(i)))

    summary: Dict[str, Any] = {
        "by_agent": by_agent,
        "total_issues": len(issues),
    }
    logger.info("Parallel linter completed: %d issues across %d agents", len(issues), len(agents))

    # Optional recommendations pass: take a small subset of issues (e.g., top 100 by severity) and enrich
    def _severity_rank(s: str) -> int:
        return {"error": 0, "warning": 1, "info": 2}.get(s, 3)

    top_issues = sorted(issues, key=lambda i: (_severity_rank(i.severity), i.path))[:100]
    if top_issues:
        seed: List[TResponseInputItem] = [
            {
                "role": "user",
                "content": json.dumps({
                    "issues": [
                        {
                            "rule": i.rule,
                            "path": i.path,
                            "line_start": i.line_start,
                            "line_end": i.line_end,
                            "severity": i.severity,
                            "message": i.message,
                        }
                        for i in top_issues
                    ]
                }),
            }
        ]
        try:
            rec_result = await Runner.run(agent_dict["recommendations"], seed, context=base_ctx)
            rec_txt = _extract_final_output(rec_result)
            rec_obj = json.loads(rec_txt)
            recs = rec_obj.get("recommendations", []) or []
            # Build index for quick merge
            key_to_issue: Dict[tuple, List[int]] = {}
            for idx, i in enumerate(issues):
                key = (i.path, i.line_start, i.rule)
                key_to_issue.setdefault(key, []).append(idx)
            for r in recs:
                key = (r.get("path"), r.get("line_start"), r.get("rule"))
                text = r.get("text")
                if not text:
                    continue
                code_suggestion = r.get("code_suggestion")
                for idx in key_to_issue.get(key, []):
                    issues[idx].recommendation = text
                    if code_suggestion:
                        issues[idx].code_suggestion = code_suggestion
            summary["recommendations"] = len(recs)
        except Exception as e:
            logger.warning("Recommendations pass failed: %s", e)

    return LintReport(summary=summary, issues=issues)


def main():
    def _load_env_from_repo(root: str) -> None:
        # Prefer python-dotenv if available; fallback to simple parser
        try:
            from dotenv import load_dotenv as _load_dotenv  # type: ignore
        except Exception:
            _load_dotenv = None  # type: ignore

        env_path = Path(root).resolve() / ".env"
        if _load_dotenv is not None:
            # Load system .env plus repo .env; repo takes precedence with override=True
            _load_dotenv(override=False)
            if env_path.exists():
                _load_dotenv(dotenv_path=str(env_path), override=True)
            return

        # Fallback: minimal .env loader
        if not env_path.exists():
            return
        try:
            content = env_path.read_text(encoding="utf-8")
        except Exception:
            return
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            key, val = line.split('=', 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val and key not in os.environ:
                os.environ[key] = val

    parser = argparse.ArgumentParser(description="Run multi-agent linter on a repository")
    parser.add_argument("repo_path", help="Path to the repository root to lint")
    parser.add_argument("--rules-path", dest="rules_path", help="Directory containing .md/.txt best-practice files", default=None)
    parser.add_argument("--prompt-overrides", dest="prompt_overrides", help="Extra guidance to augment rules", default=None)
    parser.add_argument("--format", choices=["json", "human"], default="json", help="Output format")
    parser.add_argument("--mode", choices=["parallel", "triage"], default="parallel", help="Execution mode")
    parser.add_argument("--indent", type=int, default=2, help="JSON indent (when --format=json)")
    parser.add_argument("--out", dest="out_path", default=None, help="Write output to a file (prints to stdout if omitted)")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO", help="Logging level")
    parser.add_argument("--specialist-model", dest="specialist_model", default=None, help="Model for specialist agents (overrides LLM_LINTER_SPECIALIST_MODEL)")
    parser.add_argument("--triage-model", dest="triage_model", default=None, help="Model for triage agent (overrides LLM_LINTER_TRIAGE_MODEL)")
    parser.add_argument("--recommendations-model", dest="recommendations_model", default=None, help="Model for recommendations agent (overrides LLM_LINTER_RECOMMENDATIONS_MODEL)")
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logger = logging.getLogger("linter")
    logger.debug("Logger initialized at level %s", args.log_level)

    # Load .env (including OPENAI_API_KEY) from repo root if present
    _load_env_from_repo(args.repo_path)
    if os.environ.get("OPENAI_API_KEY"):
        logger.debug("OPENAI_API_KEY present in environment")
    else:
        logger.warning("OPENAI_API_KEY is not set; linter will fail to call models")
    
    # Get model configuration from CLI args, env vars, or defaults
    models = _get_model_config(args.specialist_model, args.triage_model, args.recommendations_model)
    logger.info("Model configuration: specialist=%s, triage=%s, recommendations=%s", 
                models["specialist_model"], models["triage_model"], models["recommendations_model"])

    if args.mode == "parallel":
        report = asyncio.run(run_linter_parallel(args.repo_path, args.rules_path, args.prompt_overrides, models))
    else:
        report = asyncio.run(run_linter(args.repo_path, args.rules_path, args.prompt_overrides, models))

    # Render output
    if args.format == "json":
        output_str = report.model_dump_json(indent=args.indent)
    else:
        lines = ["=== Lint Summary ==="]
        for k, v in report.summary.items():
            lines.append(f"- {k}: {v}")
        lines.append("\n=== Issues ===")
        if not report.issues:
            lines.append("No issues found.")
        else:
            for i, iss in enumerate(report.issues, 1):
                loc = f" ({iss.line_start}-{iss.line_end})" if iss.line_start else ""
                lines.append(f"{i}. [{iss.severity}] {iss.rule} - {iss.path}{loc}\n   {iss.message}")
                if iss.recommendation:
                    lines.append(f"   Recommendation: {iss.recommendation}")
                if iss.code_suggestion:
                    lines.append("   Code Suggestion:\n" + "\n".join("     " + ln for ln in iss.code_suggestion.splitlines()))
        output_str = "\n".join(lines)

    if args.out_path:
        Path(args.out_path).write_text(output_str, encoding="utf-8")
        logger.info("Wrote linter output to %s", args.out_path)
    else:
        print(output_str)


if __name__ == "__main__":
    main()


