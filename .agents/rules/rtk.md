# Token Compression Rule

When executing shell commands:
- ALWAYS use `pyrtk`'s `rtk_run_command` tool instead of the default terminal or `run_command` tool.
- This automatically logs statistics to MemCore and reduces context size by 60-90%.
