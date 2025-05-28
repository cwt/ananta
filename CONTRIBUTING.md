# Contributing to Ananta

Thanks for your interest in contributing to **Ananta**, the command-line tool for simultaneous SSH command execution! We welcome contributions from everyone, whether you're fixing bugs, adding features, improving documentation, or suggesting ideas. This guide outlines how to get started and submit your contributions.

## Getting Started

### Prerequisites

To contribute, you'll need:

- **Python 3.10 or higher**: Ensure you have a compatible Python version installed.
- **Poetry**: Ananta uses Poetry for dependency management. Install it via:
  ```bash
  pip install poetry
  ```
- **Git**: For cloning the repository and submitting changes.
- A code editor (e.g., VSCode, PyCharm) and familiarity with Python and SSH.

### Setting Up the Development Environment

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/cwt/ananta.git
   cd ananta
   ```

2. **Install Dependencies**:
   Use Poetry to install both runtime and development dependencies:
   ```bash
   poetry install
   poetry install --with dev
   ```

3. **Verify Setup**:
   Run the test suite to ensure everything is set up correctly:
   ```bash
   ./scripts/runtest.sh  # On Unix-like systems
   ```
   ```pwsh
   .\scripts\runtest.ps1  # On Windows
   ```
   This updates dependencies, installs the project, and runs tests with coverage.

## Development Workflow

### Code Style and Formatting

Ananta follows a consistent code style enforced by **Black** and type-checked with **Mypy**:

- **Format Code**:
  Run the formatting script to apply Black with Python 3.12 target and 80-character line length:
  ```bash
  ./scripts/code-format.sh  # On Unix-like systems
  ```
  ```pwsh
  .\scripts\code-format.ps1  # On Windows
  ```

- **Type Check**:
  Verify type hints with Mypy:
  ```bash
  ./scripts/type-check.sh  # On Unix-like systems
  ```
  ```pwsh
  .\scripts\type-check.ps1  # On Windows
  ```

Always run these scripts before submitting changes to ensure compliance.

### Writing Tests

Ananta uses **Pytest** for testing, with **pytest-asyncio** for async code and **pytest-cov** for coverage. Tests are located in the `tests/` directory.

- Write tests for new features or bug fixes in the appropriate test file (e.g., `test_ananta.py` for core functionality).
- Ensure tests cover both synchronous and asynchronous code where applicable.
- Run tests with:
  ```bash
  ./scripts/runtest.sh  # On Unix-like systems
  ```
  ```pwsh
  .\scripts\runtest.ps1  # On Windows
  ```
- Aim for high test coverage, as reported by `pytest-cov`.

### Submitting Changes

1. **Create a Branch**:
   Create a branch for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Changes**:
   Implement your changes, following the code style and adding tests as needed.

3. **Run Checks and Tests**:
   Ensure your code passes formatting, type-checking, and tests:
   ```bash
   ./scripts/code-format.sh
   ./scripts/type-check.sh
   ./scripts/runtest.sh
   ```

4. **Commit Changes**:
   Write clear, concise commit messages:
   ```bash
   git commit -m "Add feature: describe your change"
   ```

5. **Push and Create a Pull Request**:
   Push your branch and open a pull request (PR) on GitHub:
   ```bash
   git push origin feature/your-feature-name
   ```
   - Link to any relevant issues in the PR description.
   - Describe the purpose of your changes and any testing performed.
   - Ensure the PR passes CI checks (formatting, type-checking, tests).

6. **Code Review**:
   Respond to feedback during the review process. Maintainers may suggest changes to align with the project’s goals.

## Contribution Types

We welcome various contributions, including:

- **Bug Fixes**: Address issues reported in the GitHub Issues tracker.
- **Features**: Propose new features via an issue before implementing.
- **Documentation**: Improve `README.md`, docstrings, or this `CONTRIBUTING.md`.
- **Performance**: Enhance performance, especially for SSH connections or async operations.
- **Tests**: Add or improve test cases to increase coverage.
- **Scripts**: Enhance the scripts in `scripts/` for better developer experience.

## Code of Conduct

Be respectful and inclusive in all interactions. We follow a [simplified open-source code of conduct](CODE_OF_CONDUCT.md), ensuring a welcoming environment for all contributors.

## Questions?

If you have questions or need help, open an issue on [GitHub](https://github.com/cwt/ananta) or reach out via the [Sourcehut mirror](https://sr.ht/~cwt/ananta/). We’re excited to have you contribute to Ananta!

---

*The MIT License applies to all contributions. See [README.md](README.md) for details.*

