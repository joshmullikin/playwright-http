# Contributing to playwright-http

Thanks for your interest in contributing! This document outlines how to get started.

## Getting Started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/playwright-http.git
   cd playwright-http
   ```

3. Set up the development environment:
   ```bash
   uv sync
   uv run playwright install chromium firefox
   ```

4. Create a branch for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development

### Running the Server

```bash
uv run uvicorn executor.main:app --reload --port 8932
```

### Running Tests

```bash
uv run pytest
```

### Code Style

- Follow PEP 8 guidelines
- Use type hints where possible
- Keep functions focused and well-documented

## Pull Request Process

1. Ensure tests pass locally
2. Update documentation if adding new features
3. Keep commits focused and well-described
4. Open a PR against the `main` branch

## Adding New Browser Actions

To add a new action:

1. Add the handler function in `executor/actions.py`
2. Register it in the `ACTION_HANDLERS` dictionary
3. Update the README with the new action
4. Add tests if applicable

## Reporting Issues

When reporting issues, please include:

- Python version (`python --version`)
- Operating system
- Steps to reproduce
- Expected vs actual behavior
- Relevant error messages or logs

## Questions?

Open an issue with the "question" label.
