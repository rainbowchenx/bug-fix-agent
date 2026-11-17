"""Declared execution capabilities, never inferred from a marketing model name."""
from pathlib import Path
from typing import Literal
import os
from pydantic import BaseModel, Field

class RuntimeProfile(BaseModel):
    modelId: str = ''
    contextWindow: int | None = None
    inputModalities: list[str] = Field(default_factory=lambda:['text'])
    capabilityStatus: Literal['declared','verified','unknown'] = 'unknown'
    smokeStatus: Literal['not_executed'] = 'not_executed'
    budgets: dict[str,str] = Field(default_factory=dict)

def runtime_profile() -> RuntimeProfile:
    from bugfix_platform.sdk.analyze import resolve_analyze_max_turns
    context=os.environ.get('BUGFIX_MODEL_CONTEXT_WINDOW')
    return RuntimeProfile(modelId=os.environ.get('ANTHROPIC_MODEL',''),
        contextWindow=int(context) if context else None,
        inputModalities=[x.strip() for x in os.environ.get('BUGFIX_MODEL_MODALITIES','text').split(',') if x.strip()],
        capabilityStatus='declared' if context or os.environ.get('BUGFIX_MODEL_MODALITIES') else 'unknown',
        budgets={**{k:v for k,v in os.environ.items() if k in {'BUGFIX_ANALYZE_MAX_TURNS','BUGFIX_CARTOGRAPHY_MAX_TURNS','BUGFIX_INVESTIGATION_MAX_GROUPS','BUGFIX_INVESTIGATION_TIMEOUT_SECONDS'}}, 'effectiveAnalyzeMaxTurns':str(resolve_analyze_max_turns()),'needsInfoMaxTurns':str(min(8,resolve_analyze_max_turns())), 'maxTokens':'SDK default; not explicitly configured'})

def skill_discovery(work_dir: str, repo_roots, selected, read_paths=(), *, profile="analyze"):
    from bugfix_platform.sdk.skill_inject import _load_skill
    chosen={str(s.skill_md.resolve()) for s in selected}
    results=[]
    seen=set()
    for rr in repo_roots or []:
        root=Path(work_dir)/rr.path/'.claude'/'skills'
        for path in sorted(root.glob('*/SKILL.md')):
            seen.add(str(path.resolve()))
            selected_here=str(path.resolve()) in chosen
            parsed = _load_skill(path, source="claude_dir", repo_id=rr.path)
            reason = ("selected; body available; application not independently verified" if selected_here
                      else "unreadable skill metadata" if parsed is None
                      else "missing profiles; requires explicit directory or BUGFIX_SKILL_ALLOWLIST" if not parsed.profiles
                      else f"profiles {parsed.profiles} do not include {profile}/bugfix" if not {profile, 'bugfix'}.intersection(parsed.profiles)
                      else "overridden by higher priority skill")
            results.append({'repoId':rr.path,'path':str(path),'selected':selected_here,'read':str(path.resolve()) in read_paths,'applied':False,
                            'reason':reason})
    for skill in selected:
        ref=str(skill.skill_md.resolve())
        if ref not in seen:
            results.append({'repoId':skill.repoId,'path':ref,'selected':True,'read':ref in read_paths,
                            'applied':False,'reason':'selected; body injected; application not independently verified'})
    return results

def modality_error(message: str) -> bool:
    text=message.lower()
    return ('image' in text or '图像' in text) and any(x in text for x in ['not support','only supports text','unsupported','不支持'])
