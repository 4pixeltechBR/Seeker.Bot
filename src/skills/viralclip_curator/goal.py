"""
Seeker.Bot — ViralClip Curator Goal Factory
src/skills/viralclip_curator/goal.py
"""

from src.skills.viralclip_curator.curator import ViralClipCurator


def create_goal(pipeline):
    return ViralClipCurator(pipeline)
