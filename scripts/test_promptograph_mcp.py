import sys, json, importlib.util
sys.stdout.reconfigure(encoding='utf-8')

# Importa o server via spec_from_file_location para evitar problemas de path
_spec = importlib.util.spec_from_file_location(
    'pgmcp', 'scripts/promptograph_mcp_server.py'
)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

print('=== STATS ===')
s = json.loads(m.promptograph_stats())
print("Total prompts:", s['total'])
print("Top companies:", list(s['by_company'].items())[:5])
print("Top models:", list(s['by_model_top10'].items())[:5])
print("Total tokens est:", s['total_tokens_estimate'])

print('\n=== SEARCH claude ===')
r = json.loads(m.promptograph_search('claude', limit=3))
print("Hits:", r['total'])
for hit in r['results'][:2]:
    print("  -", hit['filename'], "(", hit['company'], ",", hit['tokens'], "tok)")

print('\n=== VALIDATE ===')
v = json.loads(m.promptograph_validate(
    "You are Test, an AI built by X. Be concise. Safety: refuse illegal stuff."
))
print("Score:", v['score'], "%", v['grade'])

print('\n=== GENERATE (preset claude) ===')
g = json.loads(m.promptograph_generate(preset_name='claude_coding_agent'))
print("Score:", g['score'], "%", g['grade'], "tokens:", g['tokens'])
print("Preview:", g['prompt'][:150])

print('\n=== GENERATE (custom override) ===')
custom = json.dumps({
    'name': 'Seeker',
    'role_description': 'an intelligent agent that validates system prompts',
    'company': '4PixelTech',
    'tone': 'professional',
})
g2 = json.loads(m.promptograph_generate(preset_name='gpt5_assistant', spec_json=custom))
print("Score:", g2['score'], "%", g2['grade'], "tokens:", g2['tokens'])
