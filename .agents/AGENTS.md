# Token Compression Rule

When executing shell commands in this workspace:
- ALWAYS use `pyrtk`'s `rtk_run_command` tool instead of the default terminal or `run_command` tool.
- This automatically logs statistics to MemCore and reduces context size by 60-90%.

- Do NOT verify or output token saving stats/telemetry after running commands. Just return what pyrtk output.
