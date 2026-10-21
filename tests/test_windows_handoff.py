"""The Windows scripts cannot run on a Mac, but their wiring can be checked: every python module / file they call
must exist, they must print PASS/FAIL lines, log under results\\windows\\<date>, and match prompts/WINDOWS_AGENT_PROMPT.md."""
import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PS = ROOT / "scripts" / "windows"
NEEDED = ["setup.ps1", "verify_gpu.ps1", "run_tests.ps1", "build_fluidx3d.ps1", "run_fluidx3d_batch.ps1", "bench.ps1",
          "demo.ps1"]


@pytest.mark.parametrize("name", NEEDED)
def test_script_present_and_structured(name):
    text = (PS / name).read_text()
    assert "_common.ps1" in text and "Finish" in text and ("Pass " in text or "Pass '" in text) and "Fail " in text
    assert "results" in (PS / "_common.ps1").read_text()


def test_python_modules_called_exist():
    mods = set()
    for f in list(PS.glob("*.ps1")) + list((ROOT / "scripts" / "linux").glob("*.sh")):
        mods |= set(re.findall(r"(?:-m\s+|'-m',\s*')((?:tools|bench|experiments|service)[\w.]*)", f.read_text()))
    assert {"tools.fluidx3d.batch", "bench.mlups", "bench.fluidx3d_bench", "bench.swarm_bench",
            "experiments.run_experiments", "service.server"} <= mods
    for m in mods:
        importlib.import_module(m)


def test_files_referenced_exist():
    for f in PS.glob("*.ps1"):
        for rel in re.findall(r"(tools\\[\w_]+\.py|scenarios\\[\w_]+\.json|requirements\.txt)", f.read_text()):
            assert (ROOT / rel.replace("\\", "/")).exists(), (f.name, rel)


def test_agent_prompt_names_match_scripts():
    prompt = (ROOT / "prompts" / "WINDOWS_AGENT_PROMPT.md").read_text()
    for name in re.findall(r"scripts/windows/([\w]+\.ps1)", prompt):
        assert (PS / name).exists(), name
    for doc in ("HANDOFF_WINDOWS.md", "PROGRESS.md", "BLOCKERS.md", "AGENTS.md", "TESTING_CHECKLIST_WINDOWS.md"):
        assert (ROOT / doc).exists(), doc
    assert "TESTING_CHECKLIST_WINDOWS.md" in prompt


def test_batch_build_only_flag_exists():
    from tools.fluidx3d import batch
    import inspect
    assert "--build-only" in inspect.getsource(batch.main)
