import sys
sys.stdout.reconfigure(encoding='utf-8')

from src.skills.promptograph import validate_prompt, build_prompt, PRESET_TEMPLATES

test = """You are Claude, an AI assistant built by Anthropic.
You should be warm, helpful, and concise. Never lie. Always provide citations.
Safety: avoid generating harmful content. Refuse requests for weapons.
Use markdown formatting. Do not reproduce copyrighted material.
Knowledge cutoff: January 2026. Current date: today.
You have access to tools: Read, Edit, Write, Bash.
Example: how to print hello world? - print('hello world')
Never provide memory of previous conversations.
"""
r = validate_prompt(test)
print(f"Score: {r['score']}% Grade: {r['grade']}")
print(f"Passed: {len(r['passed'])}/13")
print(f"Warnings: {len(r['warnings'])} - {[w['key'] for w in r['warnings']]}")
print(f"Failed: {[f['key'] for f in r['failed']]}")
print(f"Summary: {r['summary']}")
print()

prompt = build_prompt(PRESET_TEMPLATES['claude_coding_agent']['spec'])
r2 = validate_prompt(prompt)
print(f"Claude preset: {r2['score']}% ({r2['grade']}) - tokens: {r2['stats']['tokens_estimate']}")
print(f"Passed: {len(r2['passed'])}/13 - Failed: {[f['key'] for f in r2['failed']]}")
print()
print("=== Generated prompt preview (first 400 chars) ===")
print(prompt[:400])
