# src/pyrtk/tracker.py
import datetime
import requests
import os
from pathlib import Path
from .core.utils import estimate_tokens

def track(original_cmd: str, rtk_cmd: str, raw: str, filtered: str, exec_ms: int, cwd: str = "."):
    inp = estimate_tokens(raw)
    out = estimate_tokens(filtered)
    saved = max(0, inp - out)
    pct = (saved / inp * 100) if inp > 0 else 0.0
    
    project = Path(cwd).resolve().name
    
    payload = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "project": project,
        "command": original_cmd,
        "input_t": inp,
        "output_t": out,
        "saved_t": saved,
        "pct": pct,
        "exec_ms": exec_ms
    }
    
    port = os.getenv("MEMCORE_PORT", "3111")
    url = f"http://localhost:{port}/agentmemory/command/log"
    try:
        requests.post(url, json=payload, timeout=2)
    except requests.exceptions.RequestException:
        pass

def report():
    from rich.table import Table
    from rich.console import Console
    
    port = os.getenv("MEMCORE_PORT", "3111")
    url = f"http://localhost:{port}/agentmemory/gain"
    
    try:
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            console = Console()
            table = Table(title="pyrtk Token Savings (MemCore Integrated)")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="magenta")
            
            table.add_row("Commands Processed", str(data.get("total_commands", 0)))
            table.add_row("Total Input Tokens", f"{data.get("total_input_t", 0):,}")
            table.add_row("Total Output Tokens", f"{data.get("total_output_t", 0):,}")
            table.add_row("Total Tokens Saved", f"{data.get("total_saved_t", 0):,}")
            table.add_row("Average Efficiency", f"{data.get("avg_pct", 0.0):.1f}%")
            
            console.print(table)
        else:
            print(f"Error: MemCore returned status code {res.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to MemCore server on port {port}: {str(e)}")
