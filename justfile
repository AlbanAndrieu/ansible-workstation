# Optional compatibility entrypoint; mise remains the pinned toolchain owner.
# This recipe runs only offline contract tests and a read-only manifest audit.
agent-skills-check:
    mise run agent-skills-check
