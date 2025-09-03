# LLM Linter

An intelligent multi-agent linting tool powered by large language models that provides comprehensive code analysis beyond traditional static analysis tools.

## Overview

LLM Linter uses specialized AI agents to analyze your codebase across multiple dimensions:

- **Complexity Analysis** - Identifies overly long files, classes, and functions
- **Type & Documentation** - Checks Python type hints, docstrings, and comment density
- **Error Handling** - Analyzes try/except patterns and error handling quality
- **Code Duplication** - Detects duplicated code blocks across files
- **Class Design** - Evaluates class cohesion and method placement
- **File Structure** - Assesses directory organization and package structure
- **Testing Coverage** - Estimates test coverage by comparing test files to implementation
- **Security** - Flags common security anti-patterns and potential vulnerabilities

## Installation

### Prerequisites

- Python 3.13+
- OpenAI API key (set as `OPENAI_API_KEY` environment variable)

### Setup

1. Clone or download this repository
2. Install dependencies:
   ```bash
   uv sync
   ```
   or with pip:
   ```bash
   pip install openai>=1.99.6 openai-agents>=0.2.5
   ```

3. Set your OpenAI API key:
   ```bash
   export OPENAI_API_KEY="your-api-key-here"
   ```
   
   Or create a `.env` file in your project root:
   ```
   OPENAI_API_KEY=your-api-key-here
   ```

## Usage

### Basic Usage

Lint a repository with default settings:

```bash
python -m linter /path/to/your/repository
```

### Command Line Options

```bash
python -m linter [OPTIONS] REPO_PATH
```

**Arguments:**
- `REPO_PATH` - Path to the repository root to lint

**Options:**
- `--rules-path DIR` - Directory containing custom .md/.txt best-practice files
- `--prompt-overrides TEXT` - Extra guidance to augment rules
- `--format {json,human}` - Output format (default: json)
- `--mode {parallel,triage}` - Execution mode (default: parallel)
- `--indent INT` - JSON indent when using json format (default: 2)
- `--out FILE` - Write output to file instead of stdout
- `--log-level {DEBUG,INFO,WARNING,ERROR}` - Logging level (default: INFO)

### Examples

**Basic linting:**
```bash
python -m linter ./my-project
```

**Human-readable output:**
```bash
python -m linter ./my-project --format human
```

**With custom rules:**
```bash
python -m linter ./my-project --rules-path ./coding-standards
```

**Save results to file:**
```bash
python -m linter ./my-project --out lint-report.json
```

**Verbose logging:**
```bash
python -m linter ./my-project --log-level DEBUG
```

## Execution Modes

### Parallel Mode (Default)
Runs all specialized agents concurrently for faster execution. Each agent analyzes different aspects of your code simultaneously.

### Triage Mode
Uses a coordinating agent that orchestrates specialized agents sequentially. May provide more coherent analysis but takes longer.

## Custom Rules

You can provide custom coding standards by creating `.md` or `.txt` files in a directory and using the `--rules-path` option. The linter will load all text files and use them to guide the analysis.

Example rules directory structure:
```
coding-standards/
├── python-style.md
├── security-guidelines.txt
└── team-conventions.md
```

## Output Format

### JSON Output (Default)
Structured output with summary statistics and detailed issues:

```json
{
  "summary": {
    "by_agent": {
      "Complexity Lint Agent": {...},
      "Security Lint Agent": {...}
    },
    "total_issues": 42,
    "recommendations": 15
  },
  "issues": [
    {
      "rule": "function_too_long",
      "path": "src/main.py",
      "line_start": 15,
      "line_end": 85,
      "severity": "warning",
      "message": "Function 'process_data' is 71 lines (>50).",
      "recommendation": "Consider breaking this function into smaller, focused functions.",
      "code_suggestion": "def process_data():\n    # Break into: validate_input(), transform_data(), save_results()"
    }
  ]
}
```

### Human-Readable Output
Formatted text output suitable for terminal viewing:

```
=== Lint Summary ===
- total_issues: 42
- recommendations: 15

=== Issues ===
1. [warning] function_too_long - src/main.py (15-85)
   Function 'process_data' is 71 lines (>50).
   Recommendation: Consider breaking this function into smaller, focused functions.
```

## Supported Languages

- **Python** (.py) - Full analysis including AST parsing for type hints, docstrings, classes, functions
- **TypeScript/JavaScript** (.ts, .tsx, .js, .jsx) - File-level analysis, complexity, and duplication detection

## Environment Variables

The linter will automatically load environment variables from a `.env` file in the target repository root. This is useful for setting API keys on a per-project basis.

## Limitations

- Requires internet connection for LLM API calls
- Analysis quality depends on the underlying language model
- Large repositories may take significant time to analyze
- API costs scale with repository size

## Troubleshooting

**"OPENAI_API_KEY is not set" warning:**
- Set the environment variable or create a `.env` file with your API key

**Long execution times:**
- Use `--mode parallel` (default) for faster execution
- Consider analyzing smaller portions of your codebase first

**High API costs:**
- The tool includes built-in limits to prevent excessive API usage
- Monitor your OpenAI API usage dashboard

## Contributing

The linter is built with a modular agent architecture. Each analysis type is handled by a specialized agent with its own prompt and tools. See the `linter/core.py` file for agent definitions and `linter/prompts/` for agent-specific prompts.

## License

This project uses the OpenAI API and requires an API key. Please ensure you comply with OpenAI's usage policies.
